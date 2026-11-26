#!/usr/bin/env python3
"""Executable contract tests for backlog ENG-06 (商家工作台接真實工作狀態).

Each test maps to a line of docs/collaboration/backlog.md#eng-06's
acceptance list; the mapping is restated in
specs/workbench/acceptance-trace.md. These exercise the real
services/workbench/service.py against the ENG-01 domain schemas and the
ENG-04 connector mock (no re-implemented shadow logic, no database/browser).
"""
from __future__ import annotations

import unittest

from services.workbench import schema_validation
from services.workbench.errors import (
    AuthorizationStaleError,
    CrossTenantReferenceRejectedError,
    DecisionNotPendingError,
    InvalidServiceRevisionFieldError,
    WorkNotFoundError,
    WorkPhaseMismatchError,
)
from services.workbench.repository import WorkbenchRepository
from services.workbench.service import WorkbenchService

TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_TENANT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CASE_ID = {"tenant_id": TENANT, "id": "00000000-0000-4000-8000-000000000001"}
MERCHANT = {"actor_kind": "EMPLOYEE", "actor_id": "00000000-0000-4000-8000-0000000000e1"}

MERCHANT_TEXT = (
    "原本的完整體驗保留。另做60分鐘品飲，兩款茶和一份茶點，不含沖泡實作。"
    "平日14:00，每人680元，最多6人，和原活動共用老師。現場中文示範，搭配英文說明卡。"
)


def _valid_fields(**overrides) -> dict:
    fields = {
        "name": "60 分鐘品飲版",
        "content": MERCHANT_TEXT,
        "price": {"amount_minor_units": "68000", "currency": "TWD", "currency_scale_ref": "twd-v1"},
        "duration_minutes": 60,
        "capacity": 6,
        "available_times": "平日 14:00",
        "onsite_note": "中文示範＋英文說明卡",
        "channels": ["WEB", "PARTNER"],
    }
    fields.update(overrides)
    return fields


def _new_service() -> WorkbenchService:
    return WorkbenchService(repository=WorkbenchRepository())


def _propose_and_approve(service: WorkbenchService, channels=("WEB", "PARTNER")) -> tuple[dict, dict]:
    """Walks the merchant-facing steps only: discuss -> material -> review ->
    approve. Returns (work, decision_as_approved)."""
    fields = _valid_fields(channels=list(channels))
    work = service.propose_service_revision(
        TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
        merchant_text=MERCHANT_TEXT, fields=fields,
    )
    service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="asset-demo-card", rights_confirmed=True)
    work, decision = service.request_decision(TENANT, work["id"], now="2026-11-27T01:06:00Z", expires_at="2026-11-28T01:06:00Z")
    work = service.submit_decision(
        TENANT, decision["id"], now="2026-11-27T01:10:00Z", selected_option_id="approve",
        if_match_revision=decision["revision"], if_match_payload_hash=decision["payload_hash"],
    )
    decision = service._repo.get_decision(TENANT, decision["id"])
    return work, decision


class ProposalPreservesVerbatimContent(unittest.TestCase):
    """backlog ENG-06: 模型解析出的內容可核對且不被固定範例覆蓋."""

    def test_decision_card_content_equals_merchants_own_text_not_a_canned_example(self) -> None:
        service = _new_service()
        custom_text = "改成咖啡拉花體驗，兩杯咖啡，不含拉花教學。平日15:00，每人500元，最多4人。"
        custom_price = {"amount_minor_units": "50000", "currency": "TWD", "currency_scale_ref": "twd-v1"}
        fields = _valid_fields(name="咖啡拉花體驗", content=custom_text, capacity=4, duration_minutes=45, price=custom_price)
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=custom_text, fields=fields,
        )
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_waived=True)
        _, decision = service.request_decision(TENANT, work["id"], now="2026-11-27T01:06:00Z", expires_at="2026-11-28T01:06:00Z")

        self.assertEqual(decision["display_payload"]["content"], custom_text)
        self.assertNotIn("兩款茶", decision["display_payload"]["content"])
        self.assertEqual(decision["display_payload"]["price"], custom_price)

    def test_mismatched_content_field_is_rejected_before_any_work_is_created(self) -> None:
        service = _new_service()
        fields = _valid_fields(content="與 merchant_text 不符的內容，不得被服務自行改寫或代換成固定範例示意文字。")
        with self.assertRaises(InvalidServiceRevisionFieldError):
            service.propose_service_revision(
                TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
                merchant_text=MERCHANT_TEXT, fields=fields,
            )
        self.assertEqual(service._repo.list_works(TENANT), [])


