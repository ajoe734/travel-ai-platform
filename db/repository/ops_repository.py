"""Read-only, tenant-scoped operational trace and alert projections for ENG-09.

Callers must use :func:`db.repository.db.tenant_transaction`; the queries do
not set a tenant themselves.  That keeps the application role/RLS boundary
identical to normal product reads and prevents an operations console from
turning into a cross-tenant reporting bypass.
"""
from __future__ import annotations

from typing import Any

import psycopg

from .rows import row_as_dict


def _rows(columns: list[str], result: Any) -> list[dict[str, Any]]:
    return [row_as_dict(columns, row) for row in result.fetchall()]


def assemble_trace(conn: psycopg.Connection, *, tenant_id: str, task_id: str) -> dict[str, Any] | None:
    """Return a complete Case -> Work -> Task audit slice without secrets/PII.

    The attempt-to-observation join deliberately uses ``attempt.id`` (not the
    task ID): a task can have more than one immutable attempt.  Order/payment/
    refund refs are found through the Case, while publication refs are linked
    by the task's stable business key.
    """
    root_columns = ["case_id", "work_id", "task_id", "operation", "business_key", "task_status"]
    root = conn.execute(
        """SELECT c.id, w.id, t.id, t.operation, t.business_key, t.status
           FROM execution_task t JOIN work w ON (w.tenant_id=t.tenant_id AND w.id=t.work_id)
           JOIN case_record c ON (c.tenant_id=w.tenant_id AND c.id=w.case_id)
           WHERE t.tenant_id=%s AND t.id=%s""", (tenant_id, task_id)).fetchone()
    if root is None:
        return None
    trace = row_as_dict(root_columns, root)
    trace["attempt_observations"] = _rows(
        ["attempt_id", "attempt_no", "attempt_kind", "request_ref", "observation_sequence", "outcome", "external_ref", "evidence_ref", "observed_at"],
        conn.execute(
            """SELECT a.id,a.attempt_no,a.attempt_kind,a.request_ref,o.sequence,o.outcome,o.external_ref,o.evidence_ref,o.observed_at
               FROM execution_attempt a LEFT JOIN execution_attempt_observation o
                 ON (o.tenant_id=a.tenant_id AND o.attempt_id=a.id)
               WHERE a.tenant_id=%s AND a.task_id=%s ORDER BY a.attempt_no,o.sequence""", (tenant_id, task_id)),
    )
    trace["completion_evidence"] = _rows(
        ["evidence_id", "external_ref", "source_account", "environment", "observed_at", "verified_at"],
        conn.execute("""SELECT id,external_ref,source_account,environment,observed_at,verified_at
                        FROM completion_evidence WHERE tenant_id=%s AND (task_id=%s OR work_id=%s) ORDER BY observed_at""",
                     (tenant_id, task_id, trace["work_id"])),
    )
    trace["order_payment_refund"] = _rows(
        ["order_id", "supplier_booking_external_ref", "payment_external_transaction_id", "payment_external_transaction", "refund_external_ref"],
        conn.execute(
            """SELECT o.id,o.supplier_booking_external_ref,o.payment_external_transaction_id,p.external_transaction_id,r.provider_refund_id
               FROM order_record o LEFT JOIN payment p ON (p.tenant_id=o.tenant_id AND p.order_id=o.id)
               LEFT JOIN refund r ON (r.tenant_id=p.tenant_id AND r.payment_id=p.id)
               WHERE o.tenant_id=%s AND o.case_id=%s ORDER BY o.id,p.id,r.id""", (tenant_id, trace["case_id"])),
    )
    trace["publications"] = _rows(
        ["publication_id", "channel", "connector_account_id", "environment", "status", "external_reference", "observed_at"],
        conn.execute("""SELECT id,channel,connector_account_id,environment,status,external_reference,observed_at
                        FROM channel_publication WHERE tenant_id=%s AND business_key=%s ORDER BY id""",
                     (tenant_id, trace["business_key"])),
    )
    return trace


