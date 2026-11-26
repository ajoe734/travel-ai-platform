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
from datetime import date
from pathlib import Path

from connectors import fixtures
from connectors.base import Connector
from connectors.errors import BusinessKeyConflictError, CapabilityUnavailableError
from connectors.mocks.experience_reservation import ExperienceReservationMock
from connectors.mocks.ota_delayed_publication import OtaDelayedPublicationMock, _reconciliation_token
from connectors.mocks.pms_nightly import PmsNightlyMock
from connectors.types import (
    AuthorizationState,
    CapabilityDescriptor,
    ConnectorMode,
    Failed,
    MerchantConsentState,
    OperationalAvailability,
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
    def _submitted(self, business_key: str) -> tuple[OtaDelayedPublicationMock, str]:
        ota = OtaDelayedPublicationMock()
        submission = ota.submit_publication(
            fixtures.TENANT_ID, business_key, fixtures.OTA_CHANNEL_ACCEPTING, fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW
        )
        return ota, submission.reconciliation_token

    def test_succeeded_reconcile_has_evidence_and_closes_the_pending_result(self) -> None:
        business_key = "publication.update:offer-succeed-01"
        ota, token = self._submitted(business_key)
        ota.advance_review(fixtures.TENANT_ID, business_key, "LIVE_VERIFIED")

        result = ota.reconcile(fixtures.TENANT_ID, business_key, token, fixtures.FIXED_NOW)

        self.assertIsInstance(result, Succeeded)
        self.assertTrue(result.evidence_refs)
        stored = ota._store.get(fixtures.TENANT_ID, "mock-ota-account", "sandbox", "publication.update", business_key)
        self.assertIsInstance(stored.result, Succeeded)

    def test_failed_reconcile_has_evidence_and_not_applied_disposition(self) -> None:
        business_key = "publication.update:offer-reject-01"
        ota, token = self._submitted(business_key)
        ota.advance_review(fixtures.TENANT_ID, business_key, "REJECTED")

        result = ota.reconcile(fixtures.TENANT_ID, business_key, token, fixtures.FIXED_NOW)

        self.assertIsInstance(result, Failed)
        self.assertTrue(result.evidence_refs)
        self.assertEqual(result.side_effect_disposition, SideEffectDisposition.NOT_APPLIED)
        stored = ota._store.get(fixtures.TENANT_ID, "mock-ota-account", "sandbox", "publication.update", business_key)
        self.assertIsInstance(stored.result, Failed)

    def test_reconcile_with_mismatched_token_is_rejected(self) -> None:
        business_key = "publication.update:offer-badtoken-01"
        ota, _token = self._submitted(business_key)
        with self.assertRaises(ValueError):
            ota.reconcile(fixtures.TENANT_ID, business_key, "recon-wrong-token", fixtures.FIXED_NOW)

    # SD-C-03: a lookup miss by itself must become UNKNOWN, never a crash,
    # a release or a redo.
    def test_reconcile_lookup_miss_returns_unknown_not_a_crash(self) -> None:
        ota = OtaDelayedPublicationMock()
        business_key = "publication.update:offer-never-submitted-01"
        token = _reconciliation_token(fixtures.TENANT_ID, business_key)

        result = ota.reconcile(fixtures.TENANT_ID, business_key, token, fixtures.FIXED_NOW)

        self.assertIsInstance(result, Unknown)
        self.assertEqual(result.reason_code, "NOT_FOUND_RETRY")
        self.assertEqual(result.reconciliation_token, token)
        self.assertEqual(len(ota._backend), 0)


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
        created_reference = ota._backend[(fixtures.TENANT_ID, business_key)].external_reference

        ota.advance_review(fixtures.TENANT_ID, business_key, "LIVE_VERIFIED")
        reconciled = ota.reconcile(fixtures.TENANT_ID, business_key, lost.reconciliation_token, fixtures.FIXED_NOW)

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


# R1 remediation F1: cross-tenant isolation. Reproduces the reviewer's
# repro (TENANT_ID then OTHER_TENANT_ID submitting the SAME business_key
# on one shared mock instance) and asserts neither tenant's record,
# external_reference or reconciliation_token is visible to, or overwritten
# by, the other.
class CrossTenantIsolationTest(unittest.TestCase):
    def test_ota_other_tenant_does_not_overwrite_first_tenants_submission(self) -> None:
        ota = OtaDelayedPublicationMock()
        business_key = "publication.update:offer-shared-key-01"

        first = ota.submit_publication(
            fixtures.TENANT_ID, business_key, fixtures.OTA_CHANNEL_ACCEPTING, fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW
        )
        second = ota.submit_publication(
            fixtures.OTHER_TENANT_ID,
            business_key,
            fixtures.OTA_CHANNEL_OTHER,
            fixtures.OTA_SERVICE_VERSION_OTHER,
            fixtures.FIXED_NOW,
        )

        # Two independent backend rows, not one overwriting the other.
        self.assertEqual(len(ota._backend), 2)
        self.assertNotEqual(first.external_reference, second.external_reference)
        self.assertNotEqual(first.reconciliation_token, second.reconciliation_token)

        first_tenant_record = ota._backend[(fixtures.TENANT_ID, business_key)]
        other_tenant_record = ota._backend[(fixtures.OTHER_TENANT_ID, business_key)]
        self.assertEqual(first_tenant_record.channel, fixtures.OTA_CHANNEL_ACCEPTING)
        self.assertEqual(other_tenant_record.channel, fixtures.OTA_CHANNEL_OTHER)
        self.assertEqual(first_tenant_record.service_version, fixtures.OTA_SERVICE_VERSION)
        self.assertEqual(other_tenant_record.service_version, fixtures.OTA_SERVICE_VERSION_OTHER)

        # advance_review/reconcile for one tenant must not touch the other.
        ota.advance_review(fixtures.OTHER_TENANT_ID, business_key, "LIVE_VERIFIED")
        reconciled_first = ota.reconcile(fixtures.TENANT_ID, business_key, first.reconciliation_token, fixtures.FIXED_NOW)
        self.assertIsInstance(reconciled_first, Pending)
        self.assertEqual(reconciled_first.external_reference, first.external_reference)
        first_tenant_record_after = ota._backend[(fixtures.TENANT_ID, business_key)]
        self.assertEqual(first_tenant_record_after.status, "SUBMITTED")
        self.assertEqual(first_tenant_record_after.channel, fixtures.OTA_CHANNEL_ACCEPTING)

    def test_ota_reconcile_with_other_tenants_token_is_rejected(self) -> None:
        ota = OtaDelayedPublicationMock()
        business_key = "publication.update:offer-shared-key-02"
        ota.submit_publication(
            fixtures.TENANT_ID, business_key, fixtures.OTA_CHANNEL_ACCEPTING, fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW
        )
        other = ota.submit_publication(
            fixtures.OTHER_TENANT_ID,
            business_key,
            fixtures.OTA_CHANNEL_OTHER,
            fixtures.OTA_SERVICE_VERSION_OTHER,
            fixtures.FIXED_NOW,
        )

        with self.assertRaises(ValueError):
            ota.reconcile(fixtures.TENANT_ID, business_key, other.reconciliation_token, fixtures.FIXED_NOW)

    def test_ota_advance_review_does_not_cross_tenants(self) -> None:
        ota = OtaDelayedPublicationMock()
        business_key = "publication.update:offer-shared-key-03"
        ota.submit_publication(
            fixtures.OTHER_TENANT_ID,
            business_key,
            fixtures.OTA_CHANNEL_OTHER,
            fixtures.OTA_SERVICE_VERSION_OTHER,
            fixtures.FIXED_NOW,
        )
        # TENANT_ID never submitted this business_key; advancing it must
        # not find OTHER_TENANT_ID's record.
        with self.assertRaises(KeyError):
            ota.advance_review(fixtures.TENANT_ID, business_key, "LIVE_VERIFIED")

    def test_experience_and_pms_external_reference_is_tenant_scoped(self) -> None:
        exp = ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS))
        business_key = "booking.create:case-exp-shared-01"
        first = exp.create_booking(fixtures.TENANT_ID, business_key, "sess-city-tour-0900", 1, fixtures.FIXED_NOW)
        second = exp.create_booking(fixtures.OTHER_TENANT_ID, business_key, "sess-city-tour-0900", 1, fixtures.FIXED_NOW)
        self.assertIsInstance(first, Succeeded)
        self.assertIsInstance(second, Succeeded)
        self.assertNotEqual(first.external_reference, second.external_reference)
        self.assertIn(fixtures.TENANT_ID, first.external_reference)
        self.assertIn(fixtures.OTHER_TENANT_ID, second.external_reference)

        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))
        pms_business_key = "booking.create:case-pms-shared-01"
        pms_first = pms.create_booking(
            fixtures.TENANT_ID, pms_business_key, "room-101", fixtures.PMS_AVAILABLE_CHECK_IN, fixtures.PMS_AVAILABLE_CHECK_OUT, fixtures.FIXED_NOW
        )
        self.assertIsInstance(pms_first, Succeeded)
        self.assertIn(fixtures.TENANT_ID, pms_first.external_reference)


