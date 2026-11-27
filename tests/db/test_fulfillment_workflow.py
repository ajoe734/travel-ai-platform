"""backlog ENG-05 acceptance: 第一條接單耐久流程.

Case -> Work -> query availability -> quote -> consent -> mock reservation ->
reconciliation -> completion evidence, plus the negative acceptance cases:
normal completion; restart continuation; duplicate/out-of-order webhook does
not regress state; cancel-vs-dispatch race has a clear outcome; UNKNOWN is
never blindly resent; a reconciliation deadline produces a pending
Escalation (never an automatic FAILED); completion requires real evidence;
notification failure is separate from booking failure.

Requires a real Postgres instance; see tests/db/conftest.py and
db/README.md "本機無法執行的部分" for why this cannot run in this sandbox
VM (no psycopg, no local Postgres) -- the hosted `db-repository-tests` CI
job (.github/workflows/repository-validation.yml) is what actually executes
this file.
"""
from __future__ import annotations

import threading
import uuid

import pytest

from connectors.mocks.experience_reservation import ExperienceReservationMock
from db.repository import db as repo_db
from db.repository import execution_repository, work_repository
from services.fulfillment.errors import TaskAlreadyDispatchedError, WorkPhaseMismatchError
from services.fulfillment.service import FulfillmentService

SESSION_ID = "fulfillment-test-session"
SESSION_CAPACITY = 10


@pytest.fixture()
def connector():
    return ExperienceReservationMock({SESSION_ID: SESSION_CAPACITY})


@pytest.fixture()
def fulfillment(connector, app_database_url):
    return FulfillmentService(
        connector,
        worker_connection_factory=lambda: repo_db.connect(app_database_url),
    )


def _accept_and_approve(fulfillment, conn, tenant_id, case_id, *, party_size=2, session_id=SESSION_ID, now="2026-12-01T00:00:00+00:00"):
    with repo_db.tenant_transaction(conn, tenant_id):
        accepted = fulfillment.accept_order(
            conn, tenant_id=tenant_id, case_id=case_id, session_id=session_id, party_size=party_size,
            unit_price_minor_units="100000", currency="TWD", currency_scale_ref="iso4217-minor-unit-2",
            principal={"actor_kind": "CUSTOMER", "actor_id": str(uuid.uuid4())},
            decision_expires_at="2026-12-01T01:00:00+00:00", now=now,
        )
    with repo_db.tenant_transaction(conn, tenant_id):
        approved = fulfillment.approve_consent(
            conn, tenant_id=tenant_id, work_id=accepted["work"]["id"], decision_id=accepted["decision_id"],
            expected_revision=accepted["decision_revision"], selected_option_id="approve",
            approved_by={"actor_kind": "CUSTOMER", "actor_id": str(uuid.uuid4())},
            verified_actor_ref="confirmation-flow-probe", scope_manifest=[
                {"item_id": "booking", "operation": "booking.create"}
            ],
            approved_at="2026-12-01T00:05:00+00:00", now="2026-12-01T00:05:00+00:00",
        )
    return accepted, approved


