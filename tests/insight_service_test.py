from __future__ import annotations

import unittest
from unittest.mock import patch

from services.insights.service import InsightError, InsightService


class ObservationTests(unittest.TestCase):
    def test_observation_needs_fact_source_and_keeps_hypothesis_separate(self):
        svc = InsightService()
        with self.assertRaisesRegex(InsightError, "OBSERVED_FACT_SOURCE_REQUIRED"):
            svc.record_observation(None, tenant_id="t", case_id="c", query_version="v1", metric_key="quote-rate", period_start="2026-01-01T00:00:00Z", period_end="2026-01-02T00:00:00Z", numerator={}, denominator={}, coverage={}, case_dedupe_version="d1", observed_facts=[{"value": 2}], hypotheses=[], evidence_refs=[])
        with self.assertRaisesRegex(InsightError, "HYPOTHESIS_MUST_NOT_MASQUERADE_AS_FACT"):
            svc.record_observation(None, tenant_id="t", case_id="c", query_version="v1", metric_key="quote-rate", period_start="2026-01-01T00:00:00Z", period_end="2026-01-02T00:00:00Z", numerator={}, denominator={}, coverage={}, case_dedupe_version="d1", observed_facts=[{"source_ref": "query:1"}], hypotheses=[{"source_ref": "silence"}], evidence_refs=[])

    @patch("services.insights.service.repo.create_insight")
    def test_hash_binds_query_metadata_and_unknown_is_not_a_fact(self, create):
        create.return_value = {"id": "i"}
        InsightService().record_observation(None, tenant_id="t", case_id="c", query_version="v2", metric_key="lost-reason", period_start="2026-01-01T00:00:00Z", period_end="2026-01-02T00:00:00Z", numerator={"value": 1}, denominator={"value": 3}, coverage={"complete": False}, case_dedupe_version="case-v1", observed_facts=[{"source_ref": "message:explicit", "value": "time"}], hypotheses=[{"label": "silence is UNKNOWN"}], evidence_refs=[{"ref": "query-run:7"}], insight_id="i")
        self.assertEqual(create.call_args.kwargs["result_hash"], "f363ac87508a5d53ff2d125175ce45ab25878a7afbd8107afdec736e055c74c2")


class MaterialRequestTests(unittest.TestCase):
    @patch("services.insights.service.repo.create_material_request")
    @patch("services.insights.service.repo.find_usable_assets", return_value=[{"content_hash": "a", "purpose": "marketing", "channel": "website", "language": "zh"}])
    @patch("services.insights.service.repo.get_proposal", return_value={"required_material": [{"content_hash": "a", "purpose": "marketing", "channel": "website", "language": "zh"}, {"content_hash": "b", "purpose": "marketing", "channel": "ota", "language": "en"}]})
    def test_only_missing_material_is_requested(self, proposal, uses, create):
        missing = InsightService().ask_missing_material(None, tenant_id="t", proposal_id="p", requested_channels=["website"], deadline=None, now="2026-01-01T00:00:00Z", request_id="r")
        self.assertEqual(missing, [{"content_hash": "b", "purpose": "marketing", "channel": "ota", "language": "en"}])
        self.assertEqual(create.call_args.kwargs["required_items"], missing)

    @patch("services.insights.service.repo.create_material_request")
    @patch("services.insights.service.repo.find_usable_assets", return_value=[{"content_hash": "photo", "purpose": "marketing", "channel": "website", "language": "zh"}])
    @patch("services.insights.service.repo.get_proposal", return_value={"required_material": [{"requirement_id": "hero", "purpose": "marketing", "channel": "ota", "language": "zh"}]})
    def test_other_channel_asset_does_not_satisfy_material_requirement(self, proposal, assets, create):
        missing = InsightService().ask_missing_material(None, tenant_id="t", proposal_id="p", requested_channels=["ota"], deadline=None, now="2026-01-01T00:00:00Z")
        self.assertEqual(len(missing), 1)
        create.assert_called_once()


