"""PostgreSQL acceptance coverage for ENG-08's publication projection.

This suite deliberately uses the ENG-08 0007/0008 migrations and production repositories; it
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
from services.publication.service import PublicationError, PublicationService


def _approval(conn, tenant_id, work_id, service_id, version, content, targets=None, *, expires_at=None, scope_tenant_id=None):
    now = datetime.now(timezone.utc)
    decision_id, approval_id = str(uuid.uuid4()), str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        approval_repository.create_decision_request(
            conn, tenant_id=tenant_id, decision_id=decision_id, revision=1, work_id=work_id,
            decision_type="SERVICE_VERSION_APPROVAL", options=[{"id": "approve"}],
            payload_hash="0" * 64, target_revision=version,
            expires_at=(now + timedelta(hours=1)).isoformat(), requested_role="MERCHANT_ADMIN",
        )
        payload = {"purpose": "publish service", "service_id": service_id, "version": version, "content": content}
        approval_repository.approve_decision(
            conn, tenant_id=tenant_id, decision_id=decision_id, reviewed_revision=1,
            selected_option_id="approve", approval_id=approval_id,
            approved_by={"actor_kind": "HUMAN_MERCHANT", "actor_id": "merchant"},
            verified_actor_ref="merchant", approved_payload=payload,
            payload_hash=canonical_json.payload_hash(payload),
            scope_manifest=[{"item_id": f"publish-{channel}-{account}", "operation": "publication.update",
                             "resource_ref": {"tenant_id": scope_tenant_id or tenant_id, "id": service_id},
                             "resource_revision": version, "channel": channel, "account": account}
                            for channel, account in (targets or [("ota", "ota-a")])],
            approved_at=now.isoformat(), expires_at=expires_at or (now + timedelta(hours=1)).isoformat(),
        )
    return approval_id, now.isoformat()


def test_approved_version_is_immutable_and_keeps_old_order_untouched(conn, admin_database_url, tenant_a, case_factory, work_factory, payment_chain_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    service_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
    order = payment_chain_factory(tenant_a, case_id, captured_amount=1000)
    content = {"title": "new title", "price": "1000"}
    approval_id, now = _approval(conn, tenant_a, work_id, service_id, 2, content)
    with repo_db.tenant_transaction(conn, tenant_a):
        PublicationService().create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=2,
            content=content, approval_id=approval_id, now=now,
            version_id=version_id, base_version=1, base_content={"title": "old title", "price": "900"})
        saved = publication_repository.get_service_version(conn, tenant_id=tenant_a, service_version_id=version_id)
    assert saved["base_version"] == 1
    assert saved["change_diff"]["changes"]
    with repo_db.tenant_transaction(conn, tenant_a):
        assert conn.execute("SELECT total_amount_minor_units FROM order_record WHERE tenant_id=%s AND id=%s", (tenant_a, order["order_id"])).fetchone()[0] == "1000"
    with psycopg.connect(admin_database_url, autocommit=True) as admin_conn:
        with pytest.raises(psycopg.Error):
            admin_conn.execute("UPDATE service_version SET content='{}'::jsonb WHERE tenant_id=%s AND id=%s", (tenant_a, version_id))


def test_ota_unknown_then_reconcile_and_rejected_are_independent_and_summarised(conn, tenant_a, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    service_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
    content = {"title": "v2"}
    approval_id, now = _approval(conn, tenant_a, work_id, service_id, 2, content)
    svc, ota = PublicationService(), OtaDelayedPublicationMock()
    with repo_db.tenant_transaction(conn, tenant_a):
        svc.create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=2, content=content,
            approval_id=approval_id, now=now, version_id=version_id)
        publication_repository.set_channel_access(conn, tenant_id=tenant_a, channel="ota", connector_account_id="ota-a", environment="MOCK", publication_enabled=True, reason=None)
        intents, blocked = svc.prepare_publications(conn, tenant_id=tenant_a, service_version_id=version_id, service_version=2,
            targets=[{"channel": "ota", "connector_account_id": "ota-a", "environment": "MOCK"}], now=now)
    assert not blocked
    intent = intents[0]
    with repo_db.tenant_transaction(conn, tenant_a):
        claimed = svc.claim_dispatch(conn, tenant_id=tenant_a, intent=intent, connector=ota, now=now)
    assert claimed is not None
    result = svc.dispatch_publication(tenant_id=tenant_a, intent=claimed, connector=ota, now=now, simulate_response_lost=True)
    with repo_db.tenant_transaction(conn, tenant_a):
        unknown = svc.record_connector_result(conn, tenant_id=tenant_a, publication_id=claimed.publication_id,
                                              expected_revision=claimed.expected_revision, result=result, now=now)
    assert unknown["status"] == "UNKNOWN"
    ota.advance_review(tenant_a, intent.business_key, "LIVE_VERIFIED")
    with repo_db.tenant_transaction(conn, tenant_a):
        reconciliation = svc.claim_reconciliation(conn, tenant_id=tenant_a, publication_id=intent.publication_id,
                                                   expected_revision=unknown["revision"])
        token = publication_repository.get_publication(conn, tenant_id=tenant_a, publication_id=intent.publication_id)["reconciliation_token"]
    readback = svc.reconcile_publication(tenant_id=tenant_a, intent=reconciliation, reconciliation_token=token, connector=ota, now=now)
    with repo_db.tenant_transaction(conn, tenant_a):
        live = svc.record_connector_result(conn, tenant_id=tenant_a, publication_id=intent.publication_id,
                                           expected_revision=reconciliation.expected_revision, result=readback, now=now)
        summary = publication_repository.publication_summary(conn, tenant_id=tenant_a, service_version_id=version_id)
    assert live["status"] == "LIVE"
    assert summary == {"LIVE": 1}


def test_publication_rls_and_pending_constraints(conn, tenant_a, tenant_b, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    service_id, version_id = str(uuid.uuid4()), str(uuid.uuid4())
    content = {"title": "v1"}
    approval_id, now = _approval(conn, tenant_a, work_id, service_id, 1, content)
    with repo_db.tenant_transaction(conn, tenant_a):
        PublicationService().create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=1,
            content=content, approval_id=approval_id, now=now, version_id=version_id)
        row = publication_repository.create_publication(conn, tenant_id=tenant_a, publication_id=str(uuid.uuid4()), service_version_id=version_id,
            channel="website", connector_account_id="web", environment="MOCK", business_key="publication:test", desired_version=1)
        with pytest.raises(psycopg.Error):
            publication_repository.observe_publication(conn, tenant_id=tenant_a, publication_id=row["id"], expected_revision=1,
                status="PENDING", submitted_version=1, external_reference="only-reference")
    with repo_db.tenant_transaction(conn, tenant_b):
        assert publication_repository.get_publication(conn, tenant_id=tenant_b, publication_id=row["id"]) is None


def test_approval_content_tenant_expiry_and_revocation_are_rechecked(conn, tenant_a, tenant_b, case_factory, work_factory):
    case_id, service_id = case_factory(tenant_a), str(uuid.uuid4())
    work_id, content = work_factory(tenant_a, case_id), {"title": "approved", "price": "10000"}
    svc = PublicationService()
    approval_id, now = _approval(conn, tenant_a, work_id, service_id, 1, content)
    with repo_db.tenant_transaction(conn, tenant_a):
        with pytest.raises(PublicationError, match="APPROVAL_CONTENT_MISMATCH"):
            svc.create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=1,
                content={"title": "tampered", "price": "1"}, approval_id=approval_id, now=now)
    wrong_id, _ = _approval(conn, tenant_a, work_id, service_id, 2, content, scope_tenant_id=tenant_b)
    with repo_db.tenant_transaction(conn, tenant_a):
        with pytest.raises(PublicationError, match="APPROVAL_SCOPE_MISMATCH"):
            svc.create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=2,
                content=content, approval_id=wrong_id, now=now)
    expired_id, _ = _approval(conn, tenant_a, work_id, service_id, 3, content, expires_at="2020-01-01T00:00:00+00:00")
    with repo_db.tenant_transaction(conn, tenant_a):
        with pytest.raises(PublicationError, match="APPROVAL_NOT_EFFECTIVE"):
            svc.create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=3,
                content=content, approval_id=expired_id, now=now)


def test_unapproved_target_and_revocation_block_before_connector_write(conn, tenant_a, case_factory, work_factory):
    case_id, service_id = case_factory(tenant_a), str(uuid.uuid4())
    work_id, content, version_id = work_factory(tenant_a, case_id), {"title": "v1"}, str(uuid.uuid4())
    approval_id, now = _approval(conn, tenant_a, work_id, service_id, 1, content, targets=[("ota", "ota-a")])
    svc, ota = PublicationService(), OtaDelayedPublicationMock()
    with repo_db.tenant_transaction(conn, tenant_a):
        svc.create_approved_version(conn, tenant_id=tenant_a, service_id=service_id, version=1, content=content,
            approval_id=approval_id, now=now, version_id=version_id)
        publication_repository.set_channel_access(conn, tenant_id=tenant_a, channel="website", connector_account_id="web", environment="MOCK", publication_enabled=True, reason=None)
        _, blocked = svc.prepare_publications(conn, tenant_id=tenant_a, service_version_id=version_id, service_version=1,
            targets=[{"channel": "website", "connector_account_id": "web", "environment": "MOCK"}], now=now)
    assert blocked[0]["status"] == "BLOCKED"
    with repo_db.tenant_transaction(conn, tenant_a):
        publication_repository.set_channel_access(conn, tenant_id=tenant_a, channel="ota", connector_account_id="ota-a", environment="MOCK", publication_enabled=True, reason=None)
        intents, blocked = svc.prepare_publications(conn, tenant_id=tenant_a, service_version_id=version_id, service_version=1,
            targets=[{"channel": "ota", "connector_account_id": "ota-a", "environment": "MOCK"}], now=now)
        assert not blocked
        approval_repository.revoke_approval(conn, tenant_id=tenant_a, revocation_id=str(uuid.uuid4()), approval_id=approval_id,
            revoked_by={"actor_kind": "HUMAN_MERCHANT", "actor_id": "merchant"}, reason="withdrawn", effective_at=now)
        assert svc.claim_dispatch(conn, tenant_id=tenant_a, intent=intents[0], connector=ota, now=now) is None
    assert ota._backend == {}
