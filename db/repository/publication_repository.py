"""ENG-08 persistence primitives for independent channel publication.

The projection deliberately has one row and one stable business key per
channel. A successful website readback never updates an OTA row.
"""
from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING
if TYPE_CHECKING:
    import psycopg
from .rows import row_as_dict

_PUBLICATION_COLUMNS = [
    "tenant_id", "id", "service_version_id", "channel", "connector_account_id", "environment",
    "business_key", "desired_version", "submitted_version", "observed_version", "status",
    "external_reference", "reconciliation_token", "observed_at", "failure_reason", "revision",
    "created_at", "updated_at",
]

def create_service_version(conn: Any, *, tenant_id: str, version_id: str, service_id: str,
                           version: int, base_version: int | None, content: dict[str, Any], change_diff: dict[str, Any],
                           content_hash: str, approval_id: str, approved_at: str) -> None:
    conn.execute("""INSERT INTO service_version
      (tenant_id,id,service_id,version,base_version,content,change_diff,content_hash,approval_id,approved_at)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
      (tenant_id, version_id, service_id, version, base_version, json.dumps(content, default=str),
       json.dumps(change_diff, default=str), content_hash, approval_id, approved_at))

def get_service_version(conn: Any, *, tenant_id: str, service_version_id: str) -> dict[str, Any] | None:
    columns = ["tenant_id", "id", "service_id", "version", "base_version", "content", "change_diff", "content_hash", "approval_id", "approved_at"]
    row = conn.execute("SELECT " + ", ".join(columns) + " FROM service_version WHERE tenant_id=%s AND id=%s", (tenant_id, service_version_id)).fetchone()
    return row_as_dict(columns, row) if row else None

def publication_summary(conn: Any, *, tenant_id: str, service_version_id: str) -> dict[str, int]:
    rows = conn.execute("""SELECT status, count(*) FROM channel_publication
        WHERE tenant_id=%s AND service_version_id=%s GROUP BY status""", (tenant_id, service_version_id)).fetchall()
    return {status: count for status, count in rows}

def set_channel_access(conn: Any, *, tenant_id: str, channel: str, connector_account_id: str,
                       environment: str, publication_enabled: bool, reason: str | None) -> None:
    conn.execute("""INSERT INTO channel_publication_access
      (tenant_id,channel,connector_account_id,environment,publication_enabled,reason)
      VALUES (%s,%s,%s,%s,%s,%s)
      ON CONFLICT (tenant_id,channel,connector_account_id,environment) DO UPDATE
      SET publication_enabled=EXCLUDED.publication_enabled, reason=EXCLUDED.reason,
          revision=channel_publication_access.revision+1""",
      (tenant_id,channel,connector_account_id,environment,publication_enabled,reason))

def get_channel_access(conn: Any, *, tenant_id: str, channel: str, connector_account_id: str,
                       environment: str) -> dict[str, Any] | None:
    row=conn.execute("SELECT tenant_id,channel,connector_account_id,environment,publication_enabled,reason,revision,updated_at FROM channel_publication_access WHERE tenant_id=%s AND channel=%s AND connector_account_id=%s AND environment=%s",(tenant_id,channel,connector_account_id,environment)).fetchone()
    return row_as_dict(["tenant_id","channel","connector_account_id","environment","publication_enabled","reason","revision","updated_at"],row) if row else None

def create_publication(conn: Any, *, tenant_id: str, publication_id: str, service_version_id: str,
                       channel: str, connector_account_id: str, environment: str, business_key: str,
                       desired_version: int) -> dict[str, Any]:
    row=conn.execute("""INSERT INTO channel_publication
      (tenant_id,id,service_version_id,channel,connector_account_id,environment,business_key,desired_version,status)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'NOT_STARTED') RETURNING """+", ".join(_PUBLICATION_COLUMNS),
      (tenant_id,publication_id,service_version_id,channel,connector_account_id,environment,business_key,desired_version)).fetchone()
    return row_as_dict(_PUBLICATION_COLUMNS,row)

def get_publication(conn: Any, *, tenant_id: str, publication_id: str) -> dict[str, Any] | None:
    row=conn.execute("SELECT "+", ".join(_PUBLICATION_COLUMNS)+" FROM channel_publication WHERE tenant_id=%s AND id=%s",(tenant_id,publication_id)).fetchone()
    return row_as_dict(_PUBLICATION_COLUMNS,row) if row else None

def get_publication_service_version(conn: Any, *, tenant_id: str, publication_id: str) -> dict[str, Any] | None:
    """Read the immutable version and its approval alongside a publication.

    Dispatch-time authorization must be re-evaluated from persisted state,
    rather than trusting an intent which may have waited in an outbox.
    """
    columns = _PUBLICATION_COLUMNS + ["service_id", "approval_id", "content", "content_hash"]
    row = conn.execute("""SELECT p.tenant_id, p.id, p.service_version_id, p.channel,
      p.connector_account_id, p.environment, p.business_key, p.desired_version,
      p.submitted_version, p.observed_version, p.status, p.external_reference,
      p.reconciliation_token, p.observed_at, p.failure_reason, p.revision,
      p.created_at, p.updated_at, sv.service_id, sv.approval_id, sv.content, sv.content_hash
      FROM channel_publication p
      JOIN service_version sv ON (sv.tenant_id=p.tenant_id AND sv.id=p.service_version_id
                                  AND sv.version=p.desired_version)
      WHERE p.tenant_id=%s AND p.id=%s""", (tenant_id, publication_id)).fetchone()
    return row_as_dict(columns, row) if row else None

def observe_publication(conn: Any, *, tenant_id: str, publication_id: str, expected_revision: int,
                        status: str, submitted_version: int | None = None, observed_version: int | None = None,
                        external_reference: str | None = None, reconciliation_token: str | None = None,
                        observed_at: str | None = None, failure_reason: str | None = None) -> dict[str, Any] | None:
    row=conn.execute("""UPDATE channel_publication SET status=%s,
      submitted_version=COALESCE(%s,submitted_version), observed_version=COALESCE(%s,observed_version),
      external_reference=COALESCE(%s,external_reference), reconciliation_token=COALESCE(%s,reconciliation_token),
      observed_at=COALESCE(%s,observed_at), failure_reason=COALESCE(%s,failure_reason), revision=revision+1
      WHERE tenant_id=%s AND id=%s AND revision=%s RETURNING """+", ".join(_PUBLICATION_COLUMNS),
      (status,submitted_version,observed_version,external_reference,reconciliation_token,observed_at,failure_reason,tenant_id,publication_id,expected_revision)).fetchone()
    return row_as_dict(_PUBLICATION_COLUMNS,row) if row else None

def claim_publication_dispatch(conn: Any, *, tenant_id: str, publication_id: str,
                               expected_revision: int) -> dict[str, Any] | None:
    """Atomically reserve a NOT_STARTED row before connector I/O.

    ``DISPATCHING`` is deliberately a durable local state: after commit, one
    worker owns the business key and any crash after an external write is
    reconciled, never blindly re-sent.
    """
    row = conn.execute("""UPDATE channel_publication SET status='DISPATCHING',
      revision=revision+1 WHERE tenant_id=%s AND id=%s AND revision=%s AND status='NOT_STARTED'
      RETURNING """ + ", ".join(_PUBLICATION_COLUMNS),
      (tenant_id, publication_id, expected_revision)).fetchone()
    return row_as_dict(_PUBLICATION_COLUMNS, row) if row else None

def claim_publication_reconciliation(conn: Any, *, tenant_id: str, publication_id: str,
                                     expected_revision: int) -> dict[str, Any] | None:
    """CAS-reserve one PENDING/UNKNOWN readback without changing its meaning."""
    row = conn.execute("""UPDATE channel_publication SET revision=revision+1
      WHERE tenant_id=%s AND id=%s AND revision=%s AND status IN ('PENDING','UNKNOWN')
      RETURNING """ + ", ".join(_PUBLICATION_COLUMNS),
      (tenant_id, publication_id, expected_revision)).fetchone()
    return row_as_dict(_PUBLICATION_COLUMNS, row) if row else None

def has_newer_live_publication(conn: Any, *, tenant_id: str, publication_id: str) -> bool:
    """Whether this target already has a later live service revision."""
    row = conn.execute("""SELECT 1 FROM channel_publication current_p
      JOIN service_version current_sv
        ON (current_sv.tenant_id=current_p.tenant_id AND current_sv.id=current_p.service_version_id)
      JOIN service_version later_sv
        ON (later_sv.tenant_id=current_sv.tenant_id AND later_sv.service_id=current_sv.service_id
            AND later_sv.version > current_sv.version)
      JOIN channel_publication later_p
        ON (later_p.tenant_id=later_sv.tenant_id AND later_p.service_version_id=later_sv.id
            AND later_p.channel=current_p.channel
            AND later_p.connector_account_id=current_p.connector_account_id
            AND later_p.environment=current_p.environment AND later_p.status='LIVE')
      WHERE current_p.tenant_id=%s AND current_p.id=%s LIMIT 1""",
      (tenant_id, publication_id)).fetchone()
    return row is not None

def retry_failed_publication(conn: Any, *, tenant_id: str, publication_id: str, expected_revision: int) -> dict[str, Any] | None:
    """Only a FAILED channel is reopened; LIVE/PENDING/UNKNOWN channels are never re-dispatched."""
    row = conn.execute("""UPDATE channel_publication
       SET status='NOT_STARTED', failure_reason=NULL, reconciliation_token=NULL, revision=revision+1
       WHERE tenant_id=%s AND id=%s AND revision=%s AND status='FAILED'
       RETURNING """ + ", ".join(_PUBLICATION_COLUMNS),
       (tenant_id, publication_id, expected_revision)).fetchone()
    return row_as_dict(_PUBLICATION_COLUMNS, row) if row else None
