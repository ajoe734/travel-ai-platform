"""Repository for ExecutionTask/ExecutionAttempt (specs/domain/execution-task.schema.json,
specs/domain/execution-attempt.schema.json).

create_execution_task implements SD work-execution-contract.md §6.1's two-tier
dedupe for the *business* key: same (tenant_id, operation, business_key) with
the same request_hash returns the existing task (idempotent replay); a
different request_hash is rejected with IDEMPOTENCY_CONFLICT rather than
silently overwriting what a different client retry believed it was creating
(backlog ENG-02 acceptance: "operation key 相同但 payload 不同會拒絕").
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .errors import IdempotencyConflict

_COLUMNS = [
    "tenant_id", "id", "work_id", "kind", "parent_task_id", "operation", "business_key",
    "request_hash", "request_snapshot", "status", "revision", "owner_revision",
    "postcondition_version", "postcondition", "authorization_use_id", "manifest_item_id",
    "deadline", "next_run_at", "created_at", "updated_at",
]


def create_execution_task(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    task_id: str,
    work_id: str,
    kind: str,
    operation: str,
    business_key: str,
    request_hash: str,
    request_snapshot: dict[str, Any],
    postcondition_version: str,
    postcondition: dict[str, Any],
    parent_task_id: str | None = None,
) -> dict[str, Any]:
    existing = conn.execute(
        """
        SELECT tenant_id, id, work_id, kind, parent_task_id, operation, business_key,
               request_hash, request_snapshot, status, revision, owner_revision,
               postcondition_version, postcondition, authorization_use_id, manifest_item_id,
               deadline, next_run_at, created_at, updated_at
        FROM execution_task
        WHERE tenant_id = %s AND operation = %s AND business_key = %s
        FOR UPDATE
        """,
        (tenant_id, operation, business_key),
    ).fetchone()
    if existing is not None:
        row = dict(zip(_COLUMNS, existing))
        if row["request_hash"] != request_hash:
            raise IdempotencyConflict(
                f"business_key {business_key!r} already bound to a different request_hash"
            )
        return row

    row = conn.execute(
        """
        INSERT INTO execution_task
            (tenant_id, id, work_id, kind, parent_task_id, operation, business_key,
             request_hash, request_snapshot, status, revision, owner_revision,
             postcondition_version, postcondition)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'NEW', 1, 0, %s, %s)
        RETURNING tenant_id, id, work_id, kind, parent_task_id, operation, business_key,
                  request_hash, request_snapshot, status, revision, owner_revision,
                  postcondition_version, postcondition, authorization_use_id, manifest_item_id,
                  deadline, next_run_at, created_at, updated_at
        """,
        (
            tenant_id, task_id, work_id, kind, parent_task_id, operation, business_key,
            request_hash, json.dumps(request_snapshot), postcondition_version, json.dumps(postcondition),
        ),
    ).fetchone()
    return dict(zip(_COLUMNS, row))


def record_attempt(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    attempt_id: str,
    task_id: str,
    attempt_no: int,
    attempt_kind: str,
    fence_token: int,
    request_hash: str,
    started_at: str,
    request_ref: str | None = None,
) -> None:
    """Append one ExecutionAttempt. A retry increments attempt_no; it never
    allocates a new ExecutionTask (ADR 0001)."""
    conn.execute(
        """
        INSERT INTO execution_attempt
            (tenant_id, id, task_id, attempt_no, attempt_kind, fence_token, request_hash, request_ref, started_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (tenant_id, attempt_id, task_id, attempt_no, attempt_kind, fence_token, request_hash, request_ref, started_at),
    )


def append_observation(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    attempt_id: str,
    sequence: int,
    observed_at: str,
    transport_result: str,
    outcome: str,
    external_ref: str | None = None,
    evidence_ref: str | None = None,
) -> None:
    """Append one observation. A timeout followed by a late result is two
    rows, never an overwrite of the first (SD §2)."""
    conn.execute(
        """
        INSERT INTO execution_attempt_observation
            (tenant_id, attempt_id, sequence, observed_at, transport_result, external_ref, evidence_ref, outcome)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (tenant_id, attempt_id, sequence, observed_at, transport_result, external_ref, evidence_ref, outcome),
    )
