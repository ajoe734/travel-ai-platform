#!/usr/bin/env python3
"""Formal publication-command boundary tests for ENG-08."""
from __future__ import annotations
import unittest
from connectors.mocks.ota_delayed_publication import OtaDelayedPublicationMock
from connectors.mocks.pms_nightly import PmsNightlyMock
from connectors.types import Failed, Pending, Succeeded, SideEffectDisposition
from services.publication.service import PublicationService

class _Repo:
    def __init__(self): self.row={"revision":1,"desired_version":2,"status":"NOT_STARTED"}; self.saved=[]

class ResultSafetyTest(unittest.TestCase):
    def test_matching_formal_readback_marks_only_that_publication_live(self):
        """A website readback is recorded against its own publication ID only."""
        from unittest.mock import patch

        svc = PublicationService()
        website = {"revision": 1, "desired_version": 2, "status": "NOT_STARTED"}
        with patch("services.publication.service.publications.get_publication", return_value=website), patch(
            "services.publication.service.publications.observe_publication",
            side_effect=lambda _conn, **kw: kw,
        ) as observe:
            row = svc.record_connector_result(
                None,
                tenant_id="t",
                publication_id="website-publication",
                expected_revision=1,
                result=Succeeded(
                    external_reference="website-listing",
                    data={},
                    evidence_refs=("evidence-1",),
                    observed_at="2026-11-27T00:00:00Z",
                    source_revision="2",
                ),
                now="2026-11-27T00:00:00Z",
            )
        self.assertEqual(row["status"], "LIVE")
        self.assertEqual(observe.call_args.kwargs["publication_id"], "website-publication")
        self.assertEqual(observe.call_args.kwargs["observed_version"], 2)

    def test_source_revision_must_match_before_live(self):
        # Exercises the real method with only the repository boundary replaced;
        # the connector result type is the ENG-04 SDK type.
        from unittest.mock import patch
        repo=_Repo(); svc=PublicationService()
        with patch("services.publication.service.publications.get_publication", return_value=repo.row), patch("services.publication.service.publications.observe_publication", side_effect=lambda _conn, **kw: kw) as observe:
            row=svc.record_connector_result(None, tenant_id="t", publication_id="p", expected_revision=1,
                result=Succeeded(external_reference="x", data={}, evidence_refs=("evidence-1",), observed_at="2026-11-27T00:00:00Z", source_revision="1"), now="2026-11-27T00:00:00Z")
        self.assertEqual(row, repo.row)
        observe.assert_not_called()

    def test_stale_readback_does_not_brick_new_version_then_matching_readback_lives(self):
        """Round-2 F3 probe: old v1 evidence cannot terminally fail desired v2."""
        from unittest.mock import patch
        current = {"revision": 1, "desired_version": 2, "status": "PENDING", "external_reference": "ota-2"}
        svc = PublicationService()
        stale = Succeeded("ota-2", {}, ("old-evidence",), "2026-11-27T00:00:00Z", source_revision="1")
        fresh = Succeeded("ota-2", {}, ("new-evidence",), "2026-11-27T00:00:01Z", source_revision="2")
        with patch("services.publication.service.publications.get_publication", return_value=current), patch(
            "services.publication.service.publications.observe_publication", side_effect=lambda _conn, **kw: kw
        ) as observe:
            self.assertEqual(svc.record_connector_result(None, tenant_id="t", publication_id="p", expected_revision=1, result=stale, now="now"), current)
            saved = svc.record_connector_result(None, tenant_id="t", publication_id="p", expected_revision=1, result=fresh, now="now")
        self.assertEqual(saved["status"], "LIVE")
        self.assertEqual(observe.call_count, 1)

    def test_rejected_ota_reconcile_maps_failed_without_missing_external_reference(self):
        """Round-2 F2 probe: Failed intentionally has no external_reference field."""
        from unittest.mock import patch
        ota = OtaDelayedPublicationMock()
        dispatch = ota.submit_publication("tenant-a", "publication:1", "ota", "2", "2026-11-27T00:00:00Z")
        ota.advance_review("tenant-a", "publication:1", "REJECTED")
        rejected = ota.reconcile("tenant-a", "publication:1", dispatch.reconciliation_token, "2026-11-27T00:01:00Z")
        self.assertIsInstance(rejected, Failed)
        current = {"revision": 2, "desired_version": 2, "status": "PENDING", "external_reference": dispatch.external_reference}
        with patch("services.publication.service.publications.get_publication", return_value=current), patch(
            "services.publication.service.publications.observe_publication", side_effect=lambda _conn, **kw: kw
        ):
            saved = PublicationService().record_connector_result(None, tenant_id="tenant-a", publication_id="p", expected_revision=2, result=rejected, now="now")
        self.assertEqual(saved["status"], "FAILED")
        self.assertIn("rejected", saved["failure_reason"])

    def test_unknown_preserves_optional_external_reference(self):
        from unittest.mock import patch
        from connectors.types import Unknown
        current = {"revision": 1, "desired_version": 2, "status": "PENDING", "external_reference": "ota-2"}
        unknown = Unknown("recon", "NETWORK", "evidence", "now", external_reference="ota-2")
        with patch("services.publication.service.publications.get_publication", return_value=current), patch(
            "services.publication.service.publications.observe_publication", side_effect=lambda _conn, **kw: kw
        ):
            saved = PublicationService().record_connector_result(None, tenant_id="t", publication_id="p", expected_revision=1, result=unknown, now="now")
        self.assertEqual(saved["status"], "UNKNOWN")
        self.assertEqual(saved["external_reference"], "ota-2")

    def test_known_pending_is_not_unknown(self):
        from unittest.mock import patch
        svc=PublicationService(); row={"revision":1,"desired_version":2,"status":"NOT_STARTED"}
        with patch("services.publication.service.publications.get_publication", return_value=row), patch("services.publication.service.publications.observe_publication", side_effect=lambda _conn, **kw: kw):
            stored=svc.record_connector_result(None, tenant_id="t", publication_id="p", expected_revision=1,
                result=Pending(external_reference="x", reconciliation_token="r", pending_reason="REVIEW", evidence_refs=("evidence-1",), observed_at="2026-11-27T00:00:00Z"), now="2026-11-27T00:00:00Z")
        self.assertEqual(stored["status"], "PENDING")


