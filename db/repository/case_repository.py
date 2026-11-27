"""Repository for Case (specs/domain/case.schema.json).

Every method takes an already-open psycopg connection positioned inside a
db.tenant_transaction(conn, tenant_id) block; this module never opens its own
transaction so callers can compose multiple repository calls into one short
command transaction (SD work-execution-contract.md §6.2).
"""
from __future__ import annotations

import json
from typing import Any

import psycopg
from .rows import row_as_dict


def create_case(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    case_id: str,
    case_type: str,
    demand_revision: int,
    current_owner: dict[str, Any],
    next_step: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO case_record
            (tenant_id, id, case_type, status, demand_revision, current_owner, next_step)
        VALUES (%s, %s, %s, 'OPEN', %s, %s, %s)
        """,
        (tenant_id, case_id, case_type, demand_revision, json.dumps(current_owner), json.dumps(next_step)),
    )


def get_case(conn: psycopg.Connection, *, tenant_id: str, case_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT tenant_id, id, revision, case_type, status, demand_revision,
               owner_revision, current_owner, next_step, created_at, updated_at
        FROM case_record
        WHERE tenant_id = %s AND id = %s
        """,
        (tenant_id, case_id),
    ).fetchone()
    if row is None:
        return None
    columns = [
        "tenant_id", "id", "revision", "case_type", "status", "demand_revision",
        "owner_revision", "current_owner", "next_step", "created_at", "updated_at",
    ]
    return row_as_dict(columns, row)


def take_over_ownership(
    conn: psycopg.Connection, *, tenant_id: str, case_id: str, new_owner: dict[str, Any]
) -> int:
    """Atomically bump owner_revision (SD §6.3 真人接手原子增加 owner_revision).

    Returns the new owner_revision so callers can reject any in-flight AI
    turn whose request carried a stale on_behalf_of_case_owner_revision.
    """
    row = conn.execute(
        """
        UPDATE case_record
        SET owner_revision = owner_revision + 1, current_owner = %s
        WHERE tenant_id = %s AND id = %s
        RETURNING owner_revision
        """,
        (json.dumps(new_owner), tenant_id, case_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"case {tenant_id}/{case_id} not found")
    return row[0]
