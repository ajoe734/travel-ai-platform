"""backlog ENG-02 acceptance: tenant A 不可讀寫 tenant B.

Exercises the RLS policies created in db/migrations/0001_tenancy_and_core_case.up.sql
through app_role (never the migration/admin role), both via the repository
layer and via a direct write that tries to claim a different tenant_id than
the session's app.tenant_id.
"""
from __future__ import annotations

import psycopg
import pytest

from db.repository import case_repository, db as repo_db


def test_tenant_a_cannot_read_tenant_b_case(conn, tenant_a, tenant_b, case_factory):
    case_b = case_factory(tenant_b)

    with repo_db.tenant_transaction(conn, tenant_a):
        row = case_repository.get_case(conn, tenant_id=tenant_b, case_id=case_b)

    assert row is None


def test_tenant_a_cannot_write_tenant_b_case(conn, tenant_a, tenant_b, case_factory):
    case_b = case_factory(tenant_b)

    with repo_db.tenant_transaction(conn, tenant_a):
        with pytest.raises(ValueError):
            case_repository.take_over_ownership(
                conn, tenant_id=tenant_b, case_id=case_b, new_owner={"actor_kind": "HUMAN_MERCHANT", "actor_id": "x"}
            )

    # Confirm tenant B's row was genuinely untouched, not just hidden from the caller.
    with repo_db.tenant_transaction(conn, tenant_b):
        row = case_repository.get_case(conn, tenant_id=tenant_b, case_id=case_b)
    assert row["owner_revision"] == 0


def test_tenant_a_cannot_insert_a_row_claiming_tenant_b(conn, tenant_a, tenant_b):
    with pytest.raises(psycopg.Error):
        with repo_db.tenant_transaction(conn, tenant_a):
            conn.execute(
                """
                INSERT INTO case_record (tenant_id, id, case_type, status, demand_revision, current_owner, next_step)
                VALUES (%s, gen_random_uuid(), 'BOOKING', 'OPEN', 1, '{}'::jsonb, '{}'::jsonb)
                """,
                (tenant_b,),
            )
