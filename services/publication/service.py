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
from db.repository import publication_repository as publications


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


def _hash_content(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PublicationService:
    def create_approved_version(self, conn: Any, *, tenant_id: str, service_id: str,
                                version: int, content: dict[str, Any], approval_id: str | None, now: str,
                                version_id: str | None = None) -> str:
        """Persist an immutable approved service version before any publish."""
        version_id = version_id or str(uuid.uuid4())
        publications.create_service_version(
            conn, tenant_id=tenant_id, version_id=version_id, service_id=service_id, version=version,
            content=content, content_hash=_hash_content(content), approval_id=approval_id, approved_at=now,
        )
        return version_id

    def prepare_publications(self, conn: Any, *, tenant_id: str, service_version_id: str,
                             service_version: int, targets: list[dict[str, str]]) -> tuple[list[DispatchIntent], list[dict[str, Any]]]:
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
            if access is None or not access["publication_enabled"]:
                reason = (access or {}).get("reason") or "CHANNEL_PUBLICATION_ACCESS_UNAVAILABLE"
                row = publications.observe_publication(conn, tenant_id=tenant_id, publication_id=publication_id,
                    expected_revision=publication["revision"], status="BLOCKED", failure_reason=reason)
                blocked.append(row or publication)
                continue
            intents.append(DispatchIntent(publication_id, channel, account, environment, business_key, service_version))
        return intents, blocked

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
        if current["status"] in ("LIVE", "FAILED", "BLOCKED"):
            return current
        if isinstance(result, Pending):
            status, kwargs = "PENDING", {"submitted_version": current["desired_version"], "external_reference": result.external_reference, "reconciliation_token": result.reconciliation_token}
        elif isinstance(result, Unknown):
            status, kwargs = "UNKNOWN", {"submitted_version": current["desired_version"], "reconciliation_token": result.reconciliation_token}
        elif isinstance(result, Failed):
            status, kwargs = "FAILED", {"failure_reason": result.message, "external_reference": result.external_reference}
        elif isinstance(result, Succeeded):
            if str(result.source_revision) != str(current["desired_version"]):
                status, kwargs = "FAILED", {"failure_reason": "STALE_CHANNEL_READBACK", "external_reference": result.external_reference}
            else:
                status, kwargs = "LIVE", {"submitted_version": current["desired_version"], "observed_version": current["desired_version"], "external_reference": result.external_reference, "observed_at": result.observed_at}
        else:
            raise TypeError(f"unsupported connector result: {type(result)!r}")
        row = publications.observe_publication(conn, tenant_id=tenant_id, publication_id=publication_id,
            expected_revision=expected_revision, status=status, **kwargs)
        if row is None:
            raise PublicationError("PUBLICATION_VERSION_CONFLICT")
        return row