class InvalidFieldsRejectedByBackend(unittest.TestCase):
    """backlog ENG-06: 容量等不合法值在前後端都被拒絕 (backend half; see
    tests/workbench_frontend_test.cjs for the matching frontend half)."""

    def test_zero_capacity_rejected(self) -> None:
        service = _new_service()
        with self.assertRaises(InvalidServiceRevisionFieldError):
            service.propose_service_revision(
                TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
                merchant_text=MERCHANT_TEXT, fields=_valid_fields(capacity=0),
            )

    def test_nine_capacity_rejected(self) -> None:
        service = _new_service()
        with self.assertRaises(InvalidServiceRevisionFieldError):
            service.propose_service_revision(
                TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
                merchant_text=MERCHANT_TEXT, fields=_valid_fields(capacity=9),
            )

    def test_one_and_eight_capacity_accepted(self) -> None:
        service = _new_service()
        for capacity in (1, 8):
            with self.subTest(capacity=capacity):
                work = service.propose_service_revision(
                    TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
                    merchant_text=MERCHANT_TEXT, fields=_valid_fields(capacity=capacity),
                )
                self.assertEqual(work["status"], "WAITING_INPUT")

    def test_zero_price_rejected(self) -> None:
        service = _new_service()
        with self.assertRaises(InvalidServiceRevisionFieldError):
            service.propose_service_revision(
                TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
                merchant_text=MERCHANT_TEXT,
                fields=_valid_fields(price={"amount_minor_units": "0", "currency": "TWD", "currency_scale_ref": "twd-v1"}),
            )

    def test_duration_under_15_minutes_rejected(self) -> None:
        service = _new_service()
        with self.assertRaises(InvalidServiceRevisionFieldError):
            service.propose_service_revision(
                TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
                merchant_text=MERCHANT_TEXT, fields=_valid_fields(duration_minutes=10),
            )


class PendingNeverShownAsSuccess(unittest.TestCase):
    """backlog ENG-06: 後端仍 pending 時首頁不顯示已成功."""

    def test_channels_stay_not_started_until_dispatched(self) -> None:
        service = _new_service()
        work, _ = _propose_and_approve(service)
        status = service.get_work_status(TENANT, work["id"])
        self.assertEqual(status["status"], "RUNNING")
        self.assertEqual(status["channels"], {"WEB": "not_started", "PARTNER": "not_started"})

    def test_channel_stays_pending_through_async_submission_not_live(self) -> None:
        service = _new_service()
        work, _ = _propose_and_approve(service)
        work = service.advance_execution(TENANT, work["id"], now="2026-11-27T01:11:00Z")
        status = service.get_work_status(TENANT, work["id"])
        self.assertEqual(status["status"], "WAITING_EXTERNAL")
        self.assertEqual(status["channels"], {"WEB": "pending", "PARTNER": "pending"})
        self.assertNotIn("live", status["channels"].values())
        # a second reconcile tick without any external review event must still not claim success
        work = service.advance_execution(TENANT, work["id"], now="2026-11-27T01:12:00Z")
        status = service.get_work_status(TENANT, work["id"])
        self.assertEqual(status["channels"], {"WEB": "pending", "PARTNER": "pending"})

    def test_only_a_real_terminal_readback_turns_a_channel_live(self) -> None:
        service = _new_service()
        work, _ = _propose_and_approve(service, channels=("WEB",))
        service.advance_execution(TENANT, work["id"], now="2026-11-27T01:11:00Z")  # dispatch -> WAITING
        status = service.get_work_status(TENANT, work["id"])
        self.assertEqual(status["channels"]["WEB"], "pending")

        service.simulate_channel_review_result(TENANT, work["id"], "WEB", "LIVE_VERIFIED")
        work = service.advance_execution(TENANT, work["id"], now="2026-11-27T01:13:00Z")  # reconcile -> DONE
        status = service.get_work_status(TENANT, work["id"])
        self.assertEqual(status["channels"]["WEB"], "live")
        self.assertEqual(status["status"], "COMPLETED")
        self.assertTrue(status["completion_record"]["evidence_refs"])


