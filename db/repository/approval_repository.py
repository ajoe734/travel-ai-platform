"""Repository for DecisionRequest and the Approval family
(specs/domain/decision-request.schema.json, specs/domain/approval-record.schema.json).
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .errors import VersionConflict

_DECISION_COLUMNS = [
    "tenant_id", "id", "revision", "work_id", "decision_type", "status", "context_refs",
    "options", "selected_option_id", "impact_summary", "display_payload", "payload_hash",
    "canonicalization_version", "target_revision", "expires_at", "requested_role", "created_at",
]


def get_decision_request(
    conn: psycopg.Connection, *, tenant_id: str, decision_id: str, revision: int | None = None
) -> dict[str, Any] | None:
    """Latest revision by default; a specific ``revision`` reads that exact
    (immutable-content) row, e.g. to replay what a now-superseded revision
    displayed."""
    if revision is not None:
        row = conn.execute(
            f"""
            SELECT {", ".join(_DECISION_COLUMNS)} FROM decision_request
            WHERE tenant_id = %s AND id = %s AND revision = %s
            """,
            (tenant_id, decision_id, revision),
        ).fetchone()
    else:
        row = conn.execute(
            f"""
            SELECT {", ".join(_DECISION_COLUMNS)} FROM decision_request
            WHERE tenant_id = %s AND id = %s
            ORDER BY revision DESC LIMIT 1
            """,
            (tenant_id, decision_id),
        ).fetchone()
    return dict(zip(_DECISION_COLUMNS, row)) if row is not None else None


def create_decision_request(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    decision_id: str,
    revision: int,
    work_id: str,
    decision_type: str,
    options: list[dict[str, Any]],
    payload_hash: str,
    target_revision: int,
    expires_at: str,
    requested_role: str,
    display_payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO decision_request
            (tenant_id, id, revision, work_id, decision_type, status, options,
             payload_hash, canonicalization_version, target_revision, expires_at, requested_role, display_payload)
        VALUES (%s, %s, %s, %s, %s, 'PENDING', %s, %s, 'travel-canonical-json-v1', %s, %s, %s, %s)
        """,
        (
            tenant_id, decision_id, revision, work_id, decision_type, json.dumps(options),
            payload_hash, target_revision, expires_at, requested_role,
            json.dumps(display_payload) if display_payload is not None else None,
        ),
    )


def approve_decision(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    decision_id: str,
    reviewed_revision: int,
    selected_option_id: str,
    approval_id: str,
    approved_by: dict[str, Any],
    verified_actor_ref: str,
    approved_payload: dict[str, Any],
    payload_hash: str,
    scope_manifest: list[dict[str, Any]],
    approved_at: str,
    policy_version: str | None = None,
    expires_at: str | None = None,
) -> None:
    """Transition DecisionRequest PENDING -> APPROVED and write the immutable
    ApprovalRecord in one transaction (SD §4). A same-key/same-payload retry
    is the caller's responsibility to detect before calling this (via the
    idempotency_key_record table); a second distinct ApprovalRecord attempt
    against the same (decision_id, reviewed_revision) fails on the DB's own
    UNIQUE constraint (SD-A-03/SD-A-04).
    """
    row = conn.execute(
        """
        UPDATE decision_request
        SET status = 'APPROVED', selected_option_id = %s
        WHERE tenant_id = %s AND id = %s AND revision = %s AND status = 'PENDING'
        RETURNING id
        """,
        (selected_option_id, tenant_id, decision_id, reviewed_revision),
    ).fetchone()
    if row is None:
        raise VersionConflict(
            f"decision {decision_id!r} revision {reviewed_revision} is not PENDING (stale or already resolved)"
        )

    conn.execute(
        """
        INSERT INTO approval_record
            (tenant_id, id, decision_id, reviewed_revision, approved_by, verified_actor_ref,
             approved_payload, policy_version, canonicalization_version, payload_hash,
             scope_manifest, approved_at, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'travel-canonical-json-v1', %s, %s, %s, %s)
        """,
        (
            tenant_id, approval_id, decision_id, reviewed_revision, json.dumps(approved_by),
            verified_actor_ref, json.dumps(approved_payload), policy_version, payload_hash,
            json.dumps(scope_manifest), approved_at, expires_at,
        ),
    )


def reject_decision(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    decision_id: str,
    reviewed_revision: int,
    selected_option_id: str,
) -> None:
    """PENDING -> REJECTED, no ApprovalRecord (SD §4 命令表: reject "記拒絕
    理由、保留 Work 下一步"). Unlike approve_decision there is no immutable
    record to replay on a retry here; the caller's own Idempotency-Key
    handling is responsible for recognizing a resend before calling this.
    """
    row = conn.execute(
        """
        UPDATE decision_request
        SET status = 'REJECTED', selected_option_id = %s
        WHERE tenant_id = %s AND id = %s AND revision = %s AND status = 'PENDING'
        RETURNING id
        """,
        (selected_option_id, tenant_id, decision_id, reviewed_revision),
    ).fetchone()
    if row is None:
        raise VersionConflict(
            f"decision {decision_id!r} revision {reviewed_revision} is not PENDING (stale or already resolved)"
        )


def revoke_approval(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    revocation_id: str,
    approval_id: str,
    revoked_by: dict[str, Any],
    reason: str,
    effective_at: str,
) -> None:
    """Append-only revocation; never mutates approval_record (ADR 0003).
    A resend of the same revocation command is the caller's job to recognize
    via its own Idempotency-Key -- this function always appends a new row,
    matching SD §4's "撤回批准 ... 同鍵不能承諾已送出的動作已撤銷" (the
    idempotency guard lives at the API layer, not as a DB uniqueness rule,
    since a second *distinct* revocation reason for the same approval is a
    legitimate append, not a duplicate).
    """
    conn.execute(
        """
        INSERT INTO approval_revocation (tenant_id, id, approval_id, revoked_by, reason, effective_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (tenant_id, revocation_id, approval_id, json.dumps(revoked_by), reason, effective_at),
    )
