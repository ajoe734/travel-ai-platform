"""ENG-09 hosted-PostgreSQL verification for RLS operational projections."""
from __future__ import annotations

import hashlib
import uuid

from db.repository import db as repo_db, execution_repository, ops_repository, outbox_inbox_repository, work_repository


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _task(conn, tenant_id, work_id, *, status="WAITING", deadline="2020-01-01T00:00:00Z"):
    task_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        execution_repository.create_execution_task(conn, tenant_id=tenant_id, task_id=task_id, work_id=work_id,
            kind="ACTION", operation="supplier.booking.create", business_key=f"booking:{task_id}", request_hash=_hash(task_id),
            request_snapshot={}, postcondition_version="v1", postcondition={}, deadline=deadline)
        execution_repository.update_task_status(conn, tenant_id=tenant_id, task_id=task_id, expected_revision=1,
            new_status=status, next_run_at="2020-01-01T00:00:00Z")
    return task_id


def test_trace_joins_attempt_to_observation_and_hides_other_tenant(conn, tenant_a, tenant_b, case_factory, work_factory, payment_chain_factory):
    case_a, case_b = case_factory(tenant_a), case_factory(tenant_b)
    work_a, work_b = work_factory(tenant_a, case_a), work_factory(tenant_b, case_b)
    task_a, task_b = _task(conn, tenant_a, work_a), _task(conn, tenant_b, work_b)
    attempt_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_a):
        execution_repository.record_attempt(conn, tenant_id=tenant_a, attempt_id=attempt_id, task_id=task_a, attempt_no=1,
            attempt_kind="DISPATCH", fence_token=1, request_hash=_hash("attempt"), started_at="2026-01-01T00:00:00Z")
        execution_repository.append_observation(conn, tenant_id=tenant_a, attempt_id=attempt_id, sequence=1,
            observed_at="2026-01-01T00:00:01Z", transport_result="TIMEOUT", outcome="UNKNOWN", external_ref="provider-1")
        work_repository.create_completion_evidence(conn, tenant_id=tenant_a, evidence_id=str(uuid.uuid4()), work_id=work_a,
            task_id=task_a, evidence_type="READBACK", environment="MOCK", external_ref="provider-1",
            observed_at="2026-01-01T00:01:00Z", verifier_version="test")
    payment_chain_factory(tenant_a, case_a, 100)
    with repo_db.tenant_transaction(conn, tenant_a):
        trace = ops_repository.assemble_trace(conn, tenant_id=tenant_a, task_id=task_a)
        foreign = ops_repository.assemble_trace(conn, tenant_id=tenant_a, task_id=task_b)
    assert trace["case_id"] == case_a
    assert trace["attempt_observations"][0]["attempt_id"] == attempt_id
    assert trace["attempt_observations"][0]["external_ref"] == "provider-1"
    assert trace["completion_evidence"][0]["external_ref"] == "provider-1"
    assert foreign is None


def test_alerts_detect_actionable_rows_without_false_positive_or_cross_tenant(conn, tenant_a, tenant_b, case_factory, work_factory):
    task_a = _task(conn, tenant_a, work_factory(tenant_a, case_factory(tenant_a)))
    task_b = _task(conn, tenant_b, work_factory(tenant_b, case_factory(tenant_b)))
    with repo_db.tenant_transaction(conn, tenant_a):
        outbox_inbox_repository.append_outbox_event(conn, tenant_id=tenant_a, event_id=str(uuid.uuid4()), aggregate_type="WORK",
            aggregate_id=uuid.UUID(task_a), sequence=1, event_type="test", schema_version="v1", payload={}, occurred_at="2020-01-01T00:00:00Z")
        event_id = str(uuid.uuid4())
        outbox_inbox_repository.append_outbox_event(conn, tenant_id=tenant_a, event_id=event_id, aggregate_type="WORK",
            aggregate_id=uuid.UUID(task_a), sequence=2, event_type="recovery", schema_version="v1", payload={}, occurred_at="2020-01-01T00:00:00Z")
        outbox_inbox_repository.mark_outbox_published(conn, tenant_id=tenant_a, event_id=event_id)
        redelivered = conn.execute("SELECT id, dispatch_attempts FROM outbox_event WHERE tenant_id=%s AND id=%s", (tenant_a, event_id)).fetchone()
        alerts = ops_repository.operational_alerts(conn, tenant_id=tenant_a, now="2026-01-01T00:00:00Z")
    assert [row["task_id"] for row in alerts["overdue_reconciliation"]] == [task_a]
    assert alerts["outbox_backlog"] == [{"count": 1, "oldest_created_at": alerts["outbox_backlog"][0]["oldest_created_at"]}]
    assert not alerts["expired_execution_lease"]
    assert task_b not in str(alerts)
    assert str(redelivered[0]) == event_id and redelivered[1] == 1
