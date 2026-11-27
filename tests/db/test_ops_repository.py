"""ENG-09 hosted-PostgreSQL verification for RLS operational projections."""
from __future__ import annotations

import hashlib
import json
import uuid

from db.repository import approval_repository, db as repo_db, execution_repository, ops_repository, outbox_inbox_repository, publication_repository, work_repository
from services.authorization import canonical_json


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
    chain = payment_chain_factory(tenant_a, case_a, 100)
    with repo_db.tenant_transaction(conn, tenant_a):
        conn.execute("UPDATE order_record SET supplier_booking_external_ref='booking-1', payment_external_transaction_id='order-payment-1' WHERE tenant_id=%s AND id=%s", (tenant_a, chain["order_id"]))
        conn.execute("UPDATE payment SET external_transaction_id='payment-1' WHERE tenant_id=%s AND id=%s", (tenant_a, chain["payment_id"]))
        conn.execute("""INSERT INTO refund (tenant_id,id,payment_id,business_key,amount_minor_units,currency,currency_scale_ref,state,provider_refund_id)
                        VALUES (%s,%s,%s,%s,1,'TWD','iso4217-minor-unit-2','SUCCEEDED','refund-1')""", (tenant_a, str(uuid.uuid4()), chain["payment_id"], f"refund:{task_a}"))
        decision_id, approval_id, version_id, service_id = (str(uuid.uuid4()) for _ in range(4))
        content = {"title": "trace publication"}
        approved_payload = {"purpose": "publish", "service_id": service_id, "version": 1, "content": content}
        approval_repository.create_decision_request(conn, tenant_id=tenant_a, decision_id=decision_id, revision=1, work_id=work_a,
            decision_type="SERVICE_VERSION_APPROVAL", options=[{"id": "approve"}], payload_hash="0" * 64, target_revision=1,
            expires_at="2030-01-01T00:00:00Z", requested_role="MERCHANT_ADMIN")
        approval_repository.approve_decision(conn, tenant_id=tenant_a, decision_id=decision_id, reviewed_revision=1, selected_option_id="approve",
            approval_id=approval_id, approved_by={"actor_kind": "HUMAN_MERCHANT", "actor_id": "merchant"}, verified_actor_ref="test",
            approved_payload=approved_payload, payload_hash=canonical_json.payload_hash(approved_payload), scope_manifest=[], approved_at="2020-01-01T00:00:00Z")
        publication_repository.create_service_version(conn, tenant_id=tenant_a, version_id=version_id, service_id=service_id, version=1,
            base_version=None, content=content, change_diff={}, content_hash=canonical_json.payload_hash(content), approval_id=approval_id, approved_at="2020-01-01T00:00:00Z")
        publication = publication_repository.create_publication(conn, tenant_id=tenant_a, publication_id=str(uuid.uuid4()), service_version_id=version_id,
            channel="ota", connector_account_id="trace-account", environment="MOCK", business_key=f"booking:{task_a}", desired_version=1)
        publication_repository.observe_publication(conn, tenant_id=tenant_a, publication_id=publication["id"], expected_revision=publication["revision"],
            status="PENDING", submitted_version=1, external_reference="publication-1", reconciliation_token="trace-token")
        trace = ops_repository.assemble_trace(conn, tenant_id=tenant_a, task_id=task_a)
        foreign = ops_repository.assemble_trace(conn, tenant_id=tenant_a, task_id=task_b)
    assert trace["case_id"] == case_a
    assert trace["attempt_observations"][0]["attempt_id"] == attempt_id
    assert trace["attempt_observations"][0]["external_ref"] == "provider-1"
    assert trace["completion_evidence"][0]["external_ref"] == "provider-1"
    assert trace["order_payment_refund"] == [{"order_id": chain["order_id"], "supplier_booking_external_ref": "booking-1", "payment_external_transaction_id": "order-payment-1", "payment_external_transaction": "payment-1", "refund_external_ref": "refund-1"}]
    assert trace["publications"][0]["external_reference"] == "publication-1"
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
        alerts = ops_repository.operational_alerts(conn, tenant_id=tenant_a, now="2026-01-01T00:00:00Z", stale_before="2020-01-01T00:00:00Z")
    assert [row["task_id"] for row in alerts["overdue_reconciliation"]] == [task_a]
    assert alerts["outbox_backlog"] == [{"count": 1, "oldest_created_at": alerts["outbox_backlog"][0]["oldest_created_at"]}]
    assert not alerts["expired_execution_lease"]
    assert task_b not in str(alerts)
    assert str(redelivered[0]) == event_id and redelivered[1] == 1


