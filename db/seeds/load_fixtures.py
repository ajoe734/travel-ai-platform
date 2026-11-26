#!/usr/bin/env python3
"""ENG-02 test seed data.

Loads a small, explicitly non-production dataset (two TEST-environment
tenants, one Case each) for manual exploration and for the "測試種子與非正式
資料標記" backlog ENG-02 deliverable. Every tenant this script creates has
environment='TEST' (see migrations/0001 tenant.environment CHECK); it must
never be pointed at a tenant row with environment='PRODUCTION'. It does not
seed the full Work/ExecutionTask/DecisionRequest/ApprovalRecord/Order/
Payment chain -- tests/db/conftest.py's factories build that chain for the
acceptance suite instead.

Usage:
    DATABASE_URL=postgresql://... python3 db/seeds/load_fixtures.py
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import psycopg  # noqa: E402

from db.repository import db as repo_db  # noqa: E402
from db.repository import case_repository  # noqa: E402

FIXED_NAMESPACE = uuid.UUID("00000000-0000-4000-8000-000000000000")


def fixture_id(label: str) -> str:
    return str(uuid.uuid5(FIXED_NAMESPACE, label))


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    with psycopg.connect(database_url, autocommit=True) as admin_conn:
        for label in ("eng02-fixture-tenant-a", "eng02-fixture-tenant-b"):
            tenant_id = fixture_id(label)
            admin_conn.execute(
                """
                INSERT INTO tenant (id, name, environment)
                VALUES (%s, %s, 'TEST')
                ON CONFLICT (id) DO NOTHING
                """,
                (tenant_id, label),
            )

    conn = repo_db.connect(database_url)
    tenant_a = fixture_id("eng02-fixture-tenant-a")
    case_id = fixture_id("eng02-fixture-case-a-1")

    with repo_db.tenant_transaction(conn, tenant_a):
        existing = case_repository.get_case(conn, tenant_id=tenant_a, case_id=case_id)
        if existing is None:
            case_repository.create_case(
                conn,
                tenant_id=tenant_a,
                case_id=case_id,
                case_type="BOOKING",
                demand_revision=1,
                current_owner={"actor_kind": "AI_AGENT", "actor_id": fixture_id("eng02-fixture-ai-agent")},
                next_step={"summary": "等待客戶確認報價 (fixture data, 非正式交易)"},
            )
            print(f"seeded case {case_id} under tenant {tenant_a}")
        else:
            print(f"case {case_id} already present under tenant {tenant_a}; skipping")
    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
