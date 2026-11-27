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

from .errors import IdempotencyConflict, VersionConflict

_COLUMNS = [
    "tenant_id", "id", "work_id", "kind", "parent_task_id", "operation", "business_key",
    "request_hash", "request_snapshot", "status", "revision", "owner_revision",
    "postcondition_version", "postcondition", "authorization_use_id", "manifest_item_id",
    "deadline", "next_run_at", "created_at", "updated_at",
]

_LEASE_COLUMNS = _COLUMNS + ["lease_holder", "lease_fence_token", "lease_until"]


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
    deadline: str | None = None,
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
             postcondition_version, postcondition, deadline)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'NEW', 1, 0, %s, %s, %s)
        RETURNING tenant_id, id, work_id, kind, parent_task_id, operation, business_key,
                  request_hash, request_snapshot, status, revision, owner_revision,
                  postcondition_version, postcondition, authorization_use_id, manifest_item_id,
                  deadline, next_run_at, created_at, updated_at
        """,
        (
            tenant_id, task_id, work_id, kind, parent_task_id, operation, business_key,
            # A snapshot may carry identifiers read back by psycopg as
            # uuid.UUID (for example notification order_id/work_id).  JSONB
            # persists the canonical wire representation, never driver
            # objects.
            request_hash, json.dumps(request_snapshot, default=str), postcondition_version,
            json.dumps(postcondition, default=str),
            deadline,
        ),
    ).fetchone()
    return dict(zip(_COLUMNS, row))


def next_attempt_no(conn: psycopg.Connection, *, tenant_id: str, task_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(attempt_no), 0) + 1 FROM execution_attempt WHERE tenant_id = %s AND task_id = %s",
        (tenant_id, task_id),
    ).fetchone()
    return row[0]


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


def get_execution_task(conn: psycopg.Connection, *, tenant_id: str, task_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"""
        SELECT {", ".join(_LEASE_COLUMNS)}
        FROM execution_task
        WHERE tenant_id = %s AND id = %s
        """,
        (tenant_id, task_id),
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_LEASE_COLUMNS, row))


def get_execution_task_by_business_key(
    conn: psycopg.Connection, *, tenant_id: str, operation: str, business_key: str
) -> dict[str, Any] | None:
    row = conn.execute(
        f"""
        SELECT {", ".join(_LEASE_COLUMNS)}
        FROM execution_task
        WHERE tenant_id = %s AND operation = %s AND business_key = %s
        """,
        (tenant_id, operation, business_key),
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_LEASE_COLUMNS, row))


def list_tasks_for_work(conn: psycopg.Connection, *, tenant_id: str, work_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT {", ".join(_LEASE_COLUMNS)}
        FROM execution_task
        WHERE tenant_id = %s AND work_id = %s
        ORDER BY created_at
        """,
        (tenant_id, work_id),
    ).fetchall()
    return [dict(zip(_LEASE_COLUMNS, row)) for row in rows]


def list_tasks_due_for_reconciliation(
    conn: psycopg.Connection, *, tenant_id: str, now: str
) -> list[dict[str, Any]]:
    """Tasks a scheduler should tick: WAITING/UNKNOWN whose next_run_at has
    arrived (or was never set) and whose lease is free (SD §5 reconciliation
    algorithm step 2 "取得該 task 的 reconciliation lease/fence")."""
    rows = conn.execute(
        f"""
        SELECT {", ".join(_LEASE_COLUMNS)}
        FROM execution_task
        WHERE tenant_id = %s AND status IN ('WAITING', 'UNKNOWN')
          AND (next_run_at IS NULL OR next_run_at <= %s)
          AND (lease_until IS NULL OR lease_until <= %s)
        ORDER BY created_at
        """,
        (tenant_id, now, now),
    ).fetchall()
    return [dict(zip(_LEASE_COLUMNS, row)) for row in rows]


def list_tasks_overdue_for_escalation(
    conn: psycopg.Connection, *, tenant_id: str, now: str
) -> list[dict[str, Any]]:
    """Tasks past their deadline while still WAITING/UNKNOWN (SD §5 step 6:
    "deadline 超過建立 Escalation、保留核對責任；不自動變 FAILED")."""
    rows = conn.execute(
        f"""
        SELECT {", ".join(_LEASE_COLUMNS)}
        FROM execution_task
        WHERE tenant_id = %s AND status IN ('WAITING', 'UNKNOWN')
          AND deadline IS NOT NULL AND deadline <= %s
        ORDER BY created_at
        """,
        (tenant_id, now),
    ).fetchall()
    return [dict(zip(_LEASE_COLUMNS, row)) for row in rows]