class RefreshResumesWork(unittest.TestCase):
    """backlog ENG-06: 刷新可恢復工作."""

    def test_a_fresh_service_bound_to_the_same_store_reads_identical_state(self) -> None:
        shared_repo = WorkbenchRepository()
        service = WorkbenchService(repository=shared_repo)
        work, _ = _propose_and_approve(service)
        service.advance_execution(TENANT, work["id"], now="2026-11-27T01:11:00Z")

        # "refresh" == a brand new request-scoped service object re-reading the
        # same durable store; no client timer or localStorage snapshot is
        # involved, unlike the UX 2.1 prototype (docs/verification/prototype-audit.md §6.1).
        reloaded = WorkbenchService(repository=shared_repo)
        before = service.get_work_status(TENANT, work["id"])
        after = reloaded.get_work_status(TENANT, work["id"])
        self.assertEqual(before, after)
        self.assertEqual(after["status"], "WAITING_EXTERNAL")

    def test_home_view_after_refresh_still_shows_the_decision_card_pending(self) -> None:
        shared_repo = WorkbenchRepository()
        service = WorkbenchService(repository=shared_repo)
        fields = _valid_fields()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=fields,
        )
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="a1", rights_confirmed=True)
        service.request_decision(TENANT, work["id"], now="2026-11-27T01:06:00Z", expires_at="2026-11-28T01:06:00Z")

        reloaded = WorkbenchService(repository=shared_repo)
        home = reloaded.get_home_view(TENANT)
        self.assertEqual(len(home), 1)
        self.assertEqual(home[0]["status"], "WAITING_DECISION")
        self.assertEqual(home[0]["decision_card"]["display_payload"]["content"], MERCHANT_TEXT)


class HomeViewReflectsActualMissingFields(unittest.TestCase):
    """A merchant who already provided everything must never be told the
    asset is still missing -- docs/verification/prototype-audit.md §9:
    正式前端應讓文字與核准、工作、外部結果的實際狀態一致."""

    def test_missing_fields_clears_once_asset_is_waived_even_before_request_decision(self) -> None:
        service = _new_service()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
        )
        home_before = service.get_home_view(TENANT)
        self.assertEqual(home_before[0]["missing_fields"], ["asset_ref", "rights_confirmed"])

        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_waived=True)
        home_after = service.get_home_view(TENANT)
        self.assertEqual(home_after[0]["status"], "WAITING_INPUT")
        self.assertEqual(home_after[0]["missing_fields"], [])

    def test_missing_fields_clears_once_asset_and_rights_are_both_provided(self) -> None:
        service = _new_service()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
        )
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="asset-demo-card")
        still_needs_rights = service.get_home_view(TENANT)[0]["missing_fields"]
        self.assertEqual(still_needs_rights, ["rights_confirmed"])

        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:06:00Z", rights_confirmed=True)
        self.assertEqual(service.get_home_view(TENANT)[0]["missing_fields"], [])


