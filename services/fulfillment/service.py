"""ENG-05 第一條接單耐久流程: Case -> Work -> quote -> consent -> mock
reservation -> reconciliation -> completion evidence.

Implements backlog.md#eng-05 on top of already-durable persistence.  Command
methods use the caller's tenant-scoped transaction; dispatch/reconciliation
Activities instead use a configured fresh worker connection for each short
transaction, so connector I/O never runs inside the caller transaction.
``FulfillmentService`` itself holds no process-local workflow state: a fresh
instance pointed at the same database and given the same ``task_id``/``work_id``
continues from the durable task/attempt rows (backlog ENG-05 acceptance:
"Worker 重啟後可延續").

Scope boundary (disclosed per AI_COLLABORATION_GUIDE.md §0.7): consent here
uses db/repository/approval_repository.py's DecisionRequest/ApprovalRecord
tables directly (real SQL, real revision guards) as the durable consent
gate. The full ExecutionAuthorization/AuthorizationUse manifest-consumption
chain services/authorization/service.py implements against an in-memory
repository (ENG-03) is not wired to this engine's ExecutionTask rows in this
candidate -- ExecutionTask.authorization_use_id stays NULL throughout (the
column and its CHECK constraint both already allow this). Wiring ENG-03's
service onto db/repository's persisted authorization tables is its own
follow-on, not duplicated here.

Attempt/lease bookkeeping, business_key dedupe and Work status transitions
are all real: this is the actual durable executor
services/workbench/service.py's docstring named as ENG-05 scope (lease/fence,
multi-worker contention, outbox-free direct DB transactions in place of its
collapsed NEW->EXECUTING placeholder tick).
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Callable, Iterator

from connectors.base import Connector
from connectors.idempotency import request_hash as _hash_snapshot
from connectors.types import Failed, OperationResult, Succeeded

from db.repository import approval_repository, db as repository_db, execution_repository, fulfillment_repository, outbox_inbox_repository, work_repository
from db.repository.errors import VersionConflict
from services.authorization import canonical_json
from services.authorization.temporal import is_at_or_before, parse_timestamp

from .errors import (
    DecisionOptionUnknownError,
    TaskAlreadyDispatchedError,
    TaskLeaseContendedError,
    TaskNotFoundError,
    WorkPhaseMismatchError,
)

VERIFIER_VERSION = "fulfillment-booking-verifier-v1"
SYSTEM_ACTOR = {"actor_kind": "SYSTEM", "actor_id": "00000000-0000-4000-8000-000000000099"}


def _new_id() -> str:
    return str(uuid.uuid4())


def _add_seconds(timestamp: str, seconds: float) -> str:
    return (parse_timestamp(timestamp) + timedelta(seconds=seconds)).isoformat()


class FulfillmentService:
    def __init__(self, connector: Connector, *, worker_connection_factory: Callable[[], Any] | None = None) -> None:
        self._connector = connector
        self._worker_connection_factory = worker_connection_factory

    @contextmanager
    def _worker_transaction(self, tenant_id: str) -> Iterator[Any]:
        """A worker-owned short transaction, never the caller's request TX."""
        if self._worker_connection_factory is None:
            raise RuntimeError("worker_connection_factory is required for dispatch/reconcile durability")
        worker_conn = self._worker_connection_factory()
        try:
            with repository_db.tenant_transaction(worker_conn, tenant_id):
                yield worker_conn
        finally:
            worker_conn.close()

    @staticmethod
    def _task_held_by_fence(conn, *, tenant_id: str, task_id: str, fence_token: int) -> dict[str, Any]:
        task = execution_repository.get_execution_task(conn, tenant_id=tenant_id, task_id=task_id)
        if task is None or task["lease_fence_token"] != fence_token or task["status"] not in ("EXECUTING", "WAITING", "UNKNOWN"):
            raise TaskLeaseContendedError(f"execution_task {task_id} is no longer held by fence {fence_token}")
        return task

    # -- 1. Accept the order: query supply, form a quote, ask for consent ----

    def accept_order(
        self,
        conn,
        *,
        tenant_id: str,
        case_id: str,
        session_id: str,
        party_size: int,
        unit_price_minor_units: str,
        currency: str,
        currency_scale_ref: str,
        principal: dict[str, Any],
        decision_expires_at: str,
        now: str,
    ) -> dict[str, Any]:
        """SD §3 DRAFT->RUNNING->WAITING_DECISION: the caller (an existing
        Case) already supplied everything a Work needs to start RUNNING, so
        this call creates it directly RUNNING and walks it straight to
        WAITING_DECISION once the quote exists -- there is no WAITING_INPUT
        phase for this flow (unlike ENG-06's service-revision proposal,
        nothing here is missing at acceptance time)."""
        availability = self._connector.query_availability(session_id)

        work_id = _new_id()
        work = work_repository.create_work(
            conn,
            tenant_id=tenant_id,
            work_id=work_id,
            case_id=case_id,
            work_type="BOOKING",
            objective=f"為案件 {case_id} 完成場次 {session_id} 的預訂（{party_size} 人）",
            completion_contract_version="booking-completion-v1",
            completion_conditions=[
                {
                    "condition_id": "booking_confirmed",
                    "description": "供應商預訂已確認並有正式外部證據",
                    "satisfied": False,
                }
            ],
            principal=principal,
            status="RUNNING",
        )
        work_repository.append_work_event(
            conn, tenant_id=tenant_id, work_id=work_id, event_type="work.accepted", schema_version="1.0",
            payload={"case_id": case_id, "session_id": session_id, "party_size": party_size,
                     "availability_at_quote_time": availability},
            occurred_at=now,
        )

        quote_id = _new_id()
        quote_content = {
            "session_id": session_id,
            "party_size": party_size,
            "unit_price_minor_units": unit_price_minor_units,
            "currency": currency,
        }
        total_amount_minor_units = str(int(unit_price_minor_units) * party_size)
        quote = fulfillment_repository.create_quote_snapshot(
            conn, tenant_id=tenant_id, quote_id=quote_id, case_id=case_id, content=quote_content,
            content_hash=_hash_snapshot(quote_content), total_amount_minor_units=total_amount_minor_units,
            total_currency=currency, total_currency_scale_ref=currency_scale_ref,
        )
        work_repository.create_work_context(
            conn, tenant_id=tenant_id, context_id=_new_id(), work_id=work_id,
            ref_kind="QUOTE", target_id=quote_id, purpose="predbooking quote this Work fulfils",
        )

        order_id = _new_id()
        order = fulfillment_repository.create_order(
            conn, tenant_id=tenant_id, order_id=order_id, case_id=case_id, quote_id=quote_id,
            total_amount_minor_units=total_amount_minor_units, total_currency=currency,
            total_currency_scale_ref=currency_scale_ref,
        )
        work_repository.create_work_context(
            conn, tenant_id=tenant_id, context_id=_new_id(), work_id=work_id,
            ref_kind="ORDER", target_id=order_id, purpose="order this Work's booking task will confirm",
        )

        decision_id = _new_id()
        display_payload = {
            "schema_version": "1.0",
            "canonicalization_version": "travel-canonical-json-v1",
            "tenant_id": tenant_id,
            "purpose": "BOOKING_QUOTE_CONSENT",
            "target_type": "QUOTE",
            "target_id": quote_id,
            "target_revision": 1,
            "work_id": work_id,
            "operation": "booking.create",
            "service_or_policy_version": "booking-v1",
            "expires_at": decision_expires_at,
            "data_purpose": "fulfil the customer's booking request",
            "manifest_items": ["booking"],
            "customer_impact": f"預訂場次 {session_id}，{party_size} 人，金額 {total_amount_minor_units} {currency}",
            "required_consent_refs": [],
            "session_id": session_id,
            "party_size": party_size,
            "order_id": order_id,
            "quote_id": quote_id,
            "total_amount_minor_units": total_amount_minor_units,
            "currency": currency,
        }
        payload_hash = canonical_json.payload_hash(display_payload)
        approval_repository.create_decision_request(
            conn, tenant_id=tenant_id, decision_id=decision_id, revision=1, work_id=work_id,
            decision_type="BOOKING_QUOTE_APPROVAL",
            options=[
                {"option_id": "approve", "description": "核准預訂並向供應商送出"},
                {"option_id": "decline", "description": "不核准，取消此次預訂"},
            ],
            payload_hash=payload_hash, target_revision=1, expires_at=decision_expires_at,
            requested_role="CUSTOMER", display_payload=display_payload,
        )

        work = work_repository.update_work_status(
            conn, tenant_id=tenant_id, work_id=work_id, expected_revision=work["revision"],
            new_status="WAITING_DECISION", waiting_decision={"decision_ref": {"tenant_id": tenant_id, "id": decision_id}},
        )
        work_repository.append_work_event(
            conn, tenant_id=tenant_id, work_id=work_id, event_type="work.waiting", schema_version="1.0",
            payload={"reason": "WAITING_DECISION", "decision_id": decision_id}, occurred_at=now,
        )
        return {
            "work": work, "quote": quote, "order": order,
            "decision_id": decision_id, "decision_revision": 1, "payload_hash": payload_hash,
        }

    # -- 2. Resolve consent: approve creates the booking task, decline cancels --

    def approve_consent(
        self,
        conn,
        *,
        tenant_id: str,
        work_id: str,
        decision_id: str,
        expected_revision: int,
        selected_option_id: str,
        approved_by: dict[str, Any],
        verified_actor_ref: str,
        scope_manifest: list[dict[str, Any]],
        approved_at: str,
        now: str,
        booking_deadline_seconds: int = 3600,
    ) -> dict[str, Any]:
        work = work_repository.get_work(conn, tenant_id=tenant_id, work_id=work_id)
        if work is None:
            raise TaskNotFoundError(f"no work {work_id}")
        if work["status"] != "WAITING_DECISION":
            raise WorkPhaseMismatchError(f"work {work_id} is {work['status']}, not WAITING_DECISION")

        decision = approval_repository.get_decision_request(conn, tenant_id=tenant_id, decision_id=decision_id)
        if decision is None:
            raise TaskNotFoundError(f"no decision {decision_id}")
        # psycopg returns UUID columns as uuid.UUID while the public command
        # boundary accepts the stable string ID returned by accept_order.
        # Compare the canonical wire representation on both sides: this keeps
        # the Work binding check in place instead of treating a driver type
        # difference as a cross-Work decision.
        if str(decision["work_id"]) != str(work_id):
            raise WorkPhaseMismatchError("decision does not belong to this Work")
        if decision["status"] != "PENDING" or decision["revision"] != expected_revision:
            raise WorkPhaseMismatchError("decision is no longer the requested pending revision")
        if is_at_or_before(str(decision["expires_at"]), approved_at):
            raise WorkPhaseMismatchError("decision has expired")
        if approved_by.get("actor_kind") != decision["requested_role"]:
            raise WorkPhaseMismatchError("approval actor does not hold the requested role")
        option_ids = {option["option_id"] for option in decision["options"]}
        if selected_option_id not in option_ids:
            raise DecisionOptionUnknownError(f"{selected_option_id!r} is not one of {sorted(option_ids)}")

        if selected_option_id == "approve":
            expected_manifest = {"booking": "booking.create"}
            if len(scope_manifest) != 1 or {item.get("item_id"): item.get("operation") for item in scope_manifest} != expected_manifest:
                raise WorkPhaseMismatchError("approval scope_manifest does not exactly bind booking.create")
            approval_id = _new_id()
            approval_repository.approve_decision(
                conn, tenant_id=tenant_id, decision_id=decision_id, reviewed_revision=expected_revision,
                selected_option_id=selected_option_id, approval_id=approval_id, approved_by=approved_by,
                verified_actor_ref=verified_actor_ref, approved_payload=decision["display_payload"],
                payload_hash=decision["payload_hash"], scope_manifest=scope_manifest, approved_at=approved_at,
                expires_at=str(decision["expires_at"]),
            )
            payload = decision["display_payload"]
            task_id = _new_id()
            business_key = f"booking.create:{payload['quote_id']}"
            request_snapshot = {
                "session_id": payload["session_id"],
                "party_size": payload["party_size"],
                "order_id": payload["order_id"],
                "quote_id": payload["quote_id"],
                "approval_id": approval_id,
                "decision_id": decision_id,
            }
            task = execution_repository.create_execution_task(
                conn, tenant_id=tenant_id, task_id=task_id, work_id=work_id, kind="ACTION",
                operation="booking.create", business_key=business_key, request_hash=_hash_snapshot(request_snapshot),
                request_snapshot=request_snapshot, postcondition_version="booking-v1",
                postcondition={"booking_confirmed_with_evidence": True},
                deadline=_add_seconds(now, booking_deadline_seconds),
            )
            work = work_repository.update_work_status(
                conn, tenant_id=tenant_id, work_id=work_id, expected_revision=work["revision"], new_status="RUNNING",
            )
            work_repository.append_work_event(
                conn, tenant_id=tenant_id, work_id=work_id, event_type="execution.task_created", schema_version="1.0",
                payload={"task_id": task_id, "operation": "booking.create", "business_key": business_key},
                occurred_at=now,
            )
            return {"work": work, "task": task, "approval_id": approval_id}

        approval_repository.reject_decision(
            conn, tenant_id=tenant_id, decision_id=decision_id, reviewed_revision=expected_revision,
            selected_option_id=selected_option_id,
        )
        work = work_repository.update_work_status(
            conn, tenant_id=tenant_id, work_id=work_id, expected_revision=work["revision"], new_status="CANCELLED",
            cancellation={"reason": "customer did not approve the booking quote"},
        )
        work_repository.append_work_event(
            conn, tenant_id=tenant_id, work_id=work_id, event_type="work.cancelled", schema_version="1.0",
            payload={"decision_id": decision_id, "selected_option_id": selected_option_id}, occurred_at=now,
        )
        return {"work": work, "task": None, "approval_id": None}

    # -- 3. Dispatch the booking (first attempt only; NEW -> ...) -------------

    def dispatch_booking(
        self,
        _conn,
        *,
        tenant_id: str,
        task_id: str,
        holder: str,
        now: str,
        lease_seconds: float = 30,
        simulate_timeout: bool = False,
        simulate_crash_after_external: bool = False,
        reconcile_after_seconds: float = 60,
    ) -> dict[str, Any]:
        """Commit intent, call the connector outside a transaction, then
        commit the observation.  An external success followed by a process
        death leaves EXECUTING + its stable business key for reconciliation.
        """
        # TX1: cancellation and dispatch race on this one durable predicate.
        with self._worker_transaction(tenant_id) as worker_conn:
            task = execution_repository.get_execution_task(worker_conn, tenant_id=tenant_id, task_id=task_id)
            if task is None:
                raise TaskNotFoundError(f"no execution_task {task_id}")
            if task["status"] == "CANCELLED":
                # Cancellation won the shared NEW predicate before this
                # worker recorded a dispatch intent.  This is an expected
                # race result, not a phase error, and guarantees no attempt
                # or connector write is appended after cancellation.
                return {"task": task, "outcome": "CANCELLED_BEFORE_DISPATCH"}
            if task["status"] != "NEW":
                raise WorkPhaseMismatchError(f"execution_task {task_id} is {task['status']}, not NEW")
            self._assert_dispatch_approval(worker_conn, tenant_id=tenant_id, task=task, now=now)
            task = execution_repository.claim_new_task_for_dispatch(
                worker_conn, tenant_id=tenant_id, task_id=task_id, holder=holder, now=now,
                lease_until=_add_seconds(now, lease_seconds),
            )
            if task is None:
                current = execution_repository.get_execution_task(worker_conn, tenant_id=tenant_id, task_id=task_id)
                if current is not None and current["status"] == "CANCELLED":
                    return {"task": current, "outcome": "CANCELLED_BEFORE_DISPATCH"}
                raise TaskLeaseContendedError(f"execution_task {task_id} was claimed or changed by another worker")
            fence = task["lease_fence_token"]
            attempt_id = _new_id()
            execution_repository.record_attempt(
                worker_conn, tenant_id=tenant_id, attempt_id=attempt_id, task_id=task_id,
                attempt_no=execution_repository.next_attempt_no(worker_conn, tenant_id=tenant_id, task_id=task_id),
                attempt_kind="DISPATCH", fence_token=fence, request_hash=task["request_hash"], started_at=now,
            )
            snapshot = task["request_snapshot"]

        # External I/O intentionally has no open database transaction.
        if simulate_timeout:
            # The external side effect genuinely happens -- the mock's own
            # dispatch ledger really records this booking -- but this worker
            # never observes the response, so the outcome must stay UNKNOWN
            # rather than being inferred either way (SD-C-01).
            self._connector.create_booking(tenant_id, task["business_key"], snapshot["session_id"], snapshot["party_size"], now)
            with self._worker_transaction(tenant_id) as worker_conn:
                task = self._task_held_by_fence(worker_conn, tenant_id=tenant_id, task_id=task_id, fence_token=fence)
                execution_repository.append_observation(worker_conn, tenant_id=tenant_id, attempt_id=attempt_id, sequence=1, observed_at=now, transport_result="TIMEOUT", outcome="UNKNOWN")
                task, work = self._mark_unknown(worker_conn, tenant_id=tenant_id, work_id=task["work_id"], task=task, now=now, fence_token=fence, next_check_at=_add_seconds(now, reconcile_after_seconds))
                execution_repository.release_lease(worker_conn, tenant_id=tenant_id, task_id=task_id, fence_token=fence)
                return {"task": task, "work": work, "outcome": "UNKNOWN"}

        result = self._connector.create_booking(tenant_id, task["business_key"], snapshot["session_id"], snapshot["party_size"], now)
        if simulate_crash_after_external:
            raise RuntimeError("simulated process crash after connector success and before TX2")
        # TX2: persist result/evidence after the external side effect.
        with self._worker_transaction(tenant_id) as worker_conn:
            task = self._task_held_by_fence(worker_conn, tenant_id=tenant_id, task_id=task_id, fence_token=fence)
            outcome = self._apply_dispatch_result(worker_conn, tenant_id=tenant_id, work_id=task["work_id"], task=task, attempt_id=attempt_id, result=result, now=now, fence_token=fence)
            execution_repository.release_lease(worker_conn, tenant_id=tenant_id, task_id=task_id, fence_token=fence)
            return outcome

    # -- 4. Reconcile a WAITING/UNKNOWN task via a read-only lookup -----------

    def reconcile_booking(
        self, _conn, *, tenant_id: str, task_id: str, holder: str, now: str, lease_seconds: float = 30,
    ) -> dict[str, Any]:
        # TX1 records a read-only reconciliation attempt. EXECUTING is
        # included for the crash-after-external-success recovery path.
        with self._worker_transaction(tenant_id) as worker_conn:
            task = execution_repository.get_execution_task(worker_conn, tenant_id=tenant_id, task_id=task_id)
            if task is None:
                raise TaskNotFoundError(f"no execution_task {task_id}")
            if task["status"] in ("DONE", "FAILED", "CANCELLED"):
                return {"task": task, "outcome": "ALREADY_TERMINAL_NO_OP"}
            if task["status"] not in ("EXECUTING", "WAITING", "UNKNOWN"):
                raise WorkPhaseMismatchError(f"execution_task {task_id} is {task['status']}, not EXECUTING/WAITING/UNKNOWN")
            lease = execution_repository.acquire_lease(
                worker_conn, tenant_id=tenant_id, task_id=task_id, holder=holder, now=now,
                lease_until=_add_seconds(now, lease_seconds), allowed_statuses=("EXECUTING", "WAITING", "UNKNOWN"),
            )
            if lease is None:
                raise TaskLeaseContendedError(f"execution_task {task_id} lease is held by another worker")
            task = lease
            fence = task["lease_fence_token"]
            attempt_id = _new_id()
            execution_repository.record_attempt(worker_conn, tenant_id=tenant_id, attempt_id=attempt_id, task_id=task_id, attempt_no=execution_repository.next_attempt_no(worker_conn, tenant_id=tenant_id, task_id=task_id), attempt_kind="RECONCILE", fence_token=fence, request_hash=task["request_hash"], started_at=now)

        try:
            result: OperationResult = self._connector.lookup_booking(tenant_id, task["business_key"])
        except KeyError:
            # SD-C-03: a first not-found read is not a failure; stay UNKNOWN
            # and schedule the next read-only reconciliation tick.
            with self._worker_transaction(tenant_id) as worker_conn:
                task = self._task_held_by_fence(worker_conn, tenant_id=tenant_id, task_id=task_id, fence_token=fence)
                execution_repository.append_observation(worker_conn, tenant_id=tenant_id, attempt_id=attempt_id, sequence=1, observed_at=now, transport_result="RESPONSE_RECEIVED", outcome="UNKNOWN")
                task, work = self._mark_unknown(worker_conn, tenant_id=tenant_id, work_id=task["work_id"], task=task, now=now, fence_token=fence, next_check_at=_add_seconds(now, lease_seconds))
                execution_repository.release_lease(worker_conn, tenant_id=tenant_id, task_id=task_id, fence_token=fence)
                return {"task": task, "work": work, "outcome": "STILL_UNKNOWN"}

        with self._worker_transaction(tenant_id) as worker_conn:
            task = self._task_held_by_fence(worker_conn, tenant_id=tenant_id, task_id=task_id, fence_token=fence)
            outcome = self._apply_dispatch_result(worker_conn, tenant_id=tenant_id, work_id=task["work_id"], task=task, attempt_id=attempt_id, result=result, now=now, fence_token=fence)
            execution_repository.release_lease(worker_conn, tenant_id=tenant_id, task_id=task_id, fence_token=fence)
            return outcome

    # -- 5. Cancel: deterministic outcome against a racing dispatch ----------

    def cancel_booking(
        self, conn, *, tenant_id: str, work_id: str, task_id: str, reason: str, now: str,
    ) -> dict[str, Any]:
        """SD-W-11: cancellation only wins against a task still NEW. The
        actual race arbiter is execution_task's optimistic revision: both
        this call and a racing dispatch_booking perform their own
        ``revision``-guarded UPDATE on the same row; Postgres serializes the
        two UPDATEs and whichever commits first determines which transition
        (CANCELLED vs EXECUTING) actually happens -- the loser's
        VersionConflict here is not an error, it is this race's answer.
        """
        task = execution_repository.get_execution_task(conn, tenant_id=tenant_id, task_id=task_id)
        if task is None:
            raise TaskNotFoundError(f"no execution_task {task_id}")
        if str(task["work_id"]) != str(work_id):
            raise WorkPhaseMismatchError("execution_task does not belong to this Work")
        work = work_repository.get_work(conn, tenant_id=tenant_id, work_id=work_id)
        if work is None:
            raise TaskNotFoundError(f"no work {work_id}")
        if task["status"] != "NEW":
            raise TaskAlreadyDispatchedError(
                f"execution_task {task_id} is already {task['status']}; an already-dispatched or terminal action "
                "cannot be un-sent, it proceeds to reconciliation"
            )
        try:
            task = execution_repository.update_task_status(
                conn, tenant_id=tenant_id, task_id=task_id, expected_revision=task["revision"],
                new_status="CANCELLED", next_run_at=None,
            )
        except VersionConflict:
            current = execution_repository.get_execution_task(conn, tenant_id=tenant_id, task_id=task_id)
            raise TaskAlreadyDispatchedError(
                f"execution_task {task_id} moved to {current['status'] if current else '?'} "
                "before this cancellation committed"
            )
        work = work_repository.update_work_status(
            conn, tenant_id=tenant_id, work_id=work_id, expected_revision=work["revision"], new_status="CANCELLED",
            cancellation={"reason": reason},
        )
        work_repository.append_work_event(
            conn, tenant_id=tenant_id, work_id=work_id, event_type="work.cancelled", schema_version="1.0",
            payload={"reason": reason, "task_id": task_id}, occurred_at=now,
        )
        return {"task": task, "work": work}

    # -- 6. Deadline sweep: WAITING/UNKNOWN past deadline -> Escalation -------

    def check_deadlines(
        self, conn, *, tenant_id: str, now: str, owner: dict[str, Any], escalation_due_seconds: float = 3600,
    ) -> list[dict[str, Any]]:
        """SD §5 step 6 / SD-C-12: a task UNKNOWN/WAITING past its deadline
        gets an Escalation, never an automatic FAILED -- amount/authorization
        holds stay reserved until a human/owner resolves it."""
        created = []
        for task in execution_repository.list_tasks_overdue_for_escalation(conn, tenant_id=tenant_id, now=now):
            escalation, is_new = work_repository.create_escalation_if_absent(
                conn, tenant_id=tenant_id, escalation_id=_new_id(), work_id=task["work_id"], task_id=task["id"],
                reason=f"{task['operation']} 已超過查核期限 {task['deadline']}，目前仍為 {task['status']}",
                owner=owner, due_at=_add_seconds(now, escalation_due_seconds),
            )
            if is_new:
                created.append(escalation)
        return created

    # -- 7. Webhook: idempotent, never regresses a terminal task -------------

    def process_booking_webhook(
        self,
        conn,
        *,
        tenant_id: str,
        task_id: str,
        event_id: str,
        source_event_id: str,
        producer: str,
        outcome: str,
        external_ref: str,
        now: str,
    ) -> dict[str, Any]:
        """SD-C-04/SD-W-12: same source_event_id+hash is an idempotent ACK (no
        reapplication); same id with a different hash is quarantined by
        record_inbound_event itself; and a webhook arriving after the task is
        already DONE/FAILED/CANCELLED is acknowledged into the inbox but
        never allowed to change task/Work state."""
        raw_payload = {"task_id": task_id, "outcome": outcome, "external_ref": external_ref}
        raw_hash = _hash_snapshot(raw_payload)
        inbox_result = outbox_inbox_repository.record_inbound_event(
            conn, tenant_id=tenant_id, event_id=event_id, connector_account_id=None, environment="MOCK",
            producer=producer, source_event_id=source_event_id, raw_hash=raw_hash, raw_payload=raw_payload,
        )
        if inbox_result.outcome == outbox_inbox_repository.InboxOutcome.CONFLICT:
            return {"inbox_outcome": inbox_result.outcome, "applied": False}
        if inbox_result.outcome == outbox_inbox_repository.InboxOutcome.DUPLICATE:
            # A prior delivery may have recorded the inbox row but lost the
            # lease race.  RECEIVED is deliberately replayable using the
            # original row ID; PROCESSED is the normal duplicate no-op ACK.
            if inbox_result.row is None or inbox_result.row["processing_status"] != "RECEIVED":
                return {"inbox_outcome": inbox_result.outcome, "applied": False}
            inbox_event_id = str(inbox_result.row["id"])
        else:
            inbox_event_id = event_id

        task = execution_repository.get_execution_task(conn, tenant_id=tenant_id, task_id=task_id)
        if task is None or task["status"] not in ("WAITING", "UNKNOWN"):
            outbox_inbox_repository.mark_inbox_processed(conn, tenant_id=tenant_id, event_id=inbox_event_id, processed_at=now)
            return {
                "inbox_outcome": inbox_result.outcome, "applied": False,
                "task_status": task["status"] if task else None,
            }

        lease = execution_repository.acquire_lease(
            conn, tenant_id=tenant_id, task_id=task_id, holder=f"webhook:{producer}", now=now,
            lease_until=_add_seconds(now, 30), allowed_statuses=("WAITING", "UNKNOWN"),
        )
        if lease is None:
            # Leave the inbox RECEIVED: a scheduler can safely replay it once
            # the holder finishes, rather than applying under a stale fence.
            return {"inbox_outcome": inbox_result.outcome, "applied": False, "task_status": task["status"]}
        task = lease

        attempt_id = _new_id()
        execution_repository.record_attempt(
            conn, tenant_id=tenant_id, attempt_id=attempt_id, task_id=task_id,
            attempt_no=execution_repository.next_attempt_no(conn, tenant_id=tenant_id, task_id=task_id),
            attempt_kind="VERIFY", fence_token=task["lease_fence_token"], request_hash=task["request_hash"],
            started_at=now, request_ref=inbox_event_id,
        )
        if outcome == "CONFIRMED":
            execution_repository.append_observation(
                conn, tenant_id=tenant_id, attempt_id=attempt_id, sequence=1, observed_at=now,
                transport_result="RESPONSE_RECEIVED", outcome="SUCCEEDED", external_ref=external_ref,
                evidence_ref=f"webhook:{inbox_event_id}",
            )
            result: dict[str, Any] = self._complete_booking(
                conn, tenant_id=tenant_id, work_id=task["work_id"], task=task, external_ref=external_ref,
                evidence_ref=f"webhook:{inbox_event_id}", now=now, fence_token=task["lease_fence_token"],
            )
            response = {"task": result["task"], "work": result["work"], "outcome": "SUCCEEDED"}
        elif outcome == "REJECTED":
            execution_repository.append_observation(
                conn, tenant_id=tenant_id, attempt_id=attempt_id, sequence=1, observed_at=now,
                transport_result="RESPONSE_RECEIVED", outcome="FAILED",
            )
            task2, work2 = self._fail_booking(
                conn, tenant_id=tenant_id, work_id=task["work_id"], task=task,
                message="webhook reported the supplier rejected the booking", now=now,
                fence_token=task["lease_fence_token"],
            )
            response = {"task": task2, "work": work2, "outcome": "FAILED"}
        else:
            execution_repository.release_lease(conn, tenant_id=tenant_id, task_id=task_id, fence_token=task["lease_fence_token"])
            raise ValueError(f"unknown webhook outcome {outcome!r}")

        outbox_inbox_repository.mark_inbox_processed(conn, tenant_id=tenant_id, event_id=inbox_event_id, processed_at=now)
        execution_repository.release_lease(conn, tenant_id=tenant_id, task_id=task_id, fence_token=task["lease_fence_token"])
        return {"inbox_outcome": inbox_result.outcome, "applied": True, **response}

    # -- 8. Notification: its own task, failure never reopens the booking ----

    def send_notification(
        self, conn, *, tenant_id: str, work_id: str, order_id: str, channel: str, now: str,
        notifier: Callable[[], bool], holder: str = "notification-worker",
    ) -> dict[str, Any]:
        """SD-W-09: a notification failure must only ever retry the
        notification; it must never roll back the booking's own success or
        its evidence. This is why notification is its own ExecutionTask with
        its own business_key/postcondition, not a field on the booking task."""
        business_key = f"notification.send:{order_id}:{channel}"
        snapshot = {"order_id": order_id, "channel": channel}
        task = execution_repository.create_execution_task(
            conn, tenant_id=tenant_id, task_id=_new_id(), work_id=work_id, kind="ACTION",
            operation="notification.send", business_key=business_key, request_hash=_hash_snapshot(snapshot),
            request_snapshot=snapshot, postcondition_version="notification-v1",
            postcondition={"delivered_or_accepted": True},
        )
        if task["status"] == "DONE":
            return task
        if task["status"] not in ("NEW", "FAILED"):
            raise TaskLeaseContendedError(f"notification task {task['id']} is {task['status']}")
        lease = execution_repository.acquire_lease(
            conn, tenant_id=tenant_id, task_id=task["id"], holder=holder, now=now, lease_until=_add_seconds(now, 30),
            allowed_statuses=("NEW", "FAILED"),
        )
        if lease is None:
            raise TaskLeaseContendedError(f"notification task {task['id']} lease is held by another worker")
        fence = lease["lease_fence_token"]
        task = execution_repository.update_task_status(
            conn, tenant_id=tenant_id, task_id=task["id"], expected_revision=task["revision"],
            new_status="EXECUTING", fence_token=fence,
        )

        attempt_id = _new_id()
        execution_repository.record_attempt(
            conn, tenant_id=tenant_id, attempt_id=attempt_id, task_id=task["id"],
            attempt_no=execution_repository.next_attempt_no(conn, tenant_id=tenant_id, task_id=task["id"]),
            attempt_kind="DISPATCH", fence_token=fence, request_hash=task["request_hash"], started_at=now,
        )
        delivered = notifier()
        if delivered:
            execution_repository.append_observation(
                conn, tenant_id=tenant_id, attempt_id=attempt_id, sequence=1, observed_at=now,
                transport_result="RESPONSE_RECEIVED", outcome="SUCCEEDED", evidence_ref=f"notifier:{business_key}",
            )
            task = execution_repository.update_task_status(
                conn, tenant_id=tenant_id, task_id=task["id"], expected_revision=task["revision"],
                new_status="DONE", fence_token=fence,
            )
        else:
            execution_repository.append_observation(
                conn, tenant_id=tenant_id, attempt_id=attempt_id, sequence=1, observed_at=now,
                transport_result="RESPONSE_RECEIVED", outcome="FAILED",
            )
            task = execution_repository.update_task_status(
                conn, tenant_id=tenant_id, task_id=task["id"], expected_revision=task["revision"],
                new_status="FAILED", fence_token=fence,
            )
            work_repository.create_escalation_if_absent(
                conn, tenant_id=tenant_id, escalation_id=_new_id(), work_id=work_id, task_id=task["id"],
                reason=f"{channel} 通知失敗，只重送通知，不影響已成功的預訂與付款", owner=SYSTEM_ACTOR,
                due_at=_add_seconds(now, 3600),
            )
        execution_repository.release_lease(conn, tenant_id=tenant_id, task_id=task["id"], fence_token=fence)
        return task

    # -- internals -------------------------------------------------------

    def _assert_dispatch_approval(self, conn, *, tenant_id: str, task: dict[str, Any], now: str) -> None:
        """Recheck the immutable decision/approval projection immediately
        before dispatch.  A UI flag or stale approval cannot authorize I/O.
        """
        approval_id = task["request_snapshot"].get("approval_id")
        if not approval_id or not approval_repository.approval_is_effective(
            conn, tenant_id=tenant_id, approval_id=str(approval_id), now=now
        ):
            raise WorkPhaseMismatchError("booking approval is expired, revoked, or unavailable")
        approval = approval_repository.get_approval_record(conn, tenant_id=tenant_id, approval_id=str(approval_id))
        if approval is None or approval["payload_hash"] != canonical_json.payload_hash(approval["approved_payload"]):
            raise WorkPhaseMismatchError("booking approval payload integrity check failed")
        manifest = approval["scope_manifest"]
        if len(manifest) != 1 or {item.get("item_id"): item.get("operation") for item in manifest} != {"booking": "booking.create"}:
            raise WorkPhaseMismatchError("booking approval scope no longer matches the task")
        snapshot = task["request_snapshot"]
        payload = approval["approved_payload"]
        if str(approval["decision_id"]) != str(snapshot.get("decision_id")):
            raise WorkPhaseMismatchError("booking approval decision does not match the task")
        expected = {
            "work_id": task["work_id"], "quote_id": snapshot.get("quote_id"),
            "order_id": snapshot.get("order_id"), "session_id": snapshot.get("session_id"),
            "party_size": snapshot.get("party_size"), "operation": task["operation"],
        }
        if any(str(payload.get(field)) != str(value) for field, value in expected.items()):
            raise WorkPhaseMismatchError("booking approval payload no longer binds the task request")

    def _apply_dispatch_result(
        self, conn, *, tenant_id: str, work_id: str, task: dict[str, Any], attempt_id: str,
        result: OperationResult, now: str, fence_token: int,
    ) -> dict[str, Any]:
        if isinstance(result, Succeeded):
            execution_repository.append_observation(
                conn, tenant_id=tenant_id, attempt_id=attempt_id, sequence=1, observed_at=now,
                transport_result="RESPONSE_RECEIVED", outcome="SUCCEEDED", external_ref=result.external_reference,
                evidence_ref=result.evidence_refs[0],
            )
            out = self._complete_booking(
                conn, tenant_id=tenant_id, work_id=work_id, task=task, external_ref=result.external_reference,
                evidence_ref=result.evidence_refs[0], now=now, fence_token=fence_token,
                source_revision=result.source_revision,
            )
            return {"task": out["task"], "work": out["work"], "evidence": out["evidence"], "outcome": "SUCCEEDED"}
        if isinstance(result, Failed):
            execution_repository.append_observation(
                conn, tenant_id=tenant_id, attempt_id=attempt_id, sequence=1, observed_at=now,
                transport_result="RESPONSE_RECEIVED", outcome="FAILED",
                evidence_ref=result.evidence_refs[0] if result.evidence_refs else None,
            )
            task2, work2 = self._fail_booking(
                conn, tenant_id=tenant_id, work_id=work_id, task=task, message=result.message, now=now,
                fence_token=fence_token,
            )
            return {"task": task2, "work": work2, "outcome": "FAILED"}
        raise TypeError(f"unhandled OperationResult from booking.create/lookup: {result!r}")

    def _complete_booking(
        self, conn, *, tenant_id: str, work_id: str, task: dict[str, Any], external_ref: str, evidence_ref: str,
        now: str, fence_token: int, source_revision: str | None = None,
    ) -> dict[str, Any]:
        task = execution_repository.update_task_status(
            conn, tenant_id=tenant_id, task_id=task["id"], expected_revision=task["revision"], new_status="DONE",
            fence_token=fence_token, next_run_at=None,
        )
        fulfillment_repository.update_order_supplier_booking(
            conn, tenant_id=tenant_id, order_id=task["request_snapshot"]["order_id"],
            supplier_booking_status="CONFIRMED", external_ref=external_ref,
        )
        evidence = work_repository.create_completion_evidence(
            conn, tenant_id=tenant_id, evidence_id=_new_id(), work_id=work_id, task_id=task["id"],
            evidence_type="SUPPLIER_BOOKING_CONFIRMATION", environment="MOCK", external_ref=external_ref,
            observed_at=now, verifier_version=VERIFIER_VERSION, source_revision=source_revision,
            verified_at=now, payload_ref=evidence_ref,
        )
        work = work_repository.get_work(conn, tenant_id=tenant_id, work_id=work_id)
        conditions = work["completion_conditions"]
        for condition in conditions:
            if condition["condition_id"] == "booking_confirmed":
                condition["satisfied"] = True
                condition["evidence_ref"] = evidence["id"]
        work = work_repository.update_work_status(
            conn, tenant_id=tenant_id, work_id=work_id, expected_revision=work["revision"], new_status="VERIFYING",
            completion_conditions=conditions,
        )
        work_repository.append_work_event(
            conn, tenant_id=tenant_id, work_id=work_id, event_type="execution.verified", schema_version="1.0",
            payload={"task_id": task["id"], "external_ref": external_ref}, occurred_at=now,
        )
        work = work_repository.update_work_status(
            conn, tenant_id=tenant_id, work_id=work_id, expected_revision=work["revision"], new_status="COMPLETED",
            completion_record={
                "evidence_refs": [{"tenant_id": tenant_id, "id": evidence["id"]}],
                "verifier_version": VERIFIER_VERSION, "completed_at": now,
                "completion_contract_version": work["completion_contract_version"],
            },
        )
        work_repository.append_work_event(
            conn, tenant_id=tenant_id, work_id=work_id, event_type="work.completed", schema_version="1.0",
            payload={"evidence_id": evidence["id"]}, occurred_at=now,
        )
        return {"task": task, "work": work, "evidence": evidence}

    def _fail_booking(
        self, conn, *, tenant_id: str, work_id: str, task: dict[str, Any], message: str, now: str, fence_token: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        task = execution_repository.update_task_status(
            conn, tenant_id=tenant_id, task_id=task["id"], expected_revision=task["revision"], new_status="FAILED",
            fence_token=fence_token, next_run_at=None,
        )
        work = work_repository.get_work(conn, tenant_id=tenant_id, work_id=work_id)
        work = work_repository.update_work_status(
            conn, tenant_id=tenant_id, work_id=work_id, expected_revision=work["revision"], new_status="FAILED",
            failure={"reason": message, "irreversible_effects_resolved": True},
        )
        work_repository.append_work_event(
            conn, tenant_id=tenant_id, work_id=work_id, event_type="work.failed", schema_version="1.0",
            payload={"task_id": task["id"], "reason": message}, occurred_at=now,
        )
        return task, work

    def _mark_unknown(
        self, conn, *, tenant_id: str, work_id: str, task: dict[str, Any], now: str, fence_token: int,
        next_check_at: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        task = execution_repository.update_task_status(
            conn, tenant_id=tenant_id, task_id=task["id"], expected_revision=task["revision"], new_status="UNKNOWN",
            fence_token=fence_token, next_run_at=next_check_at,
        )
        work = work_repository.get_work(conn, tenant_id=tenant_id, work_id=work_id)
        work = work_repository.update_work_status(
            conn, tenant_id=tenant_id, work_id=work_id, expected_revision=work["revision"], new_status="WAITING_EXTERNAL",
            waiting_external={
                "task_refs": [{"tenant_id": tenant_id, "id": task["id"]}],
                "waiting_reason": "RESULT_UNKNOWN",
                "responsible": SYSTEM_ACTOR,
            },
        )
        work_repository.append_work_event(
            conn, tenant_id=tenant_id, work_id=work_id, event_type="execution.result_unknown", schema_version="1.0",
            payload={"task_id": task["id"]}, occurred_at=now,
        )
        return task, work