def acquire_lease(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    task_id: str,
    holder: str,
    now: str,
    lease_until: str,
) -> dict[str, Any] | None:
    """Atomically claim the task's lease and bump its fence (SD §6.3: "每次
    取租約原子增加 fence_token"). Returns None -- without raising -- when the
    lease is currently held by someone else and has not expired yet (lost the
    race / contention), so a scheduler can simply skip this task this tick
    rather than treat contention as an error.

    ``now``/``lease_until`` are caller-supplied ISO timestamps (not the DB's
    wall clock), matching this codebase's convention of passing explicit
    times through business logic so tests stay deterministic.
    """
    row = conn.execute(
        f"""
        UPDATE execution_task
        SET lease_holder = %s,
            lease_fence_token = COALESCE(lease_fence_token, 0) + 1,
            lease_until = %s
        WHERE tenant_id = %s AND id = %s
          AND (lease_until IS NULL OR lease_until <= %s)
        RETURNING {", ".join(_LEASE_COLUMNS)}
        """,
        (holder, lease_until, tenant_id, task_id, now),
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_LEASE_COLUMNS, row))


def claim_new_task_for_dispatch(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    task_id: str,
    holder: str,
    now: str,
    lease_until: str,
) -> dict[str, Any] | None:
    """Atomically turn a still-NEW task into EXECUTING and obtain its fence.

    This is deliberately one conditional write: cancellation and dispatch
    race on the same ``status='NEW'`` predicate, so a cancelled task cannot
    acquire a lease or receive a durable DISPATCH attempt afterwards.
    """
    row = conn.execute(
        f"""
        UPDATE execution_task
        SET status = 'EXECUTING', revision = revision + 1,
            lease_holder = %s,
            lease_fence_token = COALESCE(lease_fence_token, 0) + 1,
            lease_until = %s
        WHERE tenant_id = %s AND id = %s AND status = 'NEW'
          AND (lease_until IS NULL OR lease_until <= %s)
        RETURNING {", ".join(_LEASE_COLUMNS)}
        """,
        (holder, lease_until, tenant_id, task_id, now),
    ).fetchone()
    return dict(zip(_LEASE_COLUMNS, row)) if row is not None else None


def release_lease(conn: psycopg.Connection, *, tenant_id: str, task_id: str, fence_token: int) -> None:
    """Release a lease this holder still owns. A no-op (zero rows) if the
    fence has already moved on -- an expired holder releasing late must never
    clear a newer holder's lease out from under it."""
    conn.execute(
        """
        UPDATE execution_task
        SET lease_holder = NULL, lease_until = NULL
        WHERE tenant_id = %s AND id = %s AND lease_fence_token = %s
        """,
        (tenant_id, task_id, fence_token),
    )


_STATUS_COLUMNS = _COLUMNS


def update_task_status(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    task_id: str,
    expected_revision: int,
    new_status: str,
    fence_token: int | None = None,
    next_run_at: str | None = None,
    deadline: str | None = None,
) -> dict[str, Any]:
    """Transition ExecutionTask.status, guarded by optimistic revision and
    (when supplied) the lease fence a dispatch/reconcile attempt was made
    under -- a worker whose lease has since been superseded must not be able
    to write a status change (SD §6.3: "過期 worker 不得建立新外部動作").

    ``deadline`` only *sets* a deadline the first time (COALESCE keeps any
    existing value when omitted); ``next_run_at`` is always overwritten
    (NULL clears a schedule, e.g. once a task reaches a terminal state).
    """
    row = conn.execute(
        f"""
        UPDATE execution_task
        SET status = %s, revision = revision + 1,
            next_run_at = %s, deadline = COALESCE(%s, deadline)
        WHERE tenant_id = %s AND id = %s AND revision = %s
          AND (%s::bigint IS NULL OR lease_fence_token = %s)
        RETURNING {", ".join(_STATUS_COLUMNS)}
        """,
        (
            new_status, next_run_at, deadline,
            tenant_id, task_id, expected_revision,
            fence_token, fence_token,
        ),
    ).fetchone()
    if row is None:
        raise VersionConflict(
            f"execution_task {task_id!r} is not at revision {expected_revision} "
            f"under fence {fence_token!r} (stale lease, concurrent update, or wrong revision)"
        )
    return dict(zip(_STATUS_COLUMNS, row))


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