class PartialResultsAreHonest(unittest.TestCase):
    def test_one_channel_rejected_yields_partial_not_completed(self) -> None:
        service = _new_service()
        work, _ = _propose_and_approve(service, channels=("WEB", "PARTNER"))
        service.advance_execution(TENANT, work["id"], now="2026-11-27T01:11:00Z")  # dispatch both

        service.simulate_channel_review_result(TENANT, work["id"], "WEB", "LIVE_VERIFIED")
        service.simulate_channel_review_result(TENANT, work["id"], "PARTNER", "REJECTED")
        work = service.advance_execution(TENANT, work["id"], now="2026-11-27T01:13:00Z")

        self.assertEqual(work["status"], "PARTIAL")
        status = service.get_work_status(TENANT, work["id"])
        self.assertEqual(status["channels"], {"WEB": "live", "PARTNER": "rejected"})
        self.assertEqual(status["partial_summary"]["completed_items"], ["WEB"])
        self.assertEqual(status["partial_summary"]["incomplete_items"][0]["item"], "PARTNER")
        self.assertIsNone(status["completion_record"])


class NormalFlowNeedsNoPerStepExecuteButton(unittest.TestCase):
    """backlog ENG-06: 正常工作不用商家逐步按執行按鈕."""

    def test_merchant_facing_calls_end_at_approval_execution_is_a_worker_tick(self) -> None:
        service = _new_service()
        work, decision = _propose_and_approve(service, channels=("WEB", "PARTNER", ))
        # Exactly the UX 2.1 steps map 1:1 onto merchant-facing service calls:
        # discuss (propose) -> material (submit_missing_input) -> review
        # (request_decision) -> approve (submit_decision). None of them is a
        # per-channel "execute" action, and there were two channels.
        self.assertEqual(work["status"], "RUNNING")
        self.assertEqual(decision["status"], "APPROVED")

        # advance_execution is the only thing left to call, and it is a
        # worker tick (not keyed to a channel) called an arbitrary number of
        # times until the work reaches a terminal state -- a merchant never
        # calls a distinct "execute WEB" / "execute PARTNER" action.
        service.advance_execution(TENANT, work["id"], now="2026-11-27T01:11:00Z")  # dispatch both channels
        for channel in ("WEB", "PARTNER"):
            service.simulate_channel_review_result(TENANT, work["id"], channel, "LIVE_VERIFIED")
        ticks = 0
        while service.get_work_status(TENANT, work["id"])["status"] not in ("COMPLETED", "PARTIAL", "FAILED"):
            service.advance_execution(TENANT, work["id"], now="2026-11-27T01:2%d:00Z" % ticks)
            ticks += 1
            self.assertLess(ticks, 10, "advance_execution should converge within a handful of ticks")
        self.assertEqual(service.get_work_status(TENANT, work["id"])["status"], "COMPLETED")


class TenantIsolation(unittest.TestCase):
    def test_other_tenant_cannot_read_this_tenants_work(self) -> None:
        service = _new_service()
        work, _ = _propose_and_approve(service)
        with self.assertRaises(WorkNotFoundError):
            service.get_work_status(OTHER_TENANT, work["id"])


