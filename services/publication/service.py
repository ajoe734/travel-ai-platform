"""ENG-08 publication command boundaries.

``prepare_publications`` is called in the short command transaction; callers
must commit it before invoking a connector.  ``record_connector_result`` is a
separate short transaction afterwards.  This deliberately makes it impossible
for a website result to be inferred for an OTA publication.
"""
from __future__ import annotations

import hashlib
import json
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


def _structured_diff(base: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Small, stable audit diff; the immutable full content remains authoritative."""
    base = base or {}
    keys = sorted(set(base) | set(current))
    changes = [{"field": key, "before": base.get(key), "after": current.get(key)}
               for key in keys if base.get(key) != current.get(key)]
    return {"format": "service-version-diff-v1", "changes": changes}


def _hash_content(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PublicationService:
    def create_approved_version(self, conn: Any, *, tenant_id: str, service_id: str,
                                version: int, content: dict[str, Any], approval_id: str, now: str,
                                version_id: str | None = None, base_version: int | None = None,
                                base_content: dict[str, Any] | None = None) -> str:
        """Persist an immutable approved service version before any publish."""
        if not approval_id:
            raise PublicationError("APPROVAL_REQUIRED")
        # Keep connector-result mapping importable in the dependency-light
        # unit suite; this repository is only needed on the create command.
        from db.repository import approval_repository
        approval = approval_repository.get_approval_record(conn, tenant_id=tenant_id, approval_id=approval_id)
        if approval is None or not approval_repository.approval_is_effective(conn, tenant_id=tenant_id, approval_id=approval_id, now=now):
            raise PublicationError("APPROVAL_NOT_EFFECTIVE")
        if approval["canonicalization_version"] != canonical_json.CANONICALIZATION_VERSION:
            raise PublicationError("APPROVAL_CANONICALIZATION_MISMATCH")
        if canonical_json.payload_hash(approval["approved_payload"]) != approval["payload_hash"]:
            raise PublicationError("APPROVAL_PAYLOAD_HASH_MISMATCH")
        matching = [item for item in approval["scope_manifest"]
                    if item.get("operation") == "publication.update"
                    and item.get("resource_ref", {}).get("id") == service_id
                    and item.get("resource_revision") == version]
        if not matching:
            raise PublicationError("APPROVAL_SCOPE_MISMATCH")
        version_id = version_id or str(uuid.uuid4())
        publications.create_service_version(
            conn, tenant_id=tenant_id, version_id=version_id, service_id=service_id, version=version,
            base_version=base_version, content=content, change_diff=_structured_diff(base_content, content),
            content_hash=_hash_content(content), approval_id=approval_id, approved_at=now,
        )
        return version_id

    def prepare_publications(self, conn: Any, *, tenant_id: str, service_version_id: str,
                             service_version: int, targets: list[dict[str, str]], connectors: dict[tuple[str, str, str], Any] | None = None) -> tuple[list[DispatchIntent], list[dict[str, Any]]]:
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
            intents.append(DispatchIntent(publication_id, channel, account, environment, business_key, service_version))
        return intents, blocked

    def dispatch_publication(self, conn: Any, *, tenant_id: str, intent: DispatchIntent, expected_revision: int,
                             connector: Any, now: str, simulate_response_lost: bool = False) -> dict[str, Any]:
        """Capability-check then invoke the mock/adapter exactly once with the durable key."""
        try:
            connector.ensure_capability("publication.update", SideEffect.WRITE)
        except CapabilityUnavailableError as exc:
            return self.record_connector_result(conn, tenant_id=tenant_id, publication_id=intent.publication_id,
                expected_revision=expected_revision, result=Failed(code="CAPABILITY_UNAVAILABLE", message=str(exc), retryable=False,
                side_effect_disposition=SideEffectDisposition.NOT_APPLIED,
                evidence_refs=(), observed_at=now), now=now)
        result = connector.submit_publication(tenant_id, intent.business_key, intent.channel, str(intent.service_version), now,
                                             simulate_response_lost=simulate_response_lost)
        return self.record_connector_result(conn, tenant_id=tenant_id, publication_id=intent.publication_id,
                                            expected_revision=expected_revision, result=result, now=now)

    def reconcile_publication(self, conn: Any, *, tenant_id: str, publication_id: str, expected_revision: int,
                              connector: Any, now: str) -> dict[str, Any]:
        current = publications.get_publication(conn, tenant_id=tenant_id, publication_id=publication_id)
        if current is None or not current["reconciliation_token"]:
            raise PublicationError("RECONCILIATION_CONTEXT_REQUIRED")
        result = connector.reconcile(tenant_id, current["business_key"], current["reconciliation_token"], now)
        return self.record_connector_result(conn, tenant_id=tenant_id, publication_id=publication_id,
                                            expected_revision=expected_revision, result=result, now=now)

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
        if current["status"] in ("LIVE", "BLOCKED"):
            return current
        if isinstance(result, Pending):
            status, kwargs = "PENDING", {"submitted_version": current["desired_version"], "external_reference": result.external_reference, "reconciliation_token": result.reconciliation_token}
        elif isinstance(result, Unknown):
            status, kwargs = "UNKNOWN", {"submitted_version": current["desired_version"], "reconciliation_token": result.reconciliation_token, "external_reference": result.external_reference}
        elif isinstance(result, Failed):
            status, kwargs = "FAILED", {"failure_reason": result.message}
        elif isinstance(result, Succeeded):
            if current.get("external_reference") is not None and result.external_reference != current["external_reference"]:
                raise PublicationError("EXTERNAL_REFERENCE_MISMATCH")
            if str(result.source_revision) != str(current["desired_version"]):
                # Older readback is evidence about an obsolete desired revision, not a failure of this one.
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
