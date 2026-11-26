"""backlog ENG-02 acceptance: 批准紀錄不可改寫.

approval_record has no UPDATE/DELETE grant path that matters: the
forbid_update_delete() trigger installed in db/migrations/0001 rejects both
operations outright (ADR 0003 / specs/domain/relationships.md), even though
the owning migration role could otherwise bypass a plain REVOKE.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from db.repository import approval_repository, db as repo_db
from db.repository.errors import ImmutableRecordViolation, translate_integrity_error


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _approve_a_decision(conn, tenant_id, work_id):
    decision_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with repo_db.tenant_transaction(conn, tenant_id):
        approval_repository.create_decision_request(
            conn,
            tenant_id=tenant_id,
            decision_id=decision_id,
            revision=1,
            work_id=work_id,
            decision_type="REFUND_APPROVAL",
            options=[{"id": "approve", "label": "approve"}, {"id": "reject", "label": "reject"}],
            payload_hash=_sha256_hex("decision-payload"),
            target_revision=1,
            expires_at=(now + timedelta(hours=1)).isoformat(),
            requested_role="MERCHANT_ADMIN",
        )

    approval_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        approval_repository.approve_decision(
            conn,
            tenant_id=tenant_id,
            decision_id=decision_id,
            reviewed_revision=1,
            selected_option_id="approve",
            approval_id=approval_id,
            approved_by={"actor_kind": "HUMAN_MERCHANT", "actor_id": "merchant-1"},
            verified_actor_ref="merchant-1",
            approved_payload={"id": "approve"},
            payload_hash=_sha256_hex("decision-payload"),
            scope_manifest=[{"item_id": "approve"}],
            approved_at=now.isoformat(),
        )
    return approval_id


def test_approval_record_cannot_be_updated(conn, admin_database_url, tenant_a, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    approval_id = _approve_a_decision(conn, tenant_a, work_id)

    # Layer 1: app_role (0003 grants it only SELECT, INSERT on
    # approval_record) is rejected by Postgres's own privilege check before
    # the forbid_update_delete() trigger ever runs.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repo_db.tenant_transaction(conn, tenant_a):
            conn.execute(
                "UPDATE approval_record SET approved_payload = %s WHERE tenant_id = %s AND id = %s",
                (json.dumps({"id": "reject"}), tenant_a, approval_id),
            )

    # Layer 2: the migration/admin role owns the table (so it has UPDATE and,
    # being a superuser in this CI setup, also bypasses RLS) and still hits
    # the forbid_update_delete() trigger itself.
    with psycopg.connect(admin_database_url, autocommit=True) as admin_conn:
        with pytest.raises(psycopg.Error) as excinfo:
            admin_conn.execute(
                "UPDATE approval_record SET approved_payload = %s WHERE tenant_id = %s AND id = %s",
                (json.dumps({"id": "reject"}), tenant_a, approval_id),
            )
        assert isinstance(translate_integrity_error(excinfo.value), ImmutableRecordViolation)


def test_approval_record_cannot_be_deleted(conn, admin_database_url, tenant_a, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    approval_id = _approve_a_decision(conn, tenant_a, work_id)

    # Layer 1: same privilege check as the UPDATE case above.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with repo_db.tenant_transaction(conn, tenant_a):
            conn.execute(
                "DELETE FROM approval_record WHERE tenant_id = %s AND id = %s",
                (tenant_a, approval_id),
            )

    # Layer 2: the admin/owner role has DELETE and bypasses RLS, but the
    # trigger still forbids it.
    with psycopg.connect(admin_database_url, autocommit=True) as admin_conn:
        with pytest.raises(psycopg.Error) as excinfo:
            admin_conn.execute(
                "DELETE FROM approval_record WHERE tenant_id = %s AND id = %s",
                (tenant_a, approval_id),
            )
        assert isinstance(translate_integrity_error(excinfo.value), ImmutableRecordViolation)