class DecisionLifecycleGuards(unittest.TestCase):
    def test_stale_if_match_is_rejected(self) -> None:
        service = _new_service()
        fields = _valid_fields()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=fields,
        )
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="a1", rights_confirmed=True)
        _, decision = service.request_decision(TENANT, work["id"], now="2026-11-27T01:06:00Z", expires_at="2026-11-28T01:06:00Z")

        with self.assertRaises(AuthorizationStaleError):
            service.submit_decision(
                TENANT, decision["id"], now="2026-11-27T01:10:00Z", selected_option_id="approve",
                if_match_revision=decision["revision"], if_match_payload_hash="0" * 64,
            )

    def test_deciding_twice_is_rejected(self) -> None:
        service = _new_service()
        work, decision = _propose_and_approve(service)
        with self.assertRaises(DecisionNotPendingError):
            service.submit_decision(
                TENANT, decision["id"], now="2026-11-27T01:20:00Z", selected_option_id="approve",
                if_match_revision=decision["revision"], if_match_payload_hash=decision["payload_hash"],
            )

    def test_declining_cancels_the_work_without_touching_execution(self) -> None:
        service = _new_service()
        fields = _valid_fields()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=fields,
        )
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="a1", rights_confirmed=True)
        _, decision = service.request_decision(TENANT, work["id"], now="2026-11-27T01:06:00Z", expires_at="2026-11-28T01:06:00Z")
        work = service.submit_decision(
            TENANT, decision["id"], now="2026-11-27T01:10:00Z", selected_option_id="defer",
            if_match_revision=decision["revision"], if_match_payload_hash=decision["payload_hash"],
        )
        self.assertEqual(work["status"], "CANCELLED")
        self.assertEqual(service._repo.list_tasks_for_work(TENANT, work["id"]), [])

    def test_submitting_input_while_already_waiting_on_decision_is_rejected(self) -> None:
        service = _new_service()
        work, _ = _propose_and_approve(service)
        with self.assertRaises(WorkPhaseMismatchError):
            service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:30:00Z", asset_waived=True)


class StoredEntitiesMatchDomainSchemas(unittest.TestCase):
    """Every persisted Work/ExecutionTask/DecisionRequest must independently
    re-validate against specs/domain/*.schema.json, not just at write time."""

    def test_completed_work_and_tasks_revalidate_against_domain_schemas(self) -> None:
        service = _new_service()
        work, _ = _propose_and_approve(service, channels=("WEB",))
        service.advance_execution(TENANT, work["id"], now="2026-11-27T01:11:00Z")
        service.simulate_channel_review_result(TENANT, work["id"], "WEB", "LIVE_VERIFIED")
        work = service.advance_execution(TENANT, work["id"], now="2026-11-27T01:13:00Z")

        schema_validation.validate_work(work)
        for task in service._repo.list_tasks_for_work(TENANT, work["id"]):
            schema_validation.validate_execution_task(task)


class TenantAndApprovalTimingGuards(unittest.TestCase):
    """R1 review findings F1(a)/F1(b) (Antigravity, candidate d3aa041010e6):
    a Work must not be creatable against another tenant's case, and an
    expired decision must not still be approvable."""

    def test_proposing_against_another_tenants_case_id_is_rejected(self) -> None:
        service = _new_service()
        other_tenant_case = {"tenant_id": OTHER_TENANT, "id": "00000000-0000-4000-8000-000000000099"}
        with self.assertRaises(CrossTenantReferenceRejectedError):
            service.propose_service_revision(
                TENANT, other_tenant_case, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
                merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
            )
        self.assertEqual(service._repo.list_works(TENANT), [])

    def test_approving_an_expired_decision_is_rejected_not_run_into_running(self) -> None:
        service = _new_service()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
        )
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="a1", rights_confirmed=True)
        _, decision = service.request_decision(TENANT, work["id"], now="2026-11-27T01:06:00Z", expires_at="2026-11-27T01:30:00Z")

        with self.assertRaises(DecisionNotPendingError):
            service.submit_decision(
                TENANT, decision["id"], now="2026-11-27T02:00:00Z", selected_option_id="approve",
                if_match_revision=decision["revision"], if_match_payload_hash=decision["payload_hash"],
            )
        work = service.get_work_status(TENANT, work["id"])
        self.assertEqual(work["status"], "WAITING_DECISION")


