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
        self.assertEqual(create.call_args.kwargs["result_hash"], "afc20af5fa458a8e2daf547cb29aa341ad1f5a5793aa830d5450616cb23de554")


class MaterialRequestTests(unittest.TestCase):
    @patch("services.insights.service.repo.create_material_request")
    @patch("services.insights.service.repo.usable_asset_uses", return_value=[{"content_hash": "a"}])
    @patch("services.insights.service.repo.get_proposal", return_value={"required_material": [{"content_hash": "a"}, {"content_hash": "b"}]})
    def test_only_missing_material_is_requested(self, proposal, uses, create):
        missing = InsightService().ask_missing_material(None, tenant_id="t", proposal_id="p", requested_channels=["website"], deadline=None, now="2026-01-01T00:00:00Z", request_id="r")
        self.assertEqual(missing, [{"content_hash": "b"}])
        self.assertEqual(create.call_args.kwargs["required_items"], missing)


class AssetRightsTests(unittest.TestCase):
    @patch("services.insights.service.repo.get_asset", return_value={"source_scope": "COMPLAINT_EVIDENCE", "scan_status": "CHECKED"})
    def test_complaint_attachment_never_becomes_marketing_asset(self, asset):
        with self.assertRaisesRegex(InsightError, "COMPLAINT_ASSET_MARKETING_PROHIBITED"):
            InsightService().approve_rights(None, tenant_id="t", asset_id="a", rights_holder_ref="merchant", purposes=["marketing"], channels=["website"], languages=["zh"], effective_at="2026-01-01T00:00:00Z", expires_at=None, approval_ref="approval")

    @patch("services.insights.service.repo.set_asset_scan")
    @patch("services.insights.service.repo.create_rights_grant", return_value={"id": "g"})
    @patch("services.insights.service.repo.get_asset", return_value={"source_scope": "MERCHANT_SUBMITTED", "scan_status": "CHECKED"})
    def test_explicit_scanned_asset_rights_are_required(self, asset, grant, scan):
        result = InsightService().approve_rights(None, tenant_id="t", asset_id="a", rights_holder_ref="merchant", purposes=["marketing"], channels=["website"], languages=["zh"], effective_at="2026-01-01T00:00:00Z", expires_at=None, approval_ref="approval", grant_id="g")
        self.assertEqual(result, {"id": "g"})
        self.assertEqual(scan.call_args.kwargs["lifecycle_status"], "AVAILABLE")


class ProposalToPublicationTests(unittest.TestCase):
    @patch("services.insights.service.repo.update_proposal_status", return_value={"revision": 2})
    @patch("services.insights.service.repo.usable_asset_uses", return_value=[{"content_hash": "photo", "asset_id": "a"}])
    @patch("services.insights.service.repo.get_proposal", return_value={"revision": 1, "required_material": [{"content_hash": "photo"}], "content_diff": {"title": "new"}, "cost_impact": {"labor": "10"}, "shared_resource_impact": {"room": "shared"}})
    def test_approved_proposal_outputs_traceable_service_content(self, proposal, uses, update):
        content = InsightService().approve_proposal_for_service_version(None, tenant_id="t", proposal_id="p", expected_revision=1, now="2026-01-01T00:00:00Z", base_content={"title": "old"})
        self.assertEqual(content["title"], "new")
        self.assertEqual(content["eng11_proposal"]["proposal_revision"], 2)
        self.assertEqual(content["eng11_proposal"]["cost_impact"], {"labor": "10"})


if __name__ == "__main__":
    unittest.main()