def operational_alerts(conn: psycopg.Connection, *, tenant_id: str, now: str) -> dict[str, list[dict[str, Any]]]:
    """Return read-only actionable signals; all queries retain the RLS tenant predicate."""
    queries = {
        "overdue_reconciliation": ("""SELECT id,status,deadline,next_run_at FROM execution_task WHERE tenant_id=%s AND status IN ('UNKNOWN','WAITING') AND (deadline<=%s OR next_run_at<=%s) ORDER BY created_at""", ["task_id", "status", "deadline", "next_run_at"]),
        "expired_execution_lease": ("""SELECT id,status,lease_until FROM execution_task WHERE tenant_id=%s AND status='EXECUTING' AND lease_until<=%s ORDER BY lease_until""", ["task_id", "status", "lease_until"]),
        "authorization_blockers": ("""SELECT DISTINCT t.id,t.status,'REVOCATION' FROM execution_task t JOIN work w ON (w.tenant_id=t.tenant_id AND w.id=t.work_id) JOIN execution_authorization a ON (a.tenant_id=w.tenant_id AND a.work_id=w.id) JOIN LATERAL jsonb_array_elements_text(COALESCE(a.approval_refs, '[]'::jsonb)) ar(approval_id) ON TRUE JOIN approval_revocation r ON (r.tenant_id=a.tenant_id AND r.approval_id=ar.approval_id::uuid) WHERE t.tenant_id=%s AND t.status IN ('NEW','VALIDATING','READY') AND r.effective_at<=%s
                                  UNION ALL SELECT DISTINCT t.id,t.status,'EXPIRED_DECISION' FROM execution_task t JOIN work w ON (w.tenant_id=t.tenant_id AND w.id=t.work_id) JOIN decision_request d ON (d.tenant_id=w.tenant_id AND d.work_id=w.id) WHERE t.tenant_id=%s AND t.status IN ('NEW','VALIDATING','READY') AND (d.status='EXPIRED' OR d.expires_at<=%s)
                                  UNION ALL SELECT DISTINCT t.id,t.status,'EXPIRED_AUTHORIZATION' FROM execution_task t JOIN work w ON (w.tenant_id=t.tenant_id AND w.id=t.work_id) JOIN execution_authorization a ON (a.tenant_id=w.tenant_id AND a.work_id=w.id) WHERE t.tenant_id=%s AND t.status IN ('NEW','VALIDATING','READY') AND a.expiry<=%s""", ["task_id", "status", "reason"]),
        "outbox_backlog": ("""SELECT count(*),min(created_at) FROM outbox_event WHERE tenant_id=%s AND published_at IS NULL""", ["count", "oldest_created_at"]),
        "inbox_exceptions": ("""SELECT id,processing_status,received_at FROM inbox_event WHERE tenant_id=%s AND processing_status IN ('QUARANTINED','DEAD_LETTER') UNION ALL SELECT i.id,'CONFLICT',c.detected_at FROM inbox_event_conflict c JOIN inbox_event i ON (i.tenant_id=c.tenant_id AND i.id=c.inbox_event_id) WHERE c.tenant_id=%s""", ["inbox_event_id", "status", "detected_at"]),
        "stuck_publications": ("""SELECT id,status,external_reference,updated_at FROM channel_publication WHERE tenant_id=%s AND status IN ('DISPATCHING','PENDING','UNKNOWN') AND updated_at<=%s ORDER BY updated_at""", ["publication_id", "status", "external_reference", "updated_at"]),
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for name, (sql, columns) in queries.items():
        arguments = (tenant_id, now, now) if name == "overdue_reconciliation" else ((tenant_id, now, tenant_id, now, tenant_id, now) if name == "authorization_blockers" else ((tenant_id, tenant_id) if name == "inbox_exceptions" else (tenant_id, now)))
        result[name] = _rows(columns, conn.execute(sql, arguments))
    return result