class ExecutionPhaseGuards(unittest.TestCase):
    """R1 review finding F2 (Antigravity, candidate d3aa041010e6):
    advance_execution must reject Work phases it cannot tick (instead of an
    uncaught StopIteration) and must never rewrite a terminal Work's
    completion evidence/revision on a repeated tick."""

    def test_ticking_a_work_still_waiting_on_input_is_rejected_not_a_crash(self) -> None:
        service = _new_service()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
        )
        with self.assertRaises(WorkPhaseMismatchError):
            service.advance_execution(TENANT, work["id"], now="2026-11-27T01:05:00Z")

    def test_ticking_a_waiting_decision_work_is_rejected_not_a_crash(self) -> None:
        service = _new_service()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
        )
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="a1", rights_confirmed=True)
        service.request_decision(TENANT, work["id"], now="2026-11-27T01:06:00Z", expires_at="2026-11-28T01:06:00Z")
        with self.assertRaises(WorkPhaseMismatchError):
            service.advance_execution(TENANT, work["id"], now="2026-11-27T01:07:00Z")

    def test_ticking_a_cancelled_work_is_rejected(self) -> None:
        service = _new_service()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
        )
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="a1", rights_confirmed=True)
        _, decision = service.request_decision(TENANT, work["id"], now="2026-11-27T01:06:00Z", expires_at="2026-11-28T01:06:00Z")
        service.submit_decision(
            TENANT, decision["id"], now="2026-11-27T01:10:00Z", selected_option_id="defer",
            if_match_revision=decision["revision"], if_match_payload_hash=decision["payload_hash"],
        )
        with self.assertRaises(WorkPhaseMismatchError):
            service.advance_execution(TENANT, work["id"], now="2026-11-27T01:11:00Z")

    def test_ticking_a_completed_work_again_does_not_rewrite_its_completion_evidence(self) -> None:
        service = _new_service()
        work, _ = _propose_and_approve(service, channels=("WEB",))
        service.advance_execution(TENANT, work["id"], now="2026-11-27T01:11:00Z")
        service.simulate_channel_review_result(TENANT, work["id"], "WEB", "LIVE_VERIFIED")
        work = service.advance_execution(TENANT, work["id"], now="2026-11-27T01:13:00Z")
        self.assertEqual(work["status"], "COMPLETED")
        first_completed_at = work["completion_record"]["completed_at"]
        first_revision = work["revision"]

        with self.assertRaises(WorkPhaseMismatchError):
            service.advance_execution(TENANT, work["id"], now="2026-11-27T01:30:00Z")
        unchanged = service.get_work_status(TENANT, work["id"])
        self.assertEqual(unchanged["completion_record"]["completed_at"], first_completed_at)
        self.assertEqual(service._repo.get_work(TENANT, work["id"])["revision"], first_revision)


class RightsConfirmationIsPerAsset(unittest.TestCase):
    """R1 review finding F3(a) (Antigravity, candidate d3aa041010e6): a
    previously confirmed rights_confirmed=True must not silently carry over
    to a different, later-supplied asset_ref, and a submit_missing_input
    call must not accept contradictory or empty asset fields."""

    def test_replacing_the_asset_resets_rights_confirmation(self) -> None:
        service = _new_service()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
        )
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="asset-a", rights_confirmed=True)
        self.assertEqual(service.get_home_view(TENANT)[0]["missing_fields"], [])

        # A different asset is substituted without re-confirming rights --
        # the old confirmation must not leak onto the new asset.
        service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:06:00Z", asset_ref="asset-b")
        self.assertEqual(service.get_home_view(TENANT)[0]["missing_fields"], ["rights_confirmed"])

    def test_empty_asset_ref_is_rejected(self) -> None:
        service = _new_service()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
        )
        with self.assertRaises(InvalidServiceRevisionFieldError):
            service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="")

    def test_asset_ref_and_asset_waived_together_is_rejected(self) -> None:
        service = _new_service()
        work = service.propose_service_revision(
            TENANT, CASE_ID, MERCHANT, now="2026-11-27T01:00:00Z", due_at="2026-11-28T01:00:00Z",
            merchant_text=MERCHANT_TEXT, fields=_valid_fields(),
        )
        with self.assertRaises(InvalidServiceRevisionFieldError):
            service.submit_missing_input(TENANT, work["id"], now="2026-11-27T01:05:00Z", asset_ref="asset-a", asset_waived=True)


if __name__ == "__main__":
    unittest.main()