def test_normal_completion_has_real_completion_evidence(fulfillment, conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    accepted, approved = _accept_and_approve(fulfillment, conn, tenant_a, case_id)
    task_id = approved["task"]["id"]

    with repo_db.tenant_transaction(conn, tenant_a):
        result = fulfillment.dispatch_booking(
            conn, tenant_id=tenant_a, task_id=task_id, holder="worker-1", now="2026-12-01T00:10:00+00:00",
        )
    assert result["outcome"] == "SUCCEEDED"
    assert result["work"]["status"] == "COMPLETED"
    assert result["task"]["status"] == "DONE"

    with repo_db.tenant_transaction(conn, tenant_a):
        work = work_repository.get_work(conn, tenant_id=tenant_a, work_id=accepted["work"]["id"])
        evidence_rows = conn.execute(
            "SELECT id FROM completion_evidence WHERE tenant_id = %s AND work_id = %s",
            (tenant_a, accepted["work"]["id"]),
        ).fetchall()
        order = conn.execute(
            "SELECT supplier_booking_status, status FROM order_record WHERE tenant_id = %s AND id = %s",
            (tenant_a, accepted["order"]["id"]),
        ).fetchone()
    assert work["status"] == "COMPLETED"
    assert work["completion_record"] is not None
    # backlog ENG-05 acceptance: 未取得外部證據不得顯示完成 -- COMPLETED is never
    # reached without a real CompletionEvidence row backing it.
    assert len(evidence_rows) >= 1
    assert order == ("CONFIRMED", "CONFIRMED")


def test_declining_the_quote_cancels_the_work_without_creating_a_task(fulfillment, conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    with repo_db.tenant_transaction(conn, tenant_a):
        accepted = fulfillment.accept_order(
            conn, tenant_id=tenant_a, case_id=case_id, session_id=SESSION_ID, party_size=1,
            unit_price_minor_units="50000", currency="TWD", currency_scale_ref="iso4217-minor-unit-2",
            principal={"actor_kind": "CUSTOMER", "actor_id": str(uuid.uuid4())},
            decision_expires_at="2026-12-01T01:00:00+00:00", now="2026-12-01T00:00:00+00:00",
        )
    with repo_db.tenant_transaction(conn, tenant_a):
        declined = fulfillment.approve_consent(
            conn, tenant_id=tenant_a, work_id=accepted["work"]["id"], decision_id=accepted["decision_id"],
            expected_revision=accepted["decision_revision"], selected_option_id="decline",
            approved_by={"actor_kind": "CUSTOMER", "actor_id": str(uuid.uuid4())},
            verified_actor_ref="confirmation-flow-probe", scope_manifest=[],
            approved_at="2026-12-01T00:05:00+00:00", now="2026-12-01T00:05:00+00:00",
        )
    assert declined["work"]["status"] == "CANCELLED"
    assert declined["task"] is None


def test_restart_continuation_reconciles_an_unknown_task_via_lookup_not_a_new_create(
    fulfillment, conn, app_database_url, tenant_a, case_factory,
):
    case_id = case_factory(tenant_a)
    accepted, approved = _accept_and_approve(fulfillment, conn, tenant_a, case_id)
    task_id = approved["task"]["id"]

    with repo_db.tenant_transaction(conn, tenant_a):
        timed_out = fulfillment.dispatch_booking(
            conn, tenant_id=tenant_a, task_id=task_id, holder="worker-1", now="2026-12-01T00:10:00+00:00",
            simulate_timeout=True,
        )
    assert timed_out["outcome"] == "UNKNOWN"
    assert timed_out["task"]["status"] == "UNKNOWN"
    assert timed_out["work"]["status"] == "WAITING_EXTERNAL"

    # "Restart": a brand-new connection/service, carrying no in-process
    # state from the dispatch above, continues purely from what is durable.
    fresh_connection = repo_db.connect(app_database_url)
    try:
        fresh_service = FulfillmentService(
            fulfillment._connector,
            worker_connection_factory=lambda: repo_db.connect(app_database_url),
        )
        with repo_db.tenant_transaction(fresh_connection, tenant_a):
            reconciled = fresh_service.reconcile_booking(
                fresh_connection, tenant_id=tenant_a, task_id=task_id, holder="worker-2",
                now="2026-12-01T00:11:00+00:00",
            )
    finally:
        fresh_connection.close()

    assert reconciled["outcome"] == "SUCCEEDED"
    assert reconciled["work"]["status"] == "COMPLETED"
    # Only one booking was ever created for this business_key: the mock's
    # own ledger has created_count == 1 (see connectors/idempotency.py), and
    # lookup_booking (a declared READ capability) is what found it, not a
    # second create_booking call. The first dispatch's create_booking call
    # is the only WRITE this test ever makes against the connector.
    assert len(fulfillment._connector._store._records) == 1


def test_crash_after_external_success_recovers_executing_intent_via_lookup(
    fulfillment, conn, app_database_url, tenant_a, case_factory,
):
    """F2 regression: TX1 must survive a process death after the connector
    accepted the stable business key but before the outcome transaction ran.
    Restart recovery is lookup-only; it must not create a second booking.
    """
    case_id = case_factory(tenant_a)
    accepted, approved = _accept_and_approve(fulfillment, conn, tenant_a, case_id)
    task_id = approved["task"]["id"]

    with pytest.raises(RuntimeError, match="simulated process crash"):
        with repo_db.tenant_transaction(conn, tenant_a):
            fulfillment.dispatch_booking(
                conn, tenant_id=tenant_a, task_id=task_id, holder="worker-before-crash",
                now="2026-12-01T00:10:00+00:00", simulate_crash_after_external=True,
            )

    with repo_db.tenant_transaction(conn, tenant_a):
        stranded = execution_repository.get_execution_task(conn, tenant_id=tenant_a, task_id=task_id)
        dispatch_attempts = conn.execute(
            "SELECT count(*) FROM execution_attempt WHERE tenant_id = %s AND task_id = %s AND attempt_kind = 'DISPATCH'",
            (tenant_a, task_id),
        ).fetchone()[0]
    assert stranded["status"] == "EXECUTING"
    assert dispatch_attempts == 1

    restarted = FulfillmentService(
        fulfillment._connector,
        worker_connection_factory=lambda: repo_db.connect(app_database_url),
    )
    with repo_db.tenant_transaction(conn, tenant_a):
        recovered = restarted.reconcile_booking(
            conn, tenant_id=tenant_a, task_id=task_id, holder="worker-after-crash",
            # The first holder's lease is deliberately allowed to expire.
            now="2026-12-01T00:10:31+00:00",
        )
    assert recovered["outcome"] == "SUCCEEDED"
    assert recovered["task"]["status"] == "DONE"
    assert recovered["work"]["status"] == "COMPLETED"
    assert len(fulfillment._connector._store._records) == 1


def test_duplicate_and_stale_webhook_never_regress_an_already_terminal_task(
    fulfillment, conn, tenant_a, case_factory,
):
    case_id = case_factory(tenant_a)
    accepted, approved = _accept_and_approve(fulfillment, conn, tenant_a, case_id)
    task_id = approved["task"]["id"]
    with repo_db.tenant_transaction(conn, tenant_a):
        fulfillment.dispatch_booking(
            conn, tenant_id=tenant_a, task_id=task_id, holder="worker-1", now="2026-12-01T00:10:00+00:00",
        )
    # Task is already DONE / Work already COMPLETED at this point.

    with repo_db.tenant_transaction(conn, tenant_a):
        stale = fulfillment.process_booking_webhook(
            conn, tenant_id=tenant_a, task_id=task_id, event_id=str(uuid.uuid4()),
            source_event_id="late-event-1", producer="experience-mock", outcome="REJECTED",
            external_ref="irrelevant", now="2026-12-01T00:20:00+00:00",
        )
    assert stale["applied"] is False
    assert stale["task_status"] == "DONE"

    with repo_db.tenant_transaction(conn, tenant_a):
        work = work_repository.get_work(conn, tenant_id=tenant_a, work_id=accepted["work"]["id"])
        task = execution_repository.get_execution_task(conn, tenant_id=tenant_a, task_id=task_id)
    assert work["status"] == "COMPLETED"
    assert task["status"] == "DONE"

    # A genuinely duplicate event (same source_event_id + same hash) replays
    # as a no-op ACK rather than being reprocessed a second time.
    with repo_db.tenant_transaction(conn, tenant_a):
        duplicate_1 = fulfillment.process_booking_webhook(
            conn, tenant_id=tenant_a, task_id=task_id, event_id=str(uuid.uuid4()),
            source_event_id="dup-event-1", producer="experience-mock", outcome="REJECTED",
            external_ref="irrelevant", now="2026-12-01T00:21:00+00:00",
        )
    with repo_db.tenant_transaction(conn, tenant_a):
        duplicate_2 = fulfillment.process_booking_webhook(
            conn, tenant_id=tenant_a, task_id=task_id, event_id=str(uuid.uuid4()),
            source_event_id="dup-event-1", producer="experience-mock", outcome="REJECTED",
            external_ref="irrelevant", now="2026-12-01T00:22:00+00:00",
        )
    assert duplicate_1["applied"] is False  # task already DONE, never applied in the first place
    assert duplicate_2["inbox_outcome"] == "duplicate"


def test_cancel_vs_dispatch_race_has_exactly_one_deterministic_winner(
    fulfillment, conn, app_database_url, tenant_a, case_factory,
):
    case_id = case_factory(tenant_a)
    accepted, approved = _accept_and_approve(fulfillment, conn, tenant_a, case_id)
    task_id = approved["task"]["id"]
    work_id = accepted["work"]["id"]

    barrier = threading.Barrier(2)
    results = [None, None]

    def _dispatch():
        connection = repo_db.connect(app_database_url)
        try:
            service = FulfillmentService(
                ExperienceReservationMock({SESSION_ID: SESSION_CAPACITY}),
                worker_connection_factory=lambda: repo_db.connect(app_database_url),
            )
            barrier.wait()
            with repo_db.tenant_transaction(connection, tenant_a):
                outcome = service.dispatch_booking(
                    connection, tenant_id=tenant_a, task_id=task_id, holder="racer-dispatch",
                    now="2026-12-01T00:10:00+00:00",
                )
            results[0] = ("dispatch", outcome["outcome"])
        finally:
            connection.close()

    def _cancel():
        connection = repo_db.connect(app_database_url)
        try:
            service = FulfillmentService(
                ExperienceReservationMock({SESSION_ID: SESSION_CAPACITY}),
                worker_connection_factory=lambda: repo_db.connect(app_database_url),
            )
            barrier.wait()
            try:
                with repo_db.tenant_transaction(connection, tenant_a):
                    outcome = service.cancel_booking(
                        connection, tenant_id=tenant_a, work_id=work_id, task_id=task_id,
                        reason="customer requested cancellation", now="2026-12-01T00:10:00+00:00",
                    )
                results[1] = ("cancel", "CANCELLED")
            except TaskAlreadyDispatchedError:
                results[1] = ("cancel", "TOO_LATE")
        finally:
            connection.close()

    threads = [threading.Thread(target=_dispatch), threading.Thread(target=_cancel)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    with repo_db.tenant_transaction(conn, tenant_a):
        task = execution_repository.get_execution_task(conn, tenant_id=tenant_a, task_id=task_id)
        work = work_repository.get_work(conn, tenant_id=tenant_a, work_id=work_id)

    dispatch_outcome = results[0][1]
    cancel_outcome = results[1][1]
    if cancel_outcome == "CANCELLED":
        # cancel won: the task must never have been sent externally.
        assert dispatch_outcome == "CANCELLED_BEFORE_DISPATCH"
        assert task["status"] == "CANCELLED"
        assert work["status"] == "CANCELLED"
    else:
        # dispatch won: cancellation is rejected, and the already-sent
        # action proceeds to its normal terminal outcome.
        assert cancel_outcome == "TOO_LATE"
        assert dispatch_outcome in ("SUCCEEDED", "FAILED", "UNKNOWN")
        assert task["status"] != "NEW"


def test_overdue_unknown_task_gets_one_idempotent_escalation_not_an_automatic_failure(
    fulfillment, conn, tenant_a, case_factory,
):
    case_id = case_factory(tenant_a)
    accepted, approved = _accept_and_approve(fulfillment, conn, tenant_a, case_id)
    task_id = approved["task"]["id"]
    with repo_db.tenant_transaction(conn, tenant_a):
        fulfillment.dispatch_booking(
            conn, tenant_id=tenant_a, task_id=task_id, holder="worker-1", now="2026-12-01T00:10:00+00:00",
            simulate_timeout=True,
        )

    owner = {"actor_kind": "EMPLOYEE", "actor_id": str(uuid.uuid4())}
    far_future = "2026-12-02T00:00:00+00:00"  # well past the task's booking_deadline_seconds=3600 default
    with repo_db.tenant_transaction(conn, tenant_a):
        created_first = fulfillment.check_deadlines(conn, tenant_id=tenant_a, now=far_future, owner=owner)
    with repo_db.tenant_transaction(conn, tenant_a):
        created_second = fulfillment.check_deadlines(conn, tenant_id=tenant_a, now=far_future, owner=owner)

    assert len(created_first) == 1
    assert created_first[0]["task_id"] == task_id
    assert created_second == []  # idempotent: no duplicate escalation on a second sweep

    with repo_db.tenant_transaction(conn, tenant_a):
        task = execution_repository.get_execution_task(conn, tenant_id=tenant_a, task_id=task_id)
        work = work_repository.get_work(conn, tenant_id=tenant_a, work_id=accepted["work"]["id"])
    # backlog ENG-05 acceptance: 超過查核期限產生待處理工作 -- not an automatic failure.
    assert task["status"] == "UNKNOWN"
    assert work["status"] == "WAITING_EXTERNAL"


def test_notification_failure_is_separate_from_booking_success(fulfillment, conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    accepted, approved = _accept_and_approve(fulfillment, conn, tenant_a, case_id)
    task_id = approved["task"]["id"]
    with repo_db.tenant_transaction(conn, tenant_a):
        fulfillment.dispatch_booking(
            conn, tenant_id=tenant_a, task_id=task_id, holder="worker-1", now="2026-12-01T00:10:00+00:00",
        )

    with repo_db.tenant_transaction(conn, tenant_a):
        notification_task = fulfillment.send_notification(
            conn, tenant_id=tenant_a, work_id=accepted["work"]["id"], order_id=accepted["order"]["id"],
            channel="SMS", now="2026-12-01T00:15:00+00:00", notifier=lambda: False,
        )
    assert notification_task["status"] == "FAILED"

    with repo_db.tenant_transaction(conn, tenant_a):
        work = work_repository.get_work(conn, tenant_id=tenant_a, work_id=accepted["work"]["id"])
        escalations = conn.execute(
            "SELECT status FROM escalation WHERE tenant_id = %s AND task_id = %s",
            (tenant_a, notification_task["id"]),
        ).fetchall()
    # backlog ENG-05 / SD-W-09: 通知失敗與預訂失敗分開 -- the booking's own
    # COMPLETED status and evidence are untouched by the notification task.
    assert work["status"] == "COMPLETED"
    assert len(escalations) == 1
    assert escalations[0][0] == "OPEN"


def test_dispatch_booking_rejects_a_task_that_is_not_new(fulfillment, conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    accepted, approved = _accept_and_approve(fulfillment, conn, tenant_a, case_id)
    task_id = approved["task"]["id"]
    with repo_db.tenant_transaction(conn, tenant_a):
        fulfillment.dispatch_booking(
            conn, tenant_id=tenant_a, task_id=task_id, holder="worker-1", now="2026-12-01T00:10:00+00:00",
        )
    with pytest.raises(WorkPhaseMismatchError):
        with repo_db.tenant_transaction(conn, tenant_a):
            fulfillment.dispatch_booking(
                conn, tenant_id=tenant_a, task_id=task_id, holder="worker-1", now="2026-12-01T00:11:00+00:00",
            )
