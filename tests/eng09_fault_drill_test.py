"""ENG-09 recovery drills exercise the real mock connector contract boundary."""
from __future__ import annotations

import unittest

from connectors import fixtures
from connectors.mocks.ota_delayed_publication import OtaDelayedPublicationMock
from connectors.types import Succeeded, Unknown
from services.authorization.errors import AuthorizationError
from services.authorization.repository import InMemoryAuthorizationRepository
from services.authorization.service import AuthorizationService


TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _actor(kind: str, actor_id: str) -> dict:
    return {"actor_kind": kind, "actor_id": actor_id}


def _ref(id_: str) -> dict:
    return {"tenant_id": TENANT, "id": id_}


def _revocable_authorization() -> tuple[AuthorizationService, dict, dict]:
    ids = iter(range(1, 20))
    service = AuthorizationService(InMemoryAuthorizationRepository(), id_factory=lambda: f"00000000-0000-4000-8000-{next(ids):012d}")
    decision, nonce = service.create_decision(
        tenant_id=TENANT, work_id=_ref("00000000-0000-4000-8000-000000000101"),
        decision_type="BOOKING_CONFIRMATION", options=[{"option_id": "accept", "description": "accept"}],
        display_payload={"schema_version": "1.0", "canonicalization_version": "travel-canonical-json-v1", "tenant_id": TENANT,
                         "purpose": "BOOKING", "target_type": "QUOTE", "target_id": _ref("00000000-0000-4000-8000-000000000102"),
                         "target_revision": 1, "work_id": _ref("00000000-0000-4000-8000-000000000101"), "operation": "booking.create",
                         "service_or_policy_version": "v1", "expires_at": "2026-12-01T00:00:00Z", "data_purpose": "booking",
                         "manifest_items": ["booking"], "customer_impact": "booking", "required_consent_refs": []},
        target_revision=1, expires_at="2026-12-01T00:00:00Z", requested_role="CUSTOMER", created_at="2026-11-01T00:00:00Z")
    approval = service.approve_decision(tenant_id=TENANT, decision_id=decision["id"], expected_revision=1, selected_option_id="accept", nonce_id=nonce,
        approved_by=_actor("CUSTOMER", "00000000-0000-4000-8000-000000000103"), verified_actor_ref="test", scope_manifest=[{"item_id": "booking", "operation": "booking.create"}],
        approved_at="2026-11-01T00:01:00Z", idempotency_key="fault-drill")
    authorization = service.issue_execution_authorization(tenant_id=TENANT, work_id=_ref("00000000-0000-4000-8000-000000000101"),
        root_business_key="booking:fault-drill", capabilities=["booking.create"], manifest=[{"item_id": "booking", "operation": "booking.create"}],
        approval_refs=[_ref(approval["id"])], issued_at="2026-11-01T00:01:00Z", now="2026-11-01T00:01:00Z")
    return service, approval, authorization


class RecoveryFaultDrillTest(unittest.TestCase):
    def test_unknown_timeout_recovers_by_read_only_reconcile_without_second_dispatch(self):
        connector = OtaDelayedPublicationMock()
        key = "publication.update:eng09-unknown-reconcile"
        first = connector.submit_publication(fixtures.TENANT_ID, key, fixtures.OTA_CHANNEL_ACCEPTING,
                                             fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW, simulate_response_lost=True)
        self.assertIsInstance(first, Unknown)
        self.assertEqual(len(connector._backend), 1)
        connector.advance_review(fixtures.TENANT_ID, key, "LIVE_VERIFIED")
        recovered = connector.reconcile(fixtures.TENANT_ID, key, first.reconciliation_token, fixtures.FIXED_NOW)
        self.assertIsInstance(recovered, Succeeded)
        self.assertEqual(len(connector._backend), 1, "recovery must not create a second external publication")

    def test_restore_before_local_success_uses_same_operation_reference(self):
        connector = OtaDelayedPublicationMock()
        key = "publication.update:eng09-restore-readback"
        submitted = connector.submit_publication(fixtures.TENANT_ID, key, fixtures.OTA_CHANNEL_ACCEPTING,
                                                 fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW)
        connector.advance_review(fixtures.TENANT_ID, key, "LIVE_VERIFIED")
        # This models local state restored before the terminal result write:
        # only persisted operation identity/token is supplied to the lookup.
        verified = connector.reconcile(fixtures.TENANT_ID, key, submitted.reconciliation_token, fixtures.FIXED_NOW)
        self.assertIsInstance(verified, Succeeded)
        self.assertEqual(verified.external_reference, submitted.external_reference)

    def test_revocation_blocks_an_undispatched_task_at_the_real_authorization_gate(self):
        service, approval, authorization = _revocable_authorization()
        result = service.revoke_approval(tenant_id=TENANT, approval_id=approval["id"], revoked_by=_actor("EMPLOYEE", "00000000-0000-4000-8000-000000000104"),
            reason="merchant withdrew", effective_at="2026-11-01T00:02:00Z", created_at="2026-11-01T00:02:01Z")
        self.assertEqual(result["affected_authorizations"], [{"authorization_id": authorization["id"], "outcome": "NOT_YET_DISPATCHED_BLOCKED"}])
        with self.assertRaisesRegex(AuthorizationError, "AUTHORIZATION_REVOKED"):
            service.precheck_before_dispatch(tenant_id=TENANT, authorization_id=authorization["id"], now="2026-11-01T00:03:00Z")

    def test_outbox_redelivery_retains_one_external_side_effect(self):
        connector = OtaDelayedPublicationMock()
        key = "publication.update:eng09-outbox-redelivery"
        first = connector.submit_publication(fixtures.TENANT_ID, key, fixtures.OTA_CHANNEL_ACCEPTING,
                                             fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW, simulate_response_lost=True)
        self.assertIsInstance(first, Unknown)
        # The publisher may redeliver an event ID, but the stable business key
        # reaches the real connector idempotency boundary rather than creating a second row.
        redelivery = connector.submit_publication(fixtures.TENANT_ID, key, fixtures.OTA_CHANNEL_ACCEPTING,
                                                  fixtures.OTA_SERVICE_VERSION, fixtures.FIXED_NOW, simulate_response_lost=True)
        self.assertIsInstance(redelivery, Unknown)
        self.assertEqual(len(connector._backend), 1)
