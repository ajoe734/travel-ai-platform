"""PostgreSQL acceptance coverage for ENG-11 using its real migration/repository path."""
from __future__ import annotations

import hashlib
import uuid

import psycopg
import pytest

from db.repository import db as repo_db, insight_repository
from services.insights import InsightError, InsightService


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_observation_and_proposal_are_tenant_scoped(conn, tenant_a, tenant_b, case_factory, work_factory):
    work_case = case_factory(tenant_a)
    work_id = work_factory(tenant_a, work_case)
    svc = InsightService()
    with repo_db.tenant_transaction(conn, tenant_a):
        insight = svc.record_observation(conn, tenant_id=tenant_a, case_id=work_case, query_version="quote-rate-v1", metric_key="quote_rate", period_start="2026-01-01T00:00:00Z", period_end="2026-01-08T00:00:00Z", numerator={"value": 1}, denominator={"value": 2}, coverage={"complete": False}, case_dedupe_version="case-dedupe-v1", observed_facts=[{"source_ref": "controlled-query:7", "value": 1}], hypotheses=[{"label": "silence remains UNKNOWN"}], evidence_refs=[{"ref": "controlled-query:7"}])
        proposal = svc.propose_change(conn, tenant_id=tenant_a, case_id=work_case, work_id=work_id, insight_id=insight["id"], evidence_refs=[{"ref": insight["id"]}], hypothesis_refs=[{"label": "test"}], content_diff={"title": "short"}, cost_impact={"labor": "1"}, shared_resource_impact={"guide": "shared"}, required_material=[])
    with repo_db.tenant_transaction(conn, tenant_b):
        assert insight_repository.get_proposal(conn, tenant_id=tenant_b, proposal_id=proposal["id"]) is None
        assert insight_repository.get_proposal(conn, tenant_id=tenant_b, proposal_id=str(uuid.uuid4())) is None
    assert insight["result_hash"]


def test_complaint_asset_cannot_be_marketed_even_by_direct_db_write(conn, tenant_a, admin_database_url):
    asset_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_a):
        InsightService().ingest_asset(conn, tenant_id=tenant_a, asset_id=asset_id, source_scope="COMPLAINT_EVIDENCE", media_kind="IMAGE", source_ref="complaint:evidence", content_hash=_hash("complaint"), metadata={})
        with pytest.raises(psycopg.Error):
            conn.execute("UPDATE asset SET lifecycle_status='AVAILABLE' WHERE tenant_id=%s AND id=%s", (tenant_a, asset_id))
    with psycopg.connect(admin_database_url, autocommit=True) as admin:
        with pytest.raises(psycopg.Error):
            admin.execute("UPDATE asset SET lifecycle_status='APPROVED' WHERE tenant_id=%s AND id=%s", (tenant_a, asset_id))


def test_asset_rights_expiry_blocks_proposal_service_content(conn, tenant_a, case_factory, work_factory):
    case_id, work_id = case_factory(tenant_a), None
    work_id = work_factory(tenant_a, case_id)
    svc = InsightService()
    with repo_db.tenant_transaction(conn, tenant_a):
        proposal = svc.propose_change(conn, tenant_id=tenant_a, case_id=case_id, work_id=work_id, insight_id=None, evidence_refs=[{"ref": "merchant:1"}], hypothesis_refs=[], content_diff={"title": "updated"}, cost_impact={"cost": "1"}, shared_resource_impact={"room": "shared"}, required_material=[{"content_hash": _hash("photo")}])
        asset = svc.ingest_asset(conn, tenant_id=tenant_a, proposal_id=proposal["id"], source_scope="MERCHANT_SUBMITTED", media_kind="IMAGE", source_ref="merchant:photo", content_hash=_hash("photo"), metadata={})
        svc.record_scan(conn, tenant_id=tenant_a, asset_id=asset["id"], accepted=True)
        grant = svc.approve_rights(conn, tenant_id=tenant_a, asset_id=asset["id"], rights_holder_ref="merchant", purposes=["marketing"], channels=["website"], languages=["zh"], effective_at="2026-01-01T00:00:00Z", expires_at="2026-01-02T00:00:00Z", approval_ref="approval:asset")
        svc.bind_asset_to_proposal(conn, tenant_id=tenant_a, proposal_id=proposal["id"], asset_id=asset["id"], rights_grant_id=grant["id"], purpose="marketing", channel="website", language="zh")
        with pytest.raises(InsightError, match="REQUIRED_MATERIAL_RIGHTS_MISSING"):
            svc.approve_proposal_for_service_version(conn, tenant_id=tenant_a, proposal_id=proposal["id"], expected_revision=1, now="2026-01-03T00:00:00Z", base_content={"title": "old"})