class AssetRightsTests(unittest.TestCase):
    @patch("services.insights.service.repo.asset_has_invalid_ancestor", return_value=False)
    @patch("services.insights.service.repo.get_asset", return_value={"source_scope": "COMPLAINT_EVIDENCE", "scan_status": "CHECKED", "lifecycle_status": "READY_FOR_REVIEW"})
    def test_complaint_attachment_never_becomes_marketing_asset(self, asset, ancestor):
        with self.assertRaisesRegex(InsightError, "COMPLAINT_ASSET_MARKETING_PROHIBITED"):
            InsightService().approve_rights(None, tenant_id="t", asset_id="a", rights_holder_ref="merchant", purposes=["marketing"], channels=["website"], languages=["zh"], effective_at="2026-01-01T00:00:00Z", expires_at=None, approval_ref="approval")

    @patch("services.insights.service.repo.asset_has_invalid_ancestor", return_value=False)
    @patch("services.insights.service.repo.set_asset_scan")
    @patch("services.insights.service.repo.next_rights_revision", return_value=2)
    @patch("services.insights.service.repo.create_rights_grant", return_value={"id": "g"})
    @patch("services.insights.service.repo.get_asset", return_value={"source_scope": "MERCHANT_SUBMITTED", "scan_status": "CHECKED", "lifecycle_status": "READY_FOR_REVIEW"})
    def test_explicit_scanned_asset_rights_are_required(self, asset, grant, revision, scan, ancestor):
        result = InsightService().approve_rights(None, tenant_id="t", asset_id="a", rights_holder_ref="merchant", purposes=["marketing"], channels=["website"], languages=["zh"], effective_at="2026-01-01T00:00:00Z", expires_at=None, approval_ref="approval", grant_id="g")
        self.assertEqual(result, {"id": "g"})
        self.assertEqual(scan.call_args.kwargs["lifecycle_status"], "AVAILABLE")
        self.assertEqual(grant.call_args.kwargs["revision"], 2)

    @patch("services.insights.service.repo.get_asset", return_value={"lifecycle_status": "REVOKED"})
    def test_scan_cannot_reopen_a_revoked_asset(self, asset):
        with self.assertRaisesRegex(InsightError, "ASSET_SCAN_STATE_INVALID"):
            InsightService().record_scan(None, tenant_id="t", asset_id="a", accepted=True)

    def test_private_upload_url_is_rejected_before_persistence(self):
        with self.assertRaisesRegex(InsightError, "ASSET_SOURCE_REF_UNSAFE"):
            InsightService().ingest_asset(None, tenant_id="t", source_scope="MERCHANT_SUBMITTED", media_kind="IMAGE", source_ref="http://127.0.0.1/private", content_hash="a" * 64, metadata={})

    def test_malformed_and_cgnat_upload_urls_are_rejected_before_persistence(self):
        for source_ref in ("http://", "https:///path", "http://100.64.0.1/a"):
            with self.subTest(source_ref=source_ref), self.assertRaisesRegex(InsightError, "ASSET_SOURCE_REF_UNSAFE"):
                InsightService().ingest_asset(None, tenant_id="t", source_scope="MERCHANT_SUBMITTED", media_kind="IMAGE", source_ref=source_ref, content_hash="a" * 64, metadata={})

    @patch("services.insights.service.repo.asset_has_invalid_ancestor", return_value=False)
    @patch("services.insights.service.repo.get_asset", return_value={"source_scope": "MERCHANT_SUBMITTED", "scan_status": "CHECKED", "lifecycle_status": "REVOKED"})
    def test_revoked_asset_cannot_receive_a_new_rights_grant(self, asset, ancestor):
        with self.assertRaisesRegex(InsightError, "COMPLAINT_ASSET_MARKETING_PROHIBITED"):
            InsightService().approve_rights(None, tenant_id="t", asset_id="a", rights_holder_ref="merchant", purposes=["marketing"], channels=["website"], languages=["zh"], effective_at="2026-01-01T00:00:00Z", expires_at=None, approval_ref="approval")

    @patch("services.insights.service.repo.asset_has_invalid_ancestor", return_value=False)
    @patch("services.insights.service.repo.get_rights_grant", return_value={"asset_id": "a", "status": "REVOKED"})
    @patch("services.insights.service.repo.get_asset", return_value={"source_scope": "MERCHANT_SUBMITTED", "lifecycle_status": "AVAILABLE"})
    def test_revoked_grant_cannot_be_bound_to_a_proposal(self, asset, grant, ancestor):
        with self.assertRaisesRegex(InsightError, "ASSET_USE_INVALID"):
            InsightService().bind_asset_to_proposal(None, tenant_id="t", proposal_id="p", asset_id="a", rights_grant_id="g", purpose="marketing", channel="website", language="zh")