# R1 remediation F2(a): technical capability, platform authorization,
# merchant consent and operational availability are four independent
# dimensions (AGENTS.md); any one of them failing must block is_callable()
# and ensure_capability(), not just authorization_state/support.
class CapabilityGateDimensionsTest(unittest.TestCase):
    def _descriptor(self, **overrides) -> CapabilityDescriptor:
        base = dict(
            capability_key="probe.capability",
            support=SupportLevel.SUPPORTED,
            authorization_state=AuthorizationState.ACTIVE,
            merchant_consent=MerchantConsentState.GRANTED,
            operational_availability=OperationalAvailability.AVAILABLE,
            mode=ConnectorMode.SYNC,
            inventory_model="TIMESLOT",
            side_effect=SideEffect.WRITE,
        )
        base.update(overrides)
        return CapabilityDescriptor(**base)

    def test_fully_granted_descriptor_is_callable(self) -> None:
        self.assertTrue(self._descriptor().is_callable())

    def test_unverified_support_blocks_is_callable(self) -> None:
        self.assertFalse(self._descriptor(support=SupportLevel.UNVERIFIED).is_callable())

    def test_expired_authorization_blocks_is_callable(self) -> None:
        self.assertFalse(self._descriptor(authorization_state=AuthorizationState.EXPIRED).is_callable())

    def test_revoked_authorization_blocks_is_callable(self) -> None:
        self.assertFalse(self._descriptor(authorization_state=AuthorizationState.REVOKED).is_callable())

    def test_missing_merchant_consent_blocks_is_callable(self) -> None:
        self.assertFalse(self._descriptor(merchant_consent=MerchantConsentState.MISSING).is_callable())

    def test_withdrawn_merchant_consent_blocks_is_callable(self) -> None:
        self.assertFalse(self._descriptor(merchant_consent=MerchantConsentState.WITHDRAWN).is_callable())

    def test_unavailable_operational_availability_blocks_is_callable(self) -> None:
        self.assertFalse(
            self._descriptor(operational_availability=OperationalAvailability.UNAVAILABLE).is_callable()
        )

    def test_degraded_operational_availability_blocks_is_callable(self) -> None:
        self.assertFalse(self._descriptor(operational_availability=OperationalAvailability.DEGRADED).is_callable())

    def test_ensure_capability_rejects_each_blocking_dimension(self) -> None:
        for overrides in (
            {"support": SupportLevel.UNVERIFIED},
            {"authorization_state": AuthorizationState.EXPIRED},
            {"authorization_state": AuthorizationState.REVOKED},
            {"merchant_consent": MerchantConsentState.MISSING},
            {"merchant_consent": MerchantConsentState.WITHDRAWN},
            {"operational_availability": OperationalAvailability.UNAVAILABLE},
            {"operational_availability": OperationalAvailability.DEGRADED},
        ):
            with self.subTest(overrides=overrides):
                connector = Connector({"probe.capability": self._descriptor(**overrides)})
                with self.assertRaises(CapabilityUnavailableError):
                    connector.ensure_capability("probe.capability", SideEffect.WRITE)