def test_alerts_cover_each_class_and_use_tenant_scoped_ref_json(conn, tenant_a, tenant_b, case_factory, work_factory):
    """Exercise every ENG-09 alert SQL path against the migrated schema/RLS role."""
    case_id, work_id = case_factory(tenant_a), None
    work_id = work_factory(tenant_a, case_id)
    ready_task = _task(conn, tenant_a, work_id, status="READY", deadline="2030-01-01T00:00:00Z")
    lease_task = _task(conn, tenant_a, work_id, status="EXECUTING", deadline="2030-01-01T00:00:00Z")
    decision_id, approval_id, authorization_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_a):
        conn.execute("UPDATE execution_task SET lease_until='2020-01-01T00:00:00Z' WHERE tenant_id=%s AND id=%s", (tenant_a, lease_task))
        approval_repository.create_decision_request(conn, tenant_id=tenant_a, decision_id=decision_id, revision=1, work_id=work_id,
            decision_type="BOOKING_CONFIRMATION", options=[{"id": "accept"}], payload_hash="0" * 64, target_revision=1,
            # A resolved decision whose original expiry is in the past is not
            # an authorization blocker.  Only a still-PENDING decision is.
            expires_at="2020-01-01T00:00:00Z", requested_role="CUSTOMER")
        approval_repository.approve_decision(conn, tenant_id=tenant_a, decision_id=decision_id, reviewed_revision=1, selected_option_id="accept",
            approval_id=approval_id, approved_by={"actor_kind": "CUSTOMER", "actor_id": "merchant"}, verified_actor_ref="test",
            approved_payload={}, payload_hash=canonical_json.payload_hash({}), scope_manifest=[], approved_at="2020-01-01T00:00:00Z")
        resolved_only = ops_repository.operational_alerts(
            conn, tenant_id=tenant_a, now="2026-01-01T00:00:00Z", stale_before="2020-01-01T00:00:00Z"
        )
        assert not resolved_only["authorization_blockers"]
        conn.execute("""INSERT INTO execution_authorization
            (tenant_id,id,work_id,root_business_key,capabilities,approval_refs,manifest_hash,expiry,issued_at)
            VALUES (%s,%s,%s,'booking:ops',%s,%s,%s,'2020-01-01T00:00:00Z','2020-01-01T00:00:00Z')""",
            (tenant_a, authorization_id, work_id, json.dumps(["booking.create"]), json.dumps([{"tenant_id": tenant_a, "id": approval_id}]), "0" * 64))
        approval_repository.create_decision_request(conn, tenant_id=tenant_a, decision_id=str(uuid.uuid4()), revision=1,
            work_id=work_id, decision_type="BOOKING_CONFIRMATION", options=[{"id": "accept"}], payload_hash="1" * 64,
            target_revision=1, expires_at="2020-01-01T00:00:00Z", requested_role="CUSTOMER")
        approval_repository.revoke_approval(conn, tenant_id=tenant_a, revocation_id=str(uuid.uuid4()), approval_id=approval_id,
            revoked_by={"actor_kind": "EMPLOYEE", "actor_id": "merchant"}, reason="withdrawn", effective_at="2020-01-01T00:00:00Z")
        service_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
        publication_repository.create_service_version(conn, tenant_id=tenant_a, version_id=version_id, service_id=service_id,
            version=1, base_version=None, content={"title": "ops alerts"}, change_diff={},
            content_hash=canonical_json.payload_hash({"title": "ops alerts"}), approval_id=approval_id,
            approved_at="2020-01-01T00:00:00Z")
        dispatching = publication_repository.create_publication(conn, tenant_id=tenant_a, publication_id=str(uuid.uuid4()),
            service_version_id=version_id, channel="dispatching", connector_account_id="ops", environment="MOCK",
            business_key="publication:dispatching", desired_version=1)
        dispatching = publication_repository.claim_publication_dispatch(conn, tenant_id=tenant_a,
            publication_id=dispatching["id"], expected_revision=dispatching["revision"])
        pending = publication_repository.create_publication(conn, tenant_id=tenant_a, publication_id=str(uuid.uuid4()),
            service_version_id=version_id, channel="pending", connector_account_id="ops", environment="MOCK",
            business_key="publication:pending", desired_version=1)
        pending = publication_repository.observe_publication(conn, tenant_id=tenant_a, publication_id=pending["id"],
            expected_revision=pending["revision"], status="PENDING", submitted_version=1,
            external_reference="pending-external", reconciliation_token="pending-token")
        first = outbox_inbox_repository.record_inbound_event(conn, tenant_id=tenant_a, event_id=str(uuid.uuid4()), connector_account_id=None,
            environment=None, producer="ops-test", source_event_id="event-1", raw_hash=_hash("first"), raw_payload={})
        outbox_inbox_repository.record_inbound_event(conn, tenant_id=tenant_a, event_id=str(uuid.uuid4()), connector_account_id=None,
            environment=None, producer="ops-test", source_event_id="event-1", raw_hash=_hash("second"), raw_payload={})
        assert first.outcome == outbox_inbox_repository.InboxOutcome.CREATED
        fresh_alerts = ops_repository.operational_alerts(conn, tenant_id=tenant_a, now="2026-01-01T00:00:00Z", stale_before="2020-01-01T00:00:00Z")
        alerts = ops_repository.operational_alerts(conn, tenant_id=tenant_a, now="2026-01-01T00:00:00Z", stale_before="2099-01-01T00:00:00Z")
    assert lease_task in [row["task_id"] for row in alerts["expired_execution_lease"]]
    assert {row["reason"] for row in alerts["authorization_blockers"]} == {
        "REVOCATION", "EXPIRED_DECISION", "EXPIRED_AUTHORIZATION"
    }
    assert alerts["inbox_exceptions"]
    assert not fresh_alerts["stuck_publications"], "fresh publications must not alert at an explicit old staleness cutoff"
    assert {(row["publication_id"], row["status"]) for row in alerts["stuck_publications"]} == {
        (dispatching["id"], "DISPATCHING"), (pending["id"], "PENDING")
    }
    with repo_db.tenant_transaction(conn, tenant_b):
        isolated = ops_repository.operational_alerts(conn, tenant_id=tenant_b, now="2026-01-01T00:00:00Z", stale_before="2099-01-01T00:00:00Z")
    assert not isolated["overdue_reconciliation"] and not isolated["expired_execution_lease"]
    assert not isolated["authorization_blockers"] and not isolated["inbox_exceptions"] and not isolated["stuck_publications"]
    assert isolated["outbox_backlog"][0]["count"] == 0
