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
                           version: int, content: dict[str, Any], content_hash: str, approval_id: str | None,
                           approved_at: str) -> None:
    conn.execute("""INSERT INTO service_version
      (tenant_id,id,service_id,version,content,content_hash,approval_id,approved_at)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
      (tenant_id, version_id, service_id, version, json.dumps(content, default=str), content_hash, approval_id, approved_at))

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