# R1 remediation F3(a): local validation must reject nonsensical requests
# before they reach the capacity/date logic, instead of the capacity
# check silently treating them as always-satisfiable.
class MockInputValidationTest(unittest.TestCase):
    def test_experience_booking_rejects_non_positive_party_size(self) -> None:
        exp = ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS))
        with self.assertRaises(ValueError):
            exp.create_booking(fixtures.TENANT_ID, "booking.create:case-exp-neg-01", "sess-city-tour-0900", -5, fixtures.FIXED_NOW)

    def test_experience_booking_rejects_zero_party_size_on_unknown_session(self) -> None:
        exp = ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS))
        with self.assertRaises(ValueError):
            exp.create_booking(fixtures.TENANT_ID, "booking.create:case-exp-zero-01", "sess-does-not-exist", 0, fixtures.FIXED_NOW)

    def test_pms_booking_rejects_reversed_date_range(self) -> None:
        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))
        with self.assertRaises(ValueError):
            pms.create_booking(
                fixtures.TENANT_ID, "booking.create:case-pms-reversed-01", "room-101", date(2026, 12, 22), date(2026, 12, 20), fixtures.FIXED_NOW
            )

    def test_pms_booking_rejects_equal_check_in_and_check_out(self) -> None:
        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))
        with self.assertRaises(ValueError):
            pms.create_booking(
                fixtures.TENANT_ID, "booking.create:case-pms-sameday-01", "room-101", date(2026, 12, 24), date(2026, 12, 24), fixtures.FIXED_NOW
            )