class ProposalToPublicationTests(unittest.TestCase):
    @patch("services.insights.service.repo.update_proposal_status", return_value={"revision": 2})
    @patch("services.insights.service.repo.usable_asset_uses", return_value=[{"content_hash": "photo", "asset_id": "a", "purpose": "marketing", "channel": "website", "language": "zh"}])
    @patch("services.insights.service.repo.get_proposal", return_value={"revision": 1, "status": "DISCUSSING", "required_material": [{"content_hash": "photo", "purpose": "marketing", "channel": "website", "language": "zh"}], "content_diff": {"title": "new"}, "cost_impact": {"labor": "10"}, "shared_resource_impact": {"room": "shared"}})
    def test_approved_proposal_outputs_traceable_service_content(self, proposal, uses, update):
        content = InsightService().approve_proposal_for_service_version(None, tenant_id="t", proposal_id="p", expected_revision=1, now="2026-01-01T00:00:00Z", base_content={"title": "old"})
        self.assertEqual(content["title"], "new")
        self.assertEqual(content["eng11_proposal"]["proposal_revision"], 2)
        self.assertEqual(content["eng11_proposal"]["cost_impact"], {"labor": "10"})

    @patch("services.insights.service.repo.update_proposal_status", return_value={"revision": 3, "status": "APPROVED"})
    @patch("services.insights.service.repo.usable_asset_uses", return_value=[])
    @patch("services.insights.service.repo.get_proposal", return_value={"revision": 2, "status": "AWAITING_APPROVAL", "required_material": [], "content_diff": {"title": "new"}, "cost_impact": {"labor": "10"}, "shared_resource_impact": {"room": "shared"}})
    def test_service_version_and_two_channel_preparation_require_approval_record(self, proposal, uses, update):
        publication = unittest.mock.MagicMock()
        publication.create_approved_version.return_value = "version-1"
        publication.prepare_publications.return_value = (["website", "ota"], [])
        connectors = {("website", "account-web", "TEST"): object(), ("ota", "account-ota", "TEST"): object()}
        outcome = InsightService().create_and_prepare_publications(None, tenant_id="t", proposal_id="p", expected_revision=2, now="2026-01-01T00:00:00Z", base_content={}, service_id="service", version=2, approval_id="approval-record", targets=[{"channel": "website", "connector_account_id": "account-web", "environment": "TEST"}, {"channel": "ota", "connector_account_id": "account-ota", "environment": "TEST"}], publication_service=publication, connectors=connectors)
        self.assertEqual(outcome["service_version_id"], "version-1")
        self.assertEqual(outcome["publication_intents"], ["website", "ota"])
        self.assertEqual(publication.create_approved_version.call_args.kwargs["approval_id"], "approval-record")
        self.assertEqual(publication.prepare_publications.call_args.kwargs["connectors"], connectors)
        self.assertEqual(update.call_args.kwargs["expected_revision"], 2)

    @patch("services.insights.service.repo.revise_proposal", return_value={"revision": 2, "status": "DISCUSSING"})
    def test_revising_proposal_invalidates_prepared_revision(self, revise):
        result = InsightService().revise_proposal(None, tenant_id="t", proposal_id="p", expected_revision=1, content_diff={"title": "changed"}, cost_impact={"labor": "12"}, shared_resource_impact={"room": "shared"}, required_material=[])
        self.assertEqual(result["revision"], 2)
        self.assertEqual(revise.call_args.kwargs["expected_revision"], 1)


if __name__ == "__main__":
    unittest.main()
