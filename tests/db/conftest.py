"""Shared fixtures for the ENG-02 database acceptance suite.

These tests require a real Postgres instance (the migrations create actual
roles, RLS policies and triggers -- there is no in-memory substitute that
would exercise the same guarantees). Point ENG02_ADMIN_DATABASE_URL (or
DATABASE_URL) at an admin-privileged connection to an empty/disposable
database; the session fixture below runs db/migrate.py against it and
creates a throwaway LOGIN role the tests connect as.

See db/README.md "本機無法執行的部分" for why this VM's sandbox cannot run
this suite (no outbound network to install psycopg, no local Postgres), and
.github/workflows/repository-validation.yml for the hosted CI job that does.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from db.repository import db as repo_db  # noqa: E402
from db.repository import case_repository  # noqa: E402

ADMIN_DATABASE_URL = os.environ.get("ENG02_ADMIN_DATABASE_URL") or os.environ.get("DATABASE_URL")
# Fixed, non-secret credential for a role that only ever exists inside a
# disposable CI/test database; never used against a real deployment.
_APP_USER_PASSWORD = "eng02-test-fixture-only"  # noqa: S105


def _require_admin_url() -> str:
    if not ADMIN_DATABASE_URL:
        pytest.skip(
            "ENG02_ADMIN_DATABASE_URL/DATABASE_URL is not set; the db/ acceptance "
            "suite requires a real Postgres instance and cannot run in this sandbox."
        )
    return ADMIN_DATABASE_URL


@pytest.fixture(scope="session")
def admin_database_url() -> str:
    return _require_admin_url()


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema(admin_database_url: str):
    """Run every ENG-02 migration once, then create the LOGIN role tests
    connect as (app_role itself is NOLOGIN, matching production posture)."""
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "db" / "migrate.py"), "upgrade", "--database-url", admin_database_url],
        check=True,
    )
    with psycopg.connect(admin_database_url, autocommit=True) as conn:
        conn.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eng02_test_app_user') THEN
                    CREATE ROLE eng02_test_app_user LOGIN PASSWORD %(password)s;
                END IF;
            END
            $$;
            """,
            {"password": _APP_USER_PASSWORD},
        )
        conn.execute("GRANT app_role TO eng02_test_app_user")
    yield


@pytest.fixture()
def app_database_url(admin_database_url: str) -> str:
    override = os.environ.get("ENG02_APP_DATABASE_URL")
    if override:
        return override
    parts = urlsplit(admin_database_url)
    netloc = f"eng02_test_app_user:{_APP_USER_PASSWORD}@{parts.hostname}:{parts.port or 5432}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


@pytest.fixture()
def conn(app_database_url: str):
    connection = repo_db.connect(app_database_url)
    yield connection
    connection.close()


def make_tenant(admin_database_url: str, *, environment: str = "TEST") -> str:
    tenant_id = str(uuid.uuid4())
    with psycopg.connect(admin_database_url, autocommit=True) as admin_conn:
        admin_conn.execute(
            "INSERT INTO tenant (id, name, environment) VALUES (%s, %s, %s)",
            (tenant_id, f"eng02-test-{tenant_id}", environment),
        )
    return tenant_id


@pytest.fixture()
def tenant_a(admin_database_url: str) -> str:
    return make_tenant(admin_database_url)


@pytest.fixture()
def tenant_b(admin_database_url: str) -> str:
    return make_tenant(admin_database_url)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_case(conn: psycopg.Connection, tenant_id: str) -> str:
    case_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        case_repository.create_case(
            conn,
            tenant_id=tenant_id,
            case_id=case_id,
            case_type="BOOKING",
            demand_revision=1,
            current_owner={"actor_kind": "AI_AGENT", "actor_id": str(uuid.uuid4())},
            next_step={"summary": "test fixture"},
        )
    return case_id


def _make_work(conn: psycopg.Connection, tenant_id: str, case_id: str) -> str:
    work_id = str(uuid.uuid4())
    principal = json.dumps({"actor_kind": "AI_AGENT", "actor_id": str(uuid.uuid4())})
    with repo_db.tenant_transaction(conn, tenant_id):
        conn.execute(
            """
            INSERT INTO work
                (tenant_id, id, case_id, work_type, objective, completion_contract_version,
                 completion_conditions, principal, status)
            VALUES (%s, %s, %s, 'BOOKING', 'test fixture objective', 'v1', '{}'::jsonb, %s, 'RUNNING')
            """,
            (tenant_id, work_id, case_id, principal),
        )
    return work_id


def _make_payment_chain(conn: psycopg.Connection, tenant_id: str, case_id: str, *, captured_amount: int) -> dict:
    """quote_snapshot -> order_record -> payment, enough to exercise refund_repository."""
    quote_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    payment_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        conn.execute(
            """
            INSERT INTO quote_snapshot
                (tenant_id, id, case_id, content, content_hash, total_amount_minor_units,
                 total_currency, total_currency_scale_ref)
            VALUES (%s, %s, %s, '{}'::jsonb, %s, %s, 'TWD', 'iso4217-minor-unit-2')
            """,
            (tenant_id, quote_id, case_id, sha256_hex(quote_id), str(captured_amount)),
        )
        conn.execute(
            """
            INSERT INTO order_record
                (tenant_id, id, case_id, quote_id, status, total_amount_minor_units, total_currency,
                 total_currency_scale_ref, supplier_booking_status, payment_status)
            VALUES (%s, %s, %s, %s, 'CONFIRMED', %s, 'TWD', 'iso4217-minor-unit-2', 'CONFIRMED', 'CAPTURED')
            """,
            (tenant_id, order_id, case_id, quote_id, str(captured_amount)),
        )
        conn.execute(
            """
            INSERT INTO payment
                (tenant_id, id, order_id, collector_account, environment, currency, currency_scale_ref,
                 captured_amount_minor_units)
            VALUES (%s, %s, %s, 'mock-collector', 'MOCK', 'TWD', 'iso4217-minor-unit-2', %s)
            """,
            (tenant_id, payment_id, order_id, captured_amount),
        )
    return {"quote_id": quote_id, "order_id": order_id, "payment_id": payment_id}


@pytest.fixture()
def case_factory(conn):
    """Callable(tenant_id) -> case_id, bound to the `conn` fixture's connection."""
    return lambda tenant_id: _make_case(conn, tenant_id)


@pytest.fixture()
def work_factory(conn):
    """Callable(tenant_id, case_id) -> work_id."""
    return lambda tenant_id, case_id: _make_work(conn, tenant_id, case_id)


@pytest.fixture()
def payment_chain_factory(conn):
    """Callable(tenant_id, case_id, captured_amount=...) -> {quote_id, order_id, payment_id}."""
    return lambda tenant_id, case_id, captured_amount: _make_payment_chain(
        conn, tenant_id, case_id, captured_amount=captured_amount
    )