# R1 remediation F3(b)/(c): the declared availability.read/booking.lookup
# capabilities must have a real method behind them, and the resulting
# ROOM_NIGHT_SOLD_OUT path must be exercised directly (not only inferred
# from the DuplicateDispatchIsRejectedTest capacity case).
class DeclaredReadCapabilitiesHaveMethodsTest(unittest.TestCase):
    def test_experience_query_availability_reports_capacity_and_booked(self) -> None:
        exp = ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS))
        exp.create_booking(fixtures.TENANT_ID, "booking.create:case-exp-avail-01", "sess-city-tour-0900", 1, fixtures.FIXED_NOW)

        availability = exp.query_availability("sess-city-tour-0900")

        self.assertEqual(availability["capacity"], fixtures.EXPERIENCE_SESSIONS["sess-city-tour-0900"])
        self.assertEqual(availability["booked"], 1)

    def test_experience_lookup_booking_returns_the_dispatched_result(self) -> None:
        exp = ExperienceReservationMock(dict(fixtures.EXPERIENCE_SESSIONS))
        business_key = "booking.create:case-exp-lookup-01"
        created = exp.create_booking(fixtures.TENANT_ID, business_key, "sess-city-tour-0900", 1, fixtures.FIXED_NOW)

        looked_up = exp.lookup_booking(fixtures.TENANT_ID, business_key)

        self.assertIsInstance(looked_up, Succeeded)
        self.assertEqual(looked_up.external_reference, created.external_reference)

    def test_pms_query_availability_reflects_capacity_and_the_sold_out_night(self) -> None:
        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))

        availability = pms.query_availability("room-101", fixtures.PMS_AVAILABLE_CHECK_IN, date(2026, 12, 25))

        self.assertEqual(availability[date(2026, 12, 20)], 1)
        self.assertEqual(availability[date(2026, 12, 24)], 0)

    def test_pms_create_booking_over_a_sold_out_night_is_room_night_sold_out(self) -> None:
        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))

        result = pms.create_booking(
            fixtures.TENANT_ID,
            "booking.create:case-pms-soldout-01",
            "room-101",
            fixtures.PMS_SOLD_OUT_CHECK_IN,
            fixtures.PMS_SOLD_OUT_CHECK_OUT,
            fixtures.FIXED_NOW,
        )

        self.assertIsInstance(result, Failed)
        self.assertEqual(result.code, "ROOM_NIGHT_SOLD_OUT")
        self.assertEqual(result.side_effect_disposition, SideEffectDisposition.NOT_APPLIED)

    def test_pms_lookup_booking_returns_the_dispatched_result(self) -> None:
        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))
        business_key = "booking.create:case-pms-lookup-01"
        created = pms.create_booking(
            fixtures.TENANT_ID, business_key, "room-101", fixtures.PMS_AVAILABLE_CHECK_IN, fixtures.PMS_AVAILABLE_CHECK_OUT, fixtures.FIXED_NOW
        )

        looked_up = pms.lookup_booking(fixtures.TENANT_ID, business_key)

        self.assertIsInstance(looked_up, Succeeded)
        self.assertEqual(looked_up.external_reference, created.external_reference)

    def test_pms_lookup_booking_unknown_key_raises(self) -> None:
        pms = PmsNightlyMock(dict(fixtures.PMS_ROOM_NIGHT_CAPACITY))
        with self.assertRaises(KeyError):
            pms.lookup_booking(fixtures.TENANT_ID, "booking.create:case-pms-never-made-01")


