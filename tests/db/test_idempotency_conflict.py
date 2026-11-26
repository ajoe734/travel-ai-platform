"""backlog ENG-02 acceptance: operation key 相同但 payload 不同會拒絕.

execution_repository.create_execution_task implements the two-tier dedupe
from docs/sd/work-execution-contract.md §6.1: same (tenant_id, operation,
business_key) + same request_hash replays the existing task; the same key
with a different request_hash must be rejected, never silently rebound to
the new payload.
"""
from __future__ import annotations

import hashlib
import uuid

import pytest

from db.repository import db as repo_db, execution_repository
from db.repository.errors import IdempotencyConflict


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_same_business_key_same_hash_replays(conn, tenant_a, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    business_key = "supplier-booking-001"
    request_hash = _sha256_hex("payload-v1")

    with repo_db.tenant_transaction(conn, tenant_a):
        first = execution_repository.create_execution_task(
            conn,
            tenant_id=tenant_a,
            task_id=str(uuid.uuid4()),
            work_id=work_id,
            kind="ACTION",
            operation="supplier.booking.create",
            business_key=business_key,
            request_hash=request_hash,
            request_snapshot={"amount": 100},
            postcondition_version="v1",
            postcondition={},
        )

    with repo_db.tenant_transaction(conn, tenant_a):
        replay = execution_repository.create_execution_task(
            conn,
            tenant_id=tenant_a,
            task_id=str(uuid.uuid4()),  # a fresh client-generated id must not matter
            work_id=work_id,
            kind="ACTION",
            operation="supplier.booking.create",
            business_key=business_key,
            request_hash=request_hash,
            request_snapshot={"amount": 100},
            postcondition_version="v1",
            postcondition={},
        )

    assert replay["id"] == first["id"]


def test_same_business_key_different_hash_is_rejected(conn, tenant_a, case_factory, work_factory):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    business_key = "supplier-booking-002"

    with repo_db.tenant_transaction(conn, tenant_a):
        execution_repository.create_execution_task(
            conn,
            tenant_id=tenant_a,
            task_id=str(uuid.uuid4()),
            work_id=work_id,
            kind="ACTION",
            operation="supplier.booking.create",
            business_key=business_key,
            request_hash=_sha256_hex("payload-v1"),
            request_snapshot={"amount": 100},
            postcondition_version="v1",
            postcondition={},
        )

    with pytest.raises(IdempotencyConflict):
        with repo_db.tenant_transaction(conn, tenant_a):
            execution_repository.create_execution_task(
                conn,
                tenant_id=tenant_a,
                task_id=str(uuid.uuid4()),
                work_id=work_id,
                kind="ACTION",
                operation="supplier.booking.create",
                business_key=business_key,
                request_hash=_sha256_hex("payload-v2-different-amount"),
                request_snapshot={"amount": 999},
                postcondition_version="v1",
                postcondition={},
            )
