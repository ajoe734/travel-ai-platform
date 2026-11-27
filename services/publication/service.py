"""ENG-08 publication command boundaries.

``prepare_publications`` is called in the short command transaction; callers
must commit it before invoking a connector.  ``record_connector_result`` is a
separate short transaction afterwards.  This deliberately makes it impossible
for a website result to be inferred for an OTA publication.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # keep pure result-mapping tests dependency-light
    import psycopg

from connectors.types import Failed, OperationResult, Pending, Succeeded, Unknown
from connectors.types import SideEffect, SideEffectDisposition
from connectors.errors import CapabilityUnavailableError
from db.repository import publication_repository as publications
from services.authorization import canonical_json


class PublicationError(ValueError):
    pass


@dataclass(frozen=True)
class DispatchIntent:
    publication_id: str
    channel: str
    connector_account_id: str
    environment: str
    business_key: str
    service_version: int
    expected_revision: int


def _structured_diff(base: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Small, stable audit diff; the immutable full content remains authoritative."""
    base = base or {}
    keys = sorted(set(base) | set(current))
    changes = [{"field": key, "before": base.get(key), "after": current.get(key)}
               for key in keys if base.get(key) != current.get(key)]
    return {"format": "service-version-diff-v1", "changes": changes}


def _scope_matches(item: dict[str, Any], *, tenant_id: str, service_id: str, version: int,
                   channel: str | None = None, account: str | None = None) -> bool:
    ref = item.get("resource_ref") or {}
    if (item.get("operation") != "publication.update" or ref.get("tenant_id") != tenant_id
            or str(ref.get("id")) != str(service_id) or str(item.get("resource_revision")) != str(version)):
        return False
    return ((channel is None or item.get("channel") == channel)
            and (account is None or item.get("account") == account))


def _assert_approval_integrity(conn: Any, *, tenant_id: str, approval_id: str, now: str,
                               service_id: str, version: int, content: dict[str, Any],
                               channel: str | None = None, account: str | None = None) -> None:
    """Bind every publication command to the immutable approved content/scope."""
    from db.repository import approval_repository
    approval = approval_repository.get_approval_record(conn, tenant_id=tenant_id, approval_id=approval_id)
    if approval is None or not approval_repository.approval_is_effective(
        conn, tenant_id=tenant_id, approval_id=approval_id, now=now
    ):
        raise PublicationError("APPROVAL_NOT_EFFECTIVE")
    if approval["canonicalization_version"] != canonical_json.CANONICALIZATION_VERSION:
        raise PublicationError("APPROVAL_CANONICALIZATION_MISMATCH")
    if canonical_json.payload_hash(approval["approved_payload"]) != approval["payload_hash"]:
        raise PublicationError("APPROVAL_PAYLOAD_HASH_MISMATCH")
    payload = approval["approved_payload"]
    if (str(payload.get("service_id")) != str(service_id) or str(payload.get("version")) != str(version)
            or payload.get("content") != content):
        raise PublicationError("APPROVAL_CONTENT_MISMATCH")
    if not any(_scope_matches(item, tenant_id=tenant_id, service_id=service_id, version=version,
                              channel=channel, account=account) for item in approval["scope_manifest"]):
        raise PublicationError("APPROVAL_SCOPE_MISMATCH")