# R1 remediation F3(c) / SD-C-08: "A發布成功、B審核、C拒絕；各自狀態；重試C不
# 再送A/B". Three channels for the same offer, each with its own
# business_key (SD §8), reach three different terminal/non-terminal states
# independently, and retrying one never touches the others.
class MultiChannelPartialPublicationResultsTest(unittest.TestCase):
    def test_three_channels_resolve_independently(self) -> None:
        ota = OtaDelayedPublicationMock()
        key_a, key_b, key_c = (
            "publication.update:offer-42-ota-a",
            "publication.update:offer-42-ota-b",
            "publication.update:offer-42-ota-c",
        )

        submission_a = ota.submit_publication(fixtures.TENANT_ID, key_a, "ota-channel-a", "1", fixtures.FIXED_NOW)
        submission_b = ota.submit_publication(fixtures.TENANT_ID, key_b, "ota-channel-b", "1", fixtures.FIXED_NOW)
        submission_c = ota.submit_publication(fixtures.TENANT_ID, key_c, "ota-channel-c", "1", fixtures.FIXED_NOW)
        self.assertIsInstance(submission_a, Pending)
        self.assertIsInstance(submission_b, Pending)
        self.assertIsInstance(submission_c, Pending)

        ota.advance_review(fixtures.TENANT_ID, key_a, "LIVE_VERIFIED")
        ota.advance_review(fixtures.TENANT_ID, key_c, "REJECTED")
        # key_b is left SUBMITTED/PENDING: still under review.

        result_a = ota.reconcile(fixtures.TENANT_ID, key_a, submission_a.reconciliation_token, fixtures.FIXED_NOW)
        result_b = ota.reconcile(fixtures.TENANT_ID, key_b, submission_b.reconciliation_token, fixtures.FIXED_NOW)
        result_c = ota.reconcile(fixtures.TENANT_ID, key_c, submission_c.reconciliation_token, fixtures.FIXED_NOW)

        self.assertIsInstance(result_a, Succeeded)
        self.assertIsInstance(result_b, Pending)
        self.assertIsInstance(result_c, Failed)

        # Retrying the rejected channel C again must not flip or touch A/B.
        retry_c = ota.reconcile(fixtures.TENANT_ID, key_c, submission_c.reconciliation_token, fixtures.FIXED_NOW)
        self.assertIsInstance(retry_c, Failed)
        self.assertEqual(ota._backend[(fixtures.TENANT_ID, key_a)].status, "LIVE_VERIFIED")
        self.assertEqual(ota._backend[(fixtures.TENANT_ID, key_b)].status, "SUBMITTED")
        self.assertEqual(ota._backend[(fixtures.TENANT_ID, key_c)].status, "REJECTED")


if __name__ == "__main__":
    unittest.main()
