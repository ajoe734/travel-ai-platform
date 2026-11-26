"""backlog ENG-02 acceptance: 不能建立跨 tenant 父子參照.

db/migrations/0002_work_execution.up.sql ties execution_task.parent_task_id
to its own (tenant_id, work_id, id) via a composite FK specifically so a
parent from a different tenant (or a different Work) can never be attached,
even though parent_task_id itself carries no tenant_id column of its own.
"""
from __future__ import annotations

import hashlib
import uuid

import psycopg
import pytest

from db.repository import db as repo_db
from db.repository.errors import CrossTenantReferenceRejected, translate_integrity_error


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _create_root_task(conn, tenant_id, work_id, business_key):
    task_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        conn.execute(
            """
            INSERT INTO execution_task
                (tenant_id, id, work_id, kind, operation, business_key, request_hash,
                 request_snapshot, status, postcondition_version, postcondition)
            VALUES (%s, %s, %s, 'GROUP', 'booking.create', %s, %s, '{}'::jsonb, 'NEW', 'v1', '{}'::jsonb)
            """,
            (tenant_id, task_id, work_id, business_key, _sha256_hex(business_key)),
        )
    return task_id


def test_execution_task_cannot_adopt_a_parent_from_another_tenant(
    conn, tenant_a, tenant_b, case_factory, work_factory
):
    case_a = case_factory(tenant_a)
    work_a = work_factory(tenant_a, case_a)
    case_b = case_factory(tenant_b)
    work_b = work_factory(tenant_b, case_b)

    task_b = _create_root_task(conn, tenant_b, work_b, "booking-b-root")

    child_id = str(uuid.uuid4())
    with pytest.raises(psycopg.Error) as excinfo:
        with repo_db.tenant_transaction(conn, tenant_a):
            conn.execute(
                """
                INSERT INTO execution_task
                    (tenant_id, id, work_id, kind, parent_task_id, operation, business_key, request_hash,
                     request_snapshot, status, postcondition_version, postcondition)
                VALUES (%s, %s, %s, 'ACTION', %s, 'booking.create.step', 'booking-a-child', %s,
                        '{}'::jsonb, 'NEW', 'v1', '{}'::jsonb)
                """,
                (tenant_a, child_id, work_a, task_b, _sha256_hex("booking-a-child")),
            )

    translated = translate_integrity_error(excinfo.value, on_unique_violation=None)
    assert isinstance(translated, CrossTenantReferenceRejected)
