"""Executable contract tests for backlog ENG-04.

Each test maps to one line of docs/collaboration/backlog.md#eng-04's
acceptance list; the mapping is restated in
specs/connector/acceptance-trace.md. These exercise the real
connectors/* classes (no re-implemented shadow logic) against fixed data
in connectors/fixtures.py; they do not start a database, a browser or any
network connector (AI_COLLABORATION_GUIDE.md §0.7).
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from connectors import fixtures
from connectors.base import Connector
from connectors.errors import BusinessKeyConflictError, CapabilityUnavailableError
from connectors.mocks.experience_reservation import ExperienceReservationMock
from connectors.mocks.ota_delayed_publication import OtaDelayedPublicationMock
from connectors.mocks.pms_nightly import PmsNightlyMock
from connectors.types import (
    AuthorizationState,
    Failed,
    Pending,
    SideEffect,
    SideEffectDisposition,
    Succeeded,
    SupportLevel,
    Unknown,
)

ROOT = Path(__file__).resolve().parents[1]

# Mirrors specs/domain/common/identifiers.schema.json#/$defs/BusinessOperationKey
# (ENG-01); connector business keys must stay compatible with the domain
# layer's persisted business_key column.
BUSINESS_OPERATION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*:[A-Za-z0-9_.:-]+$")


class BusinessKeyFixtureShapeTest(unittest.TestCase):
    def test_fixture_business_keys_match_domain_business_operation_key(self) -> None:
        for key in ("booking.create:case-exp-001", "booking.create:case-pms-001", "publication.update:offer-42-ota-a"):
            self.assertRegex(key, BUSINESS_OPERATION_KEY_PATTERN)


# ENG-04 acceptance: "PMS 未提供發布能力時在呼叫前拒絕"
class PmsPublicationCapabilityGateTest(unittest.TestCase):
    def test_publication_rejected_before_any_call(self) -> None:
        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))
        self.assertEqual(pms.publication_call_count, 0)

        with self.assertRaises(CapabilityUnavailableError) as ctx:
            pms.submit_publication()

        self.assertEqual(ctx.exception.descriptor.support, SupportLevel.UNSUPPORTED)
        # The counter only proves the method was entered; no booking/night
        # state was ever touched because ensure_capability raised first.
        self.assertEqual(pms.publication_call_count, 1)
        self.assertEqual(pms._booked, {})

    def test_describe_capability_reports_unsupported_without_raising(self) -> None:
        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))
        descriptor = pms.describe_capability("publication.update")
        self.assertEqual(descriptor.support, SupportLevel.UNSUPPORTED)
        self.assertEqual(descriptor.authorization_state, AuthorizationState.MISSING)


# ENG-04 acceptance: "PENDING 與 UNKNOWN 可區分"
class PendingVersusUnknownTest(unittest.TestCase):
    def test_normal_submission_is_pending_lost_response_is_unknown(self) -> None:
        ota = OtaDelayedPublicationMock()

        pending = ota.submit_publication(
            fixtures.TENANT_ID,
            "publication.update:offer-pending-01",
            fixtures.OTA_CHANNEL_ACCEPTING,
            fixtures.OTA_SERVICE_VERSION,
            fixtures.FIXED_NOW,
        )
        unknown = ota.submit_publication(
            fixtures.TENANT_ID,
            "publication.update:offer-lost-01",
            fixtures.OTA_CHANNEL_ACCEPTING,
            fixtures.OTA_SERVICE_VERSION,
            fixtures.FIXED_NOW,
            simulate_response_lost=True,
        )

        self.assertIsInstance(pending, Pending)
        self.assertIsInstance(unknown, Unknown)
        self.assertNotIsInstance(pending, Unknown)
        self.assertNotIsInstance(unknown, Pending)
        self.assertTrue(hasattr(pending, "pending_reason"))
        self.assertFalse(hasattr(unknown, "pending_reason"))
        self.assertTrue(hasattr(unknown, "reason_code"))
        self.assertFalse(hasattr(pending, "reason_code"))
        # PENDING always carries an external_reference already; UNKNOWN's
        # caller-visible reference may be absent even though the backend
        # already created one (see the response-lost test below).
        self.assertIsNotNone(pending.external_reference)


# ENG-04 acceptance: "查核回 SUCCEEDED 或 FAILED 均有收尾"
class ReconciliationClosureTest(unittest.TestCase):
    def _submitted(self, business_key: str) -> OtaDelayedPublicationMock:
        ota = OtaDelayedPublicationMock()
        ota.submit_publication(
            fixtures.TENANT_ID, business_key, fixtures.OTA_CHANNEL_ACCEPTING, fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW
        )
        return ota

    def test_succeeded_reconcile_has_evidence_and_closes_the_pending_result(self) -> None:
        business_key = "publication.update:offer-succeed-01"
        ota = self._submitted(business_key)
        ota.advance_review(business_key, "LIVE_VERIFIED")

        result = ota.reconcile(fixtures.TENANT_ID, business_key, fixtures.FIXED_NOW)

        self.assertIsInstance(result, Succeeded)
        self.assertTrue(result.evidence_refs)
        stored = ota._store.get(fixtures.TENANT_ID, "mock-ota-account", "sandbox", "publication.update", business_key)
        self.assertIsInstance(stored.result, Succeeded)

    def test_failed_reconcile_has_evidence_and_not_applied_disposition(self) -> None:
        business_key = "publication.update:offer-reject-01"
        ota = self._submitted(business_key)
        ota.advance_review(business_key, "REJECTED")

        result = ota.reconcile(fixtures.TENANT_ID, business_key, fixtures.FIXED_NOW)

        self.assertIsInstance(result, Failed)
        self.assertTrue(result.evidence_refs)
        self.assertEqual(result.side_effect_disposition, SideEffectDisposition.NOT_APPLIED)
        stored = ota._store.get(fixtures.TENANT_ID, "mock-ota-account", "sandbox", "publication.update", business_key)
        self.assertIsInstance(stored.result, Failed)


# ENG-04 acceptance: "同 key 不重複建立外部資源"
class DuplicateDispatchIsRejectedTest(unittest.TestCase):
    def test_experience_booking_retried_with_same_key_returns_same_reference(self) -> None:
        exp = ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS))
        business_key = "booking.create:case-exp-001"

        first = exp.create_booking(fixtures.TENANT_ID, business_key, "sess-city-tour-0900", 2, fixtures.FIXED_NOW)
        second = exp.create_booking(fixtures.TENANT_ID, business_key, "sess-city-tour-0900", 2, fixtures.FIXED_NOW)

        self.assertIsInstance(first, Succeeded)
        self.assertEqual(first.external_reference, second.external_reference)
        # Only one seat block was ever applied, not two.
        self.assertEqual(exp._booked["sess-city-tour-0900"], 2)

    def test_pms_booking_retried_with_same_key_returns_same_reference(self) -> None:
        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))
        business_key = "booking.create:case-pms-001"

        first = pms.create_booking(
            fixtures.TENANT_ID, business_key, "room-101", fixtures.PMS_AVAILABLE_CHECK_IN, fixtures.PMS_AVAILABLE_CHECK_OUT, fixtures.FIXED_NOW
        )
        second = pms.create_booking(
            fixtures.TENANT_ID, business_key, "room-101", fixtures.PMS_AVAILABLE_CHECK_IN, fixtures.PMS_AVAILABLE_CHECK_OUT, fixtures.FIXED_NOW
        )

        self.assertIsInstance(first, Succeeded)
        self.assertEqual(first.external_reference, second.external_reference)
        self.assertEqual(pms._booked[("room-101", fixtures.PMS_AVAILABLE_CHECK_IN)], 1)

    def test_ota_publication_retried_with_same_key_does_not_create_second_backend_record(self) -> None:
        ota = OtaDelayedPublicationMock()
        business_key = "publication.update:offer-dup-01"

        first = ota.submit_publication(
            fixtures.TENANT_ID, business_key, fixtures.OTA_CHANNEL_ACCEPTING, fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW
        )
        second = ota.submit_publication(
            fixtures.TENANT_ID, business_key, fixtures.OTA_CHANNEL_ACCEPTING, fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW
        )

        self.assertEqual(first.external_reference, second.external_reference)
        self.assertEqual(len(ota._backend), 1)

    def test_changed_payload_under_same_business_key_is_rejected_not_merged(self) -> None:
        exp = ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS))
        business_key = "booking.create:case-exp-002"
        exp.create_booking(fixtures.TENANT_ID, business_key, "sess-city-tour-0900", 1, fixtures.FIXED_NOW)

        with self.assertRaises(BusinessKeyConflictError):
            exp.create_booking(fixtures.TENANT_ID, business_key, "sess-city-tour-0900", 2, fixtures.FIXED_NOW)

    def test_capacity_exceeded_is_failed_not_applied_and_also_deduplicated(self) -> None:
        exp = ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS))
        business_key = "booking.create:case-exp-003"

        first = exp.create_booking(fixtures.TENANT_ID, business_key, "sess-sold-out-1400", 1, fixtures.FIXED_NOW)
        second = exp.create_booking(fixtures.TENANT_ID, business_key, "sess-sold-out-1400", 1, fixtures.FIXED_NOW)

        self.assertIsInstance(first, Failed)
        self.assertEqual(first.code, "SESSION_CAPACITY_EXCEEDED")
        self.assertEqual(first.side_effect_disposition, SideEffectDisposition.NOT_APPLIED)
        # Retrying a rejected attempt under the same key must not re-run
        # the capacity check and must not flip the outcome.
        self.assertIsInstance(second, Failed)
        self.assertEqual(first.code, second.code)
        self.assertEqual(exp._booked["sess-sold-out-1400"], 0)


# ENG-04 acceptance: "外部成功後本地逾時仍可查回同一結果"
class ResponseLostThenReconcileSameResourceTest(unittest.TestCase):
    def test_lost_response_reconciles_to_the_resource_already_created(self) -> None:
        ota = OtaDelayedPublicationMock()
        business_key = "publication.update:offer-lost-then-found-01"

        lost = ota.submit_publication(
            fixtures.TENANT_ID,
            business_key,
            fixtures.OTA_CHANNEL_ACCEPTING,
            fixtures.OTA_SERVICE_VERSION,
            fixtures.FIXED_NOW,
            simulate_response_lost=True,
        )
        self.assertIsInstance(lost, Unknown)
        # The backend already has exactly one record even though the
        # caller only saw UNKNOWN.
        self.assertEqual(len(ota._backend), 1)
        created_reference = ota._backend[business_key].external_reference

        ota.advance_review(business_key, "LIVE_VERIFIED")
        reconciled = ota.reconcile(fixtures.TENANT_ID, business_key, fixtures.FIXED_NOW)

        self.assertIsInstance(reconciled, Succeeded)
        self.assertEqual(reconciled.external_reference, created_reference)
        self.assertEqual(len(ota._backend), 1)


# ENG-04 acceptance: "沒有任何真實服務 API 權限的預設"
class NoRealServiceCredentialsByDefaultTest(unittest.TestCase):
    FORBIDDEN_MODULES = {
        "requests",
        "httpx",
        "urllib.request",
        "socket",
        "http.client",
        "aiohttp",
        "os",
    }

    def _connector_source_files(self) -> list[Path]:
        connectors_dir = ROOT / "connectors"
        return sorted(connectors_dir.rglob("*.py"))

    def test_no_connector_module_imports_networking_or_environment(self) -> None:
        files = self._connector_source_files()
        self.assertGreater(len(files), 0)
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name for alias in node.names}
                elif isinstance(node, ast.ImportFrom):
                    names = {node.module} if node.module else set()
                else:
                    continue
                offending = names & self.FORBIDDEN_MODULES
                self.assertFalse(
                    offending,
                    f"{path.relative_to(ROOT)} imports {offending}, which would let a mock reach a real "
                    f"service or read real credentials from the environment",
                )

    def test_capability_verification_defaults_to_production_disabled(self) -> None:
        mocks: list[Connector] = [
            ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS)),
            PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY)),
            OtaDelayedPublicationMock(),
        ]
        for mock in mocks:
            for capability_key, descriptor in mock._capabilities.items():
                self.assertIsNone(
                    descriptor.verification,
                    f"{type(mock).__name__}.{capability_key} must not carry a pre-filled "
                    f"CapabilityVerification; no account has been verified by default",
                )

    def test_ensure_capability_rejects_read_write_mismatch(self) -> None:
        # SD-C-10: a declared READ lookup must never be reused as a WRITE.
        exp = ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS))
        with self.assertRaises(CapabilityUnavailableError):
            exp.ensure_capability("availability.read", SideEffect.WRITE)


if __name__ == "__main__":
    unittest.main()
