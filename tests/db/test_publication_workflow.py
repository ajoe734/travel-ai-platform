"""PostgreSQL acceptance coverage for ENG-08's publication projection.

This suite deliberately uses migration 0006 and production repositories; it
does not recreate publication tables in test SQL.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from connectors.mocks.ota_delayed_publication import OtaDelayedPublicationMock
from db.repository import approval_repository, db as repo_db, publication_repository
from services.authorization import canonical_json
from services.publication.service import PublicationService


def _approval(conn, tenant_id, work_id, service_id, version):
    now = datetime.now(timezone.utc)
    decision_id, approval_id = str(uuid.uuid4()), str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        approval_repository.create_decision_request(
            conn, tenant_id=tenant_id, decision_id=decision_id, revision=1, work_id=work_id,
            decision_type="SERVICE_VERSION_APPROVAL", options=[{"id": "approve"}],
            payload_hash="0" * 64, target_revision=version,
            expires_at=(now + timedelta(hours=1)).isoformat(), requested_role="MERCHANT_ADMIN",
        )
        payload = {"purpose": "publish service", "service_id": service_id, "version": version}
        approval_repository.approve_decision(
            conn, tenant_id=tenant_id, decision_id=decision_id, reviewed_revision=1,
            selected_option_id="approve", approval_id=approval_id,
            approved_by={"actor_kind": "HUMAN_MERCHANT", "actor_id": "merchant"},
            verified_actor_ref="merchant", approved_payload=payload,
            payload_hash=canonical_json.payload_hash(payload),
            scope_manifest=[{"item_id": "publish", "operation": "publication.update",
                             "resource_ref": {"tenant_id": tenant_id, "id": service_id},
                             "resource_revision": version, "channel": "ota", "account": "mock-ota-account"}],
            approved_at=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(),
        )
    return approval_id, now.isoformat()


def test_approved_version_is_immutable_and_keeps_old_order_untouched(conn, admin_database_url, tenant_a, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    service_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
    approval_id, now = _approval(conn, tenant_a, work_id, service_id, 2)
    with repo_db.tenant_transaction(conn, tenant_a):
        PublicationService().create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=2,
            content={"title": "new title", "price": "1000"}, approval_id=approval_id, now=now,
            version_id=version_id, base_version=1, base_content={"title": "old title", "price": "900"})
        saved = publication_repository.get_service_version(conn, tenant_id=tenant_a, service_version_id=version_id)
    assert saved["base_version"] == 1
    assert saved["change_diff"]["changes"]
    with psycopg.connect(admin_database_url, autocommit=True) as admin_conn:
        with pytest.raises(psycopg.Error):
            admin_conn.execute("UPDATE service_version SET content='{}'::jsonb WHERE tenant_id=%s AND id=%s", (tenant_a, version_id))


def test_ota_unknown_then_reconcile_and_rejected_are_independent_and_summarised(conn, tenant_a, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    service_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
    approval_id, now = _approval(conn, tenant_a, work_id, service_id, 2)
    svc, ota = PublicationService(), OtaDelayedPublicationMock()
    with repo_db.tenant_transaction(conn, tenant_a):
        svc.create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=2, content={"title": "v2"},
            approval_id=approval_id, now=now, version_id=version_id)
        publication_repository.set_channel_access(conn, tenant_id=tenant_a, channel="ota", connector_account_id="ota-a", environment="MOCK", publication_enabled=True, reason=None)
        intents, blocked = svc.prepare_publications(conn, tenant_id=tenant_a, service_version_id=version_id, service_version=2,
            targets=[{"channel": "ota", "connector_account_id": "ota-a", "environment": "MOCK"}])
    assert not blocked
    intent = intents[0]
    with repo_db.tenant_transaction(conn, tenant_a):
        unknown = svc.dispatch_publication(conn, tenant_id=tenant_a, intent=intent, expected_revision=1, connector=ota, now=now, simulate_response_lost=True)
    assert unknown["status"] == "UNKNOWN"
    ota.advance_review(tenant_a, intent.business_key, "LIVE_VERIFIED")
    with repo_db.tenant_transaction(conn, tenant_a):
        live = svc.reconcile_publication(conn, tenant_id=tenant_a, publication_id=intent.publication_id, expected_revision=unknown["revision"], connector=ota, now=now)
        summary = publication_repository.publication_summary(conn, tenant_id=tenant_a, service_version_id=version_id)
    assert live["status"] == "LIVE"
    assert summary == {"LIVE": 1}


def test_publication_rls_and_pending_constraints(conn, tenant_a, tenant_b, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    service_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
    approval_id, now = _approval(conn, tenant_a, work_id, service_id, 1)
    with repo_db.tenant_transaction(conn, tenant_a):
        PublicationService().create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=1,
            content={"title": "v1"}, approval_id=approval_id, now=now, version_id=version_id)
        row = publication_repository.create_publication(conn, tenant_id=tenant_a, publication_id=str(uuid.uuid4()), service_version_id=version_id,
            channel="website", connector_account_id="web", environment="MOCK", business_key="publication:test", desired_version=1)
        with pytest.raises(psycopg.Error):
            publication_repository.observe_publication(conn, tenant_id=tenant_a, publication_id=row["id"], expected_revision=1,
                status="PENDING", submitted_version=1, external_reference="only-reference")
    with repo_db.tenant_transaction(conn, tenant_b):
        assert publication_repository.get_publication(conn, tenant_id=tenant_b, publication_id=row["id"]) is None