class PublicationService:
    def create_approved_version(self, conn: Any, *, tenant_id: str, service_id: str,
                                version: int, content: dict[str, Any], approval_id: str, now: str,
                                version_id: str | None = None, base_version: int | None = None,
                                base_content: dict[str, Any] | None = None) -> str:
        """Persist an immutable approved service version before any publish."""
        if not approval_id:
            raise PublicationError("APPROVAL_REQUIRED")
        _assert_approval_integrity(conn, tenant_id=tenant_id, approval_id=approval_id, now=now,
                                   service_id=service_id, version=version, content=content)
        version_id = version_id or str(uuid.uuid4())
        publications.create_service_version(
            conn, tenant_id=tenant_id, version_id=version_id, service_id=service_id, version=version,
            base_version=base_version, content=content, change_diff=_structured_diff(base_content, content),
            content_hash=canonical_json.payload_hash(content), approval_id=approval_id, approved_at=now,
        )
        return version_id

    def prepare_publications(self, conn: Any, *, tenant_id: str, service_version_id: str,
                             service_version: int, targets: list[dict[str, str]], now: str,
                             connectors: dict[tuple[str, str, str], Any] | None = None) -> tuple[list[DispatchIntent], list[dict[str, Any]]]:
        """Create one independent durable row per channel.

        Missing/disabled access becomes BLOCKED with a merchant-actionable
        reason, never an attempted connector call.  The caller commits before
        consuming returned intents outside the DB transaction.
        """
        intents: list[DispatchIntent] = []
        blocked: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for target in targets:
            channel, account, environment = target["channel"], target["connector_account_id"], target["environment"]
            key = (channel, account, environment)
            if key in seen:
                raise PublicationError("duplicate channel/account/environment target")
            seen.add(key)
            publication_id = str(uuid.uuid4())
            business_key = f"publication:{service_version_id}:{channel}:{account}:{environment}"
            publication = publications.create_publication(
                conn, tenant_id=tenant_id, publication_id=publication_id, service_version_id=service_version_id,
                channel=channel, connector_account_id=account, environment=environment,
                business_key=business_key, desired_version=service_version,
            )
            access = publications.get_channel_access(conn, tenant_id=tenant_id, channel=channel,
                                                     connector_account_id=account, environment=environment)
            connector = (connectors or {}).get(key)
            descriptor = connector.describe_capability("publication.update") if connector else None
            if access is None or not access["publication_enabled"] or (descriptor is not None and not descriptor.is_callable()):
                reason = (access or {}).get("reason") or "CHANNEL_PUBLICATION_ACCESS_UNAVAILABLE"
                if descriptor is not None and not descriptor.is_callable():
                    reason = f"CAPABILITY_UNAVAILABLE:{descriptor.support.value}:{descriptor.authorization_state.value}:{descriptor.merchant_consent.value}:{descriptor.operational_availability.value}"
                row = publications.observe_publication(conn, tenant_id=tenant_id, publication_id=publication_id,
                    expected_revision=publication["revision"], status="BLOCKED", failure_reason=reason)
                blocked.append(row or publication)
                continue
            version_row = publications.get_service_version(conn, tenant_id=tenant_id, service_version_id=service_version_id)
            if version_row is None or int(version_row["version"]) != int(service_version):
                raise PublicationError("SERVICE_VERSION_NOT_FOUND")
            try:
                _assert_approval_integrity(conn, tenant_id=tenant_id, approval_id=version_row["approval_id"],
                                           now=now, service_id=version_row["service_id"],
                                           version=service_version, content=version_row["content"], channel=channel, account=account)
            except PublicationError as exc:
                row = publications.observe_publication(conn, tenant_id=tenant_id, publication_id=publication_id,
                    expected_revision=publication["revision"], status="BLOCKED", failure_reason=str(exc))
                blocked.append(row or publication)
                continue
            intents.append(DispatchIntent(publication_id, channel, account, environment, business_key, service_version, publication["revision"]))
        return intents, blocked

    def claim_dispatch(self, conn: Any, *, tenant_id: str, intent: DispatchIntent, connector: Any,
                       now: str) -> DispatchIntent | None:
        """TX1: recheck access/approval and durably claim before any connector I/O."""
        current = publications.get_publication_service_version(conn, tenant_id=tenant_id, publication_id=intent.publication_id)
        if current is None or current["revision"] != intent.expected_revision or current["status"] != "NOT_STARTED":
            raise PublicationError("PUBLICATION_VERSION_CONFLICT")
        try:
            _assert_approval_integrity(conn, tenant_id=tenant_id, approval_id=current["approval_id"], now=now,
                                       service_id=current["service_id"], version=current["desired_version"], content=current["content"],
                                       channel=current["channel"], account=current["connector_account_id"])
            access = publications.get_channel_access(conn, tenant_id=tenant_id, channel=current["channel"],
                                                     connector_account_id=current["connector_account_id"], environment=current["environment"])
            if access is None or not access["publication_enabled"]:
                raise PublicationError((access or {}).get("reason") or "CHANNEL_PUBLICATION_ACCESS_UNAVAILABLE")
            connector.ensure_capability("publication.update", SideEffect.WRITE)
        except (PublicationError, CapabilityUnavailableError) as exc:
            row = publications.observe_publication(conn, tenant_id=tenant_id, publication_id=intent.publication_id,
                expected_revision=intent.expected_revision, status="BLOCKED", failure_reason=str(exc))
            if row is None:
                raise PublicationError("PUBLICATION_VERSION_CONFLICT")
            return None
        claimed = publications.claim_publication_dispatch(conn, tenant_id=tenant_id, publication_id=intent.publication_id,
                                                           expected_revision=intent.expected_revision)
        if claimed is None:
            raise PublicationError("PUBLICATION_VERSION_CONFLICT")
        return DispatchIntent(claimed["id"], claimed["channel"], claimed["connector_account_id"], claimed["environment"],
                              claimed["business_key"], claimed["desired_version"], claimed["revision"])

    def dispatch_publication(self, *, tenant_id: str, intent: DispatchIntent, connector: Any, now: str,
                             simulate_response_lost: bool = False) -> OperationResult:
        """Transaction-free connector I/O. Persist its result in a new TX via record_connector_result."""
        try:
            connector.ensure_capability("publication.update", SideEffect.WRITE)
        except CapabilityUnavailableError as exc:
            return Failed(code="CAPABILITY_UNAVAILABLE", message=str(exc), retryable=False,
                side_effect_disposition=SideEffectDisposition.NOT_APPLIED,
                evidence_refs=(), observed_at=now)
        return connector.submit_publication(tenant_id, intent.business_key, intent.channel, str(intent.service_version), now,
                                            simulate_response_lost=simulate_response_lost)

    def claim_reconciliation(self, conn: Any, *, tenant_id: str, publication_id: str, expected_revision: int) -> DispatchIntent:
        """TX1: reserve a known submitted/unknown row before the read-only connector call."""
        current = publications.get_publication(conn, tenant_id=tenant_id, publication_id=publication_id)
        if current is None or current["revision"] != expected_revision or not current["reconciliation_token"]:
            raise PublicationError("RECONCILIATION_CONTEXT_REQUIRED")
        claimed = publications.claim_publication_reconciliation(conn, tenant_id=tenant_id, publication_id=publication_id,
                                                                 expected_revision=expected_revision)
        if claimed is None:
            raise PublicationError("PUBLICATION_VERSION_CONFLICT")
        return DispatchIntent(claimed["id"], claimed["channel"], claimed["connector_account_id"], claimed["environment"],
                              claimed["business_key"], claimed["desired_version"], claimed["revision"])

    def reconcile_publication(self, *, tenant_id: str, intent: DispatchIntent, reconciliation_token: str,
                              connector: Any, now: str) -> OperationResult:
        """Transaction-free connector readback; caller records in TX2."""
        return connector.reconcile(tenant_id, intent.business_key, reconciliation_token, now)

    def record_connector_result(self, conn: Any, *, tenant_id: str, publication_id: str,
                                expected_revision: int, result: OperationResult, now: str) -> dict[str, Any]:
        """Save a provider response/readback for exactly one publication row.

        A `Succeeded` response only turns LIVE when its source revision equals
        this row's desired version; stale events are retained as FAILED rather
        than overwriting the newer desired version.
        """
        current = publications.get_publication(conn, tenant_id=tenant_id, publication_id=publication_id)
        if current is None:
            raise PublicationError("publication not found for tenant")
        if current["revision"] != expected_revision:
            raise PublicationError("PUBLICATION_VERSION_CONFLICT")
        if current["status"] in ("LIVE", "BLOCKED", "FAILED"):
            return current
        if isinstance(result, Pending):
            status, kwargs = "PENDING", {"submitted_version": current["desired_version"], "external_reference": result.external_reference, "reconciliation_token": result.reconciliation_token}
        elif isinstance(result, Unknown):
            status, kwargs = "UNKNOWN", {"submitted_version": current["desired_version"], "reconciliation_token": result.reconciliation_token, "external_reference": result.external_reference}
        elif isinstance(result, Failed):
            status = "BLOCKED" if result.code == "CAPABILITY_UNAVAILABLE" else "FAILED"
            kwargs = {"failure_reason": result.message}
        elif isinstance(result, Succeeded):
            if current.get("external_reference") is not None and result.external_reference != current["external_reference"]:
                raise PublicationError("EXTERNAL_REFERENCE_MISMATCH")
            if str(result.source_revision) != str(current["desired_version"]):
                # Older readback is evidence about an obsolete desired revision, not a failure of this one.
                return current
            elif publications.has_newer_live_publication(conn, tenant_id=tenant_id, publication_id=publication_id):
                return current
            else:
                status, kwargs = "LIVE", {"submitted_version": current["desired_version"], "observed_version": current["desired_version"], "external_reference": result.external_reference, "observed_at": result.observed_at}
        else:
            raise TypeError(f"unsupported connector result: {type(result)!r}")
        row = publications.observe_publication(conn, tenant_id=tenant_id, publication_id=publication_id,
            expected_revision=expected_revision, status=status, **kwargs)
        if row is None:
            raise PublicationError("PUBLICATION_VERSION_CONFLICT")
        return row

    def retry_failed_publication(self, conn: Any, *, tenant_id: str, publication_id: str,
                                 expected_revision: int, connector: Any, now: str) -> DispatchIntent | None:
        """Reopen only FAILED then run the same approval/access/claim gate as first dispatch."""
        reopened = publications.retry_failed_publication(conn, tenant_id=tenant_id, publication_id=publication_id,
                                                          expected_revision=expected_revision)
        if reopened is None:
            raise PublicationError("PUBLICATION_RETRY_NOT_ALLOWED")
        intent = DispatchIntent(reopened["id"], reopened["channel"], reopened["connector_account_id"], reopened["environment"],
                                reopened["business_key"], reopened["desired_version"], reopened["revision"])
        return self.claim_dispatch(conn, tenant_id=tenant_id, intent=intent, connector=connector, now=now)
