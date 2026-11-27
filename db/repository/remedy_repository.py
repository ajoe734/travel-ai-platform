"""ENG-07 explicit remedy notification and complaint resolution commands."""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .errors import IdempotencyConflict


def record_remedy_notification(
    conn: psycopg.Connection, *, tenant_id: str, notification_id: str,
    remedy_action_id: str, business_key: str, state: str, evidence: dict[str, Any] | None,
) -> None:
    if state not in ("PENDING", "DELIVERED", "FAILED"):
        raise ValueError("invalid remedy notification state")
    existing = conn.execute(
        "SELECT remedy_action_id, state FROM remedy_notification WHERE tenant_id = %s AND business_key = %s FOR UPDATE",
        (tenant_id, business_key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != str(remedy_action_id):
            raise IdempotencyConflict("notification key is already bound to another remedy action")
        # Delivery is a terminal fact. A late retry/failure must never turn a
        # successfully delivered notification back into a pending action.
        if existing[1] == state or existing[1] == "DELIVERED":
            return
        conn.execute(
            "UPDATE remedy_notification SET state = %s, evidence = %s WHERE tenant_id = %s AND business_key = %s",
            (state, json.dumps(evidence) if evidence is not None else None, tenant_id, business_key),
        )
        return
    conn.execute(
        """INSERT INTO remedy_notification (tenant_id, id, remedy_action_id, business_key, state, evidence)
            VALUES (%s, %s, %s, %s, %s, %s)""",
        (tenant_id, notification_id, remedy_action_id, business_key, state,
         json.dumps(evidence) if evidence is not None else None),
    )


def resolve_complaint(
    conn: psycopg.Connection, *, tenant_id: str, complaint_id: str,
    resolution_reason: str, unresolved_items: list[str], customer_responded: bool | None,
) -> None:
    """The only ENG-07 closeout command; remedy success never calls this."""
    if not resolution_reason.strip():
        raise ValueError("complaint resolution requires a reason")
    if any(not isinstance(item, str) or not item.strip() for item in unresolved_items):
        raise ValueError("unresolved_items must contain only non-empty descriptions")
    if len(set(unresolved_items)) != len(unresolved_items):
        raise ValueError("unresolved_items must not contain duplicates")
    active_actions = conn.execute(
        """SELECT count(*) FROM remedy_action
             WHERE tenant_id = %s AND complaint_id = %s
               AND state IN ('RESERVED', 'SUBMITTED', 'PENDING', 'UNKNOWN')""",
        (tenant_id, complaint_id),
    ).fetchone()[0]
    if active_actions and not unresolved_items:
        raise ValueError("unresolved_items must identify outstanding remedy actions before closeout")
    resolution = {"resolved_at": None, "resolution_reason": resolution_reason,
                  "unresolved_items": unresolved_items}
    if customer_responded is not None:
        resolution["customer_responded"] = customer_responded
    updated = conn.execute(
        """UPDATE complaint
             SET status = 'RESOLVED', revision = revision + 1,
                 resolution = jsonb_set(%s::jsonb, '{resolved_at}', to_jsonb(clock_timestamp()))
             WHERE tenant_id = %s AND id = %s AND status NOT IN ('RESOLVED', 'CLOSED')""",
        (json.dumps(resolution), tenant_id, complaint_id),
    )
    if updated.rowcount == 0:
        raise IdempotencyConflict("complaint is already resolved/closed or does not belong to this tenant")