class PublicationPreparationTest(unittest.TestCase):
    def test_disabled_channel_is_blocked_without_a_dispatch_intent(self):
        """Missing/disabled access is actionable locally, not a connector call."""
        from unittest.mock import patch

        next_id = iter(("website-publication", "ota-publication"))

        def create(_conn, **kwargs):
            return {"id": kwargs["publication_id"], "revision": 1, "status": "NOT_STARTED"}

        def access(_conn, **kwargs):
            if kwargs["channel"] == "website":
                return {"publication_enabled": True, "reason": None}
            return {"publication_enabled": False, "reason": "CHANNEL_AUTHORIZATION_EXPIRED"}

        def observe(_conn, **kwargs):
            return kwargs

        svc = PublicationService()
        with patch(
            "services.publication.service.uuid.uuid4", side_effect=next_id
        ), patch(
            "services.publication.service.publications.create_publication", side_effect=create
        ), patch(
            "services.publication.service.publications.get_channel_access", side_effect=access
        ), patch(
            "services.publication.service.publications.observe_publication", side_effect=observe
        ) as record_block:
            intents, blocked = svc.prepare_publications(
                None,
                tenant_id="t",
                service_version_id="version-1",
                service_version=2,
                targets=[
                    {"channel": "website", "connector_account_id": "web", "environment": "MOCK"},
                    {"channel": "ota", "connector_account_id": "ota-a", "environment": "MOCK"},
                ],
            )
        self.assertEqual([intent.channel for intent in intents], ["website"])
        self.assertEqual(intents[0].publication_id, "website-publication")
        self.assertEqual(blocked[0]["status"], "BLOCKED")
        self.assertEqual(blocked[0]["failure_reason"], "CHANNEL_AUTHORIZATION_EXPIRED")
        self.assertEqual(record_block.call_args.kwargs["publication_id"], "ota-publication")

    def test_unsupported_pms_is_blocked_before_dispatch(self):
        from unittest.mock import patch
        pms = PmsNightlyMock({})
        publication = {"id": "pms-publication", "revision": 1, "status": "NOT_STARTED"}
        with patch("services.publication.service.uuid.uuid4", return_value="pms-publication"), patch(
            "services.publication.service.publications.create_publication", return_value=publication
        ), patch("services.publication.service.publications.get_channel_access", return_value={"publication_enabled": True, "reason": None}), patch(
            "services.publication.service.publications.observe_publication", side_effect=lambda _conn, **kw: kw
        ):
            intents, blocked = PublicationService().prepare_publications(None, tenant_id="t", service_version_id="v", service_version=2,
                targets=[{"channel": "pms", "connector_account_id": "pms", "environment": "MOCK"}],
                connectors={("pms", "pms", "MOCK"): pms})
        self.assertEqual(intents, [])
        self.assertEqual(blocked[0]["status"], "BLOCKED")
        self.assertEqual(pms.publication_call_count, 0)

if __name__ == "__main__": unittest.main()
