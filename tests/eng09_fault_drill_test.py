"""ENG-09 recovery drills exercise the real mock connector contract boundary."""
from __future__ import annotations

import unittest

from connectors import fixtures
from connectors.mocks.ota_delayed_publication import OtaDelayedPublicationMock
from connectors.types import Succeeded, Unknown


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
