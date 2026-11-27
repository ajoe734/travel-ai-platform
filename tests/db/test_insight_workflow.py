"""PostgreSQL acceptance coverage for ENG-11 using its real migration/repository path."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from connectors.mocks.ota_delayed_publication import OtaDelayedPublicationMock
from db.repository import approval_repository, db as repo_db, insight_repository, publication_repository
from services.authorization import canonical_json
from services.insights import InsightError, InsightService
from services.publication import PublicationService
from services.publication.service import PublicationError


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _approval(conn, tenant_id, work_id, service_id, version, content, targets):
    """Create the real ENG-03 record ENG-08 verifies, not a service mock."""
    now = datetime.now(timezone.utc)
    decision_id, approval_id = str(uuid.uuid4()), str(uuid.uuid4())
    payload = {"purpose": "publish service", "service_id": service_id, "version": version, "content": content}
    approval_repository.create_decision_request(
        conn, tenant_id=tenant_id, decision_id=decision_id, revision=1, work_id=work_id,
        decision_type="SERVICE_VERSION_APPROVAL", options=[{"id": "approve"}],
        payload_hash="0" * 64, target_revision=version,
        expires_at=(now + timedelta(hours=1)).isoformat(), requested_role="MERCHANT_ADMIN")
    approval_repository.approve_decision(
        conn, tenant_id=tenant_id, decision_id=decision_id, reviewed_revision=1,
        selected_option_id="approve", approval_id=approval_id,
        approved_by={"actor_kind": "HUMAN_MERCHANT", "actor_id": "merchant"},
        verified_actor_ref="merchant", approved_payload=payload,
        payload_hash=canonical_json.payload_hash(payload),
        scope_manifest=[{"item_id": f"publish-{channel}-{account}", "operation": "publication.update",
                         "resource_ref": {"tenant_id": tenant_id, "id": service_id},
                         "resource_revision": version, "channel": channel, "account": account}
                        for channel, account in targets],
        approved_at=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat())
    return approval_id, now.isoformat()


def _proposal_with_two_assets(conn, tenant_id, case_id, work_id):
    svc = InsightService()
    requirements = [
        {"requirement_id": "web-hero", "purpose": "marketing", "channel": "website", "language": "zh"},
        {"requirement_id": "ota-hero", "purpose": "marketing", "channel": "ota", "language": "en"},
    ]
    proposal = svc.propose_change(conn, tenant_id=tenant_id, case_id=case_id, work_id=work_id, insight_id=None,
        evidence_refs=[{"ref": "merchant:brief"}], hypothesis_refs=[], content_diff={"title": "two-channel revision"},
        cost_impact={"labor": "10"}, shared_resource_impact={"guide": "shared"}, required_material=requirements)
    for item in requirements:
        asset = svc.ingest_asset(conn, tenant_id=tenant_id, proposal_id=proposal["id"], source_scope="MERCHANT_SUBMITTED",
            media_kind="IMAGE", source_ref=f"merchant:{item['requirement_id']}", content_hash=_hash(item["requirement_id"]), metadata={})
        svc.record_scan(conn, tenant_id=tenant_id, asset_id=asset["id"], accepted=True)
        grant = svc.approve_rights(conn, tenant_id=tenant_id, asset_id=asset["id"], rights_holder_ref="merchant",
            purposes=[item["purpose"]], channels=[item["channel"]], languages=[item["language"]],
            effective_at="2026-01-01T00:00:00Z", expires_at=None, approval_ref="merchant:rights")
        svc.bind_asset_to_proposal(conn, tenant_id=tenant_id, proposal_id=proposal["id"], asset_id=asset["id"],
            rights_grant_id=grant["id"], purpose=item["purpose"], channel=item["channel"], language=item["language"])
    return svc, proposal


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
        # A failed statement aborts its transaction in PostgreSQL.  Keep the
        # fixture row by isolating this expected constraint rejection in a
        # savepoint, then commit it for the separate admin-role probe below.
        with pytest.raises(psycopg.Error):
            with conn.transaction():
                conn.execute("UPDATE asset SET lifecycle_status='AVAILABLE' WHERE tenant_id=%s AND id=%s", (tenant_a, asset_id))
    with psycopg.connect(admin_database_url, autocommit=True) as admin:
        with pytest.raises(psycopg.Error):
            admin.execute("UPDATE asset SET lifecycle_status='APPROVED' WHERE tenant_id=%s AND id=%s", (tenant_a, asset_id))


def test_asset_rights_expiry_blocks_proposal_service_content(conn, tenant_a, case_factory, work_factory):
    case_id, work_id = case_factory(tenant_a), None
    work_id = work_factory(tenant_a, case_id)
    svc = InsightService()
    with repo_db.tenant_transaction(conn, tenant_a):
        proposal = svc.propose_change(conn, tenant_id=tenant_a, case_id=case_id, work_id=work_id, insight_id=None, evidence_refs=[{"ref": "merchant:1"}], hypothesis_refs=[], content_diff={"title": "updated"}, cost_impact={"cost": "1"}, shared_resource_impact={"room": "shared"}, required_material=[{"content_hash": _hash("photo"), "purpose": "marketing", "channel": "website", "language": "zh"}])
        asset = svc.ingest_asset(conn, tenant_id=tenant_a, proposal_id=proposal["id"], source_scope="MERCHANT_SUBMITTED", media_kind="IMAGE", source_ref="merchant:photo", content_hash=_hash("photo"), metadata={})
        svc.record_scan(conn, tenant_id=tenant_a, asset_id=asset["id"], accepted=True)
        grant = svc.approve_rights(conn, tenant_id=tenant_a, asset_id=asset["id"], rights_holder_ref="merchant", purposes=["marketing"], channels=["website"], languages=["zh"], effective_at="2026-01-01T00:00:00Z", expires_at="2026-01-02T00:00:00Z", approval_ref="approval:asset")
        svc.bind_asset_to_proposal(conn, tenant_id=tenant_a, proposal_id=proposal["id"], asset_id=asset["id"], rights_grant_id=grant["id"], purpose="marketing", channel="website", language="zh")
        with pytest.raises(InsightError, match="REQUIRED_MATERIAL_RIGHTS_MISSING"):
            svc.approve_proposal_for_service_version(conn, tenant_id=tenant_a, proposal_id=proposal["id"], expected_revision=1, now="2026-01-03T00:00:00Z", base_content={"title": "old"})


def test_proposal_uses_real_approval_and_two_independent_publications(conn, tenant_a, case_factory, work_factory):
    """ENG-11 -> ENG-03 -> ENG-08 uses production repositories end-to-end."""
    case_id, work_id, service_id = case_factory(tenant_a), None, str(uuid.uuid4())
    work_id = work_factory(tenant_a, case_id)
    targets = [("website", "web-a"), ("ota", "ota-a")]
    web_connector, ota_connector = OtaDelayedPublicationMock(), OtaDelayedPublicationMock()
    with repo_db.tenant_transaction(conn, tenant_a):
        svc, proposal = _proposal_with_two_assets(conn, tenant_a, case_id, work_id)
        content = svc.approve_proposal_for_service_version(conn, tenant_id=tenant_a, proposal_id=proposal["id"],
            expected_revision=1, now="2026-02-01T00:00:00Z", base_content={"title": "old"})
        assert content["eng11_proposal"]["cost_impact"] == {"labor": "10"}
        assert content["eng11_proposal"]["shared_resource_impact"] == {"guide": "shared"}
        assert [item["channel"] for item in content["eng11_proposal"]["asset_uses"]] == ["ota", "website"]
        approval_id, now = _approval(conn, tenant_a, work_id, service_id, 2, content, targets)
        for channel, account in targets:
            publication_repository.set_channel_access(conn, tenant_id=tenant_a, channel=channel,
                connector_account_id=account, environment="MOCK", publication_enabled=True, reason=None)
        outcome = svc.create_and_prepare_publications(conn, tenant_id=tenant_a, proposal_id=proposal["id"],
            expected_revision=2, now=now, base_content={"title": "old"}, service_id=service_id, version=2,
            approval_id=approval_id, targets=[{"channel": channel, "connector_account_id": account, "environment": "MOCK"}
                                              for channel, account in targets], publication_service=PublicationService(),
            connectors={("website", "web-a", "MOCK"): web_connector,
                        ("ota", "ota-a", "MOCK"): ota_connector})
        assert outcome["proposal"]["status"] == "APPROVED"
        assert len(outcome["publication_intents"]) == 2
        assert {intent.channel for intent in outcome["publication_intents"]} == {"website", "ota"}
        assert len({intent.publication_id for intent in outcome["publication_intents"]}) == 2
        publication_service = PublicationService()
        claimed = {intent.channel: publication_service.claim_dispatch(conn, tenant_id=tenant_a, intent=intent,
                    connector={"website": web_connector, "ota": ota_connector}[intent.channel], now=now)
                   for intent in outcome["publication_intents"]}
        saved = conn.execute("SELECT content FROM service_version WHERE tenant_id=%s AND id=%s", (tenant_a, outcome["service_version_id"])).fetchone()[0]
    assert saved["eng11_proposal"]["asset_uses"] == content["eng11_proposal"]["asset_uses"]
    dispatched = {channel: PublicationService().dispatch_publication(tenant_id=tenant_a, intent=intent,
                  connector={"website": web_connector, "ota": ota_connector}[channel], now=now)
                  for channel, intent in claimed.items()}
    assert set(dispatched) == {"website", "ota"}
    assert len(web_connector._backend) == len(ota_connector._backend) == 1


def test_revised_proposal_rejects_old_approval_record(conn, tenant_a, case_factory, work_factory):
    case_id, work_id, service_id = case_factory(tenant_a), None, str(uuid.uuid4())
    work_id = work_factory(tenant_a, case_id)
    targets = [("website", "web-a"), ("ota", "ota-a")]
    with repo_db.tenant_transaction(conn, tenant_a):
        svc, proposal = _proposal_with_two_assets(conn, tenant_a, case_id, work_id)
        old_content = svc.approve_proposal_for_service_version(conn, tenant_id=tenant_a, proposal_id=proposal["id"],
            expected_revision=1, now="2026-02-01T00:00:00Z", base_content={"title": "old"})
        old_approval, now = _approval(conn, tenant_a, work_id, service_id, 3, old_content, targets)
        revised = svc.revise_proposal(conn, tenant_id=tenant_a, proposal_id=proposal["id"], expected_revision=2,
            content_diff={"title": "merchant changed it"}, cost_impact={"labor": "12"},
            shared_resource_impact={"guide": "shared"}, required_material=proposal["required_material"])
        assert revised["status"] == "DISCUSSING"
        new_content = svc.approve_proposal_for_service_version(conn, tenant_id=tenant_a, proposal_id=proposal["id"],
            expected_revision=3, now=now, base_content={"title": "old"})
        assert new_content != old_content
        with pytest.raises(PublicationError, match="APPROVAL_CONTENT_MISMATCH"):
            svc.create_and_prepare_publications(conn, tenant_id=tenant_a, proposal_id=proposal["id"], expected_revision=4,
                now=now, base_content={"title": "old"}, service_id=service_id, version=3, approval_id=old_approval,
                targets=[{"channel": channel, "connector_account_id": account, "environment": "MOCK"}
                         for channel, account in targets], publication_service=PublicationService())


def test_catalog_gap_discussion_and_asset_revocation_are_enforced_in_postgres(conn, tenant_a, tenant_b, case_factory, work_factory):
    case_id, work_id = case_factory(tenant_a), None
    work_id = work_factory(tenant_a, case_id)
    svc = InsightService()
    requirement = {"requirement_id": "ota-hero", "purpose": "marketing", "channel": "ota", "language": "en"}
    with repo_db.tenant_transaction(conn, tenant_a):
        proposal = svc.propose_change(conn, tenant_id=tenant_a, case_id=case_id, work_id=work_id, insight_id=None,
            evidence_refs=[{"ref": "merchant:brief"}], hypothesis_refs=[], content_diff={"title": "new"},
            cost_impact={"labor": "10"}, shared_resource_impact={"guide": "shared"}, required_material=[requirement])
        assert svc.ask_missing_material(conn, tenant_id=tenant_a, proposal_id=proposal["id"], requested_channels=["ota"],
            deadline=None, now="2026-02-01T00:00:00Z") == [requirement]
        asset = svc.ingest_asset(conn, tenant_id=tenant_a, proposal_id=proposal["id"], source_scope="MERCHANT_SUBMITTED",
            media_kind="IMAGE", source_ref="merchant:ota", content_hash=_hash("ota"), metadata={})
        svc.record_scan(conn, tenant_id=tenant_a, asset_id=asset["id"], accepted=True)
        grant = svc.approve_rights(conn, tenant_id=tenant_a, asset_id=asset["id"], rights_holder_ref="merchant",
            purposes=["marketing"], channels=["ota"], languages=["en"], effective_at="2026-01-01T00:00:00Z",
            expires_at=None, approval_ref="merchant:rights")
        # The tenant catalog, rather than merely an already-bound use, satisfies the exact scope.
        assert svc.ask_missing_material(conn, tenant_id=tenant_a, proposal_id=proposal["id"], requested_channels=["ota"],
            deadline=None, now="2026-02-01T00:00:00Z") == []
        assert insight_repository.find_usable_assets(conn, tenant_id=tenant_b, now="2026-02-01T00:00:00Z") == []
        assert svc.append_discussion(conn, tenant_id=tenant_a, proposal_id=proposal["id"], speaker="MERCHANT",
            message_kind="TEXT", body={"text": "first"}, source_refs=[]) == 1
        assert svc.append_discussion(conn, tenant_id=tenant_a, proposal_id=proposal["id"], speaker="ASSISTANT",
            message_kind="TEXT", body={"text": "second"}, source_refs=[]) == 2
        svc.bind_asset_to_proposal(conn, tenant_id=tenant_a, proposal_id=proposal["id"], asset_id=asset["id"],
            rights_grant_id=grant["id"], purpose="marketing", channel="ota", language="en")
        svc.revoke_rights(conn, tenant_id=tenant_a, rights_grant_id=grant["id"])
        assert insight_repository.usable_asset_uses(conn, tenant_id=tenant_a, proposal_id=proposal["id"], now="2026-02-01T00:00:00Z") == []
        svc.revoke_asset(conn, tenant_id=tenant_a, asset_id=asset["id"])
        with pytest.raises(InsightError, match="ASSET_REVOKE_INVALID"):
            svc.revoke_asset(conn, tenant_id=tenant_a, asset_id=asset["id"])


def test_insight_lineage_and_immutable_constraints_are_database_enforced(conn, tenant_a, tenant_b, case_factory, work_factory, admin_database_url):
    case_a, case_b = case_factory(tenant_a), case_factory(tenant_a)
    work_a = work_factory(tenant_a, case_a)
    svc = InsightService()
    with repo_db.tenant_transaction(conn, tenant_a):
        insight = svc.record_observation(conn, tenant_id=tenant_a, case_id=case_a, query_version="v1", metric_key="metric",
            period_start="2026-01-01T00:00:00Z", period_end="2026-01-02T00:00:00Z", numerator={"n": 1}, denominator={"n": 2},
            coverage={"complete": True}, case_dedupe_version="case-v1", observed_facts=[{"source_ref": "query:1"}], hypotheses=[], evidence_refs=[])
        with pytest.raises(psycopg.Error):
            with conn.transaction():
                svc.propose_change(conn, tenant_id=tenant_a, case_id=case_b, work_id=work_a, insight_id=insight["id"],
                    evidence_refs=[{"ref": insight["id"]}], hypothesis_refs=[], content_diff={"title": "bad lineage"},
                    cost_impact={"labor": "1"}, shared_resource_impact={"guide": "shared"}, required_material=[])
    with psycopg.connect(admin_database_url, autocommit=True) as admin:
        with pytest.raises(psycopg.Error):
            admin.execute("UPDATE operating_insight SET metric_key='mutated' WHERE tenant_id=%s AND id=%s", (tenant_a, insight["id"]))
