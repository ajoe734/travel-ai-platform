"""Repository for Work and its owned records (specs/domain/work.schema.json):
WorkPlan, WorkContext, CompletionEvidence, Escalation, WorkEvent.

``update_work_status`` always writes every status-conditional jsonb column
(waiting_input/waiting_decision/waiting_external/completion_record/
partial_summary/failure/cancellation) in the same statement, clearing the
ones that do not apply to ``new_status`` -- this is what lets a single
UPDATE satisfy work.schema.json's "exactly one of these is present, matching
status" invariant (also enforced again at the row level by
db/migrations/0002's CHECK constraints) without a prior read-then-patch
race on the other six columns.
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .errors import VersionConflict

_WORK_COLUMNS = [
    "tenant_id", "id", "case_id", "work_type", "objective", "completion_contract_version",
    "completion_conditions", "principal", "authority_context", "status", "revision",
    "waiting_input", "waiting_decision", "waiting_external", "completion_record",
    "partial_summary", "failure", "cancellation", "created_at", "updated_at",
]

# Maps a terminal/waiting status to the one jsonb column it requires
# (work.schema.json's allOf; db/migrations/0002's *_matches_status CHECKs).
# RUNNING/VERIFYING/DRAFT require none of these seven columns.
_STATUS_FIELD = {
    "WAITING_INPUT": "waiting_input",
    "WAITING_DECISION": "waiting_decision",
    "WAITING_EXTERNAL": "waiting_external",
    "COMPLETED": "completion_record",
    "PARTIAL": "partial_summary",
    "FAILED": "failure",
    "CANCELLED": "cancellation",
}
_STATUS_PAYLOAD_FIELDS = (
    "waiting_input", "waiting_decision", "waiting_external",
    "completion_record", "partial_summary", "failure", "cancellation",
)


def create_work(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    work_id: str,
    case_id: str,
    work_type: str,
    objective: str,
    completion_contract_version: str,
    completion_conditions: list[dict[str, Any]],
    principal: dict[str, Any],
    status: str = "RUNNING",
    authority_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a Work directly into ``status`` (default RUNNING: the caller
    has already confirmed objective/principal/completion conditions/access
    scope, satisfying SD §3's DRAFT->RUNNING precondition before this call).
    ``status`` must be one with no required waiting_*/completion_record/...
    column (RUNNING/VERIFYING/DRAFT); use update_work_status for any status
    in _STATUS_FIELD."""
    if status in _STATUS_FIELD:
        raise ValueError(f"create_work cannot create status={status!r} directly; use update_work_status after create")
    row = conn.execute(
        """
        INSERT INTO work
            (tenant_id, id, case_id, work_type, objective, completion_contract_version,
             completion_conditions, principal, authority_context, status, revision)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
        RETURNING tenant_id, id, case_id, work_type, objective, completion_contract_version,
                  completion_conditions, principal, authority_context, status, revision,
                  waiting_input, waiting_decision, waiting_external, completion_record,
                  partial_summary, failure, cancellation, created_at, updated_at
        """,
        (
            tenant_id, work_id, case_id, work_type, objective, completion_contract_version,
            json.dumps(completion_conditions, default=str), json.dumps(principal, default=str),
            json.dumps(authority_context, default=str) if authority_context is not None else None,
            status,
        ),
    ).fetchone()
    return dict(zip(_WORK_COLUMNS, row))


def get_work(conn: psycopg.Connection, *, tenant_id: str, work_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"""
        SELECT {", ".join(_WORK_COLUMNS)}
        FROM work
        WHERE tenant_id = %s AND id = %s
        """,
        (tenant_id, work_id),
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_WORK_COLUMNS, row))


def update_work_status(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    work_id: str,
    expected_revision: int,
    new_status: str,
    completion_conditions: list[dict[str, Any]] | None = None,
    **status_payload: dict[str, Any],
) -> dict[str, Any]:
    """Transition Work.status, guarded by optimistic revision. Exactly the
    jsonb column ``_STATUS_FIELD[new_status]`` (if any) must be supplied in
    ``status_payload``; every other status-conditional column is cleared.
    ``completion_conditions``, when given, replaces the full array (callers
    pass the whole updated list, e.g. marking one condition satisfied) --
    independent of ``new_status``, since the schema carries it on every
    status. work.schema.json's ``execution_task_refs`` has no column on the
    0002 `work` table (ExecutionTask.work_id is the authoritative link);
    callers read execution_repository.list_tasks_for_work instead of a
    projection on Work.
    """
    required = _STATUS_FIELD.get(new_status)
    if required is not None and required not in status_payload:
        raise ValueError(f"status {new_status!r} requires status_payload[{required!r}]")
    extra = set(status_payload) - ({required} if required else set())
    if extra:
        raise ValueError(f"status {new_status!r} does not accept {sorted(extra)}")

    values = {
        field: json.dumps(status_payload[field], default=str) if field in status_payload else None
        for field in _STATUS_PAYLOAD_FIELDS
    }
    row = conn.execute(
        f"""
        UPDATE work
        SET status = %s, revision = revision + 1,
            waiting_input = %s, waiting_decision = %s, waiting_external = %s,
            completion_record = %s, partial_summary = %s, failure = %s, cancellation = %s,
            completion_conditions = COALESCE(%s, completion_conditions)
        WHERE tenant_id = %s AND id = %s AND revision = %s
        RETURNING {", ".join(_WORK_COLUMNS)}
        """,
        (
            new_status,
            *[values[f] for f in _STATUS_PAYLOAD_FIELDS],
            json.dumps(completion_conditions, default=str) if completion_conditions is not None else None,
            tenant_id, work_id, expected_revision,
        ),
    ).fetchone()
    if row is None:
        raise VersionConflict(f"work {work_id!r} is not at revision {expected_revision}")
    return dict(zip(_WORK_COLUMNS, row))


def create_work_plan(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    work_id: str,
    plan_revision: int,
    steps: list[dict[str, Any]],
    planner_version: str,
    context_refs: list[dict[str, Any]] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO work_plan (tenant_id, work_id, plan_revision, steps, planner_version, context_refs)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (tenant_id, work_id, plan_revision, json.dumps(steps, default=str), planner_version, json.dumps(context_refs or [], default=str)),
    )


def create_work_context(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    context_id: str,
    work_id: str,
    ref_kind: str,
    target_id: str,
    purpose: str,
    target_revision: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO work_context
            (tenant_id, id, work_id, ref_kind, target_tenant_id, target_id, target_revision, purpose)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (tenant_id, context_id, work_id, ref_kind, tenant_id, target_id, target_revision, purpose),
    )


def append_work_event(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    work_id: str,
    event_type: str,
    schema_version: str,
    payload: dict[str, Any],
    occurred_at: str,
    causation_id: str | None = None,
    correlation_id: str | None = None,
    resource_revision: int | None = None,
) -> int:
    """Append one WorkEvent, computing the next sequence from the existing
    append-only history (SD §2: "sequence 唯一，只追加"). Returns the
    sequence written. A concurrent append for the same work_id can collide on
    (tenant_id, work_id, sequence) and must retry -- this vertical slice
    does not hold a row lock across the SELECT+INSERT because every caller
    in this package already serializes WorkEvent appends through the same
    tenant_transaction that performs the work.status transition they
    describe."""
    row = conn.execute(
        """
        INSERT INTO work_event
            (tenant_id, work_id, sequence, event_type, schema_version,
             causation_id, correlation_id, resource_revision, payload, occurred_at)
        SELECT %s, %s, COALESCE(MAX(sequence), 0) + 1, %s, %s, %s, %s, %s, %s, %s
        FROM work_event WHERE tenant_id = %s AND work_id = %s
        RETURNING sequence
        """,
        (
            tenant_id, work_id, event_type, schema_version,
            causation_id, correlation_id, resource_revision, json.dumps(payload, default=str), occurred_at,
            tenant_id, work_id,
        ),
    ).fetchone()
    return row[0]


def create_completion_evidence(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    evidence_id: str,
    work_id: str,
    evidence_type: str,
    environment: str,
    external_ref: str,
    observed_at: str,
    verifier_version: str,
    task_id: str | None = None,
    source_account: str | None = None,
    source_revision: str | None = None,
    verified_at: str | None = None,
    payload_ref: str | None = None,
    payload_hash: str | None = None,
) -> dict[str, Any]:
    """Insert one immutable CompletionEvidence row (SD §7: a Work's
    completion_record must reference real evidence like this, never just an
    HTTP 200)."""
    row = conn.execute(
        """
        INSERT INTO completion_evidence
            (tenant_id, id, work_id, task_id, evidence_type, source_account, environment,
             external_ref, source_revision, observed_at, verified_at, payload_ref, payload_hash,
             verifier_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING tenant_id, id, work_id, task_id, evidence_type, source_account, environment,
                  external_ref, source_revision, observed_at, verified_at, payload_ref, payload_hash,
                  verifier_version, created_at
        """,
        (
            tenant_id, evidence_id, work_id, task_id, evidence_type, source_account, environment,
            external_ref, source_revision, observed_at, verified_at, payload_ref, payload_hash,
            verifier_version,
        ),
    ).fetchone()
    columns = [
        "tenant_id", "id", "work_id", "task_id", "evidence_type", "source_account", "environment",
        "external_ref", "source_revision", "observed_at", "verified_at", "payload_ref", "payload_hash",
        "verifier_version", "created_at",
    ]
    return dict(zip(columns, row))


_ESCALATION_COLUMNS = [
    "tenant_id", "id", "work_id", "task_id", "reason", "owner", "due_at", "status",
    "resolution_ref", "created_at", "updated_at",
]


def get_open_escalation_for_task(
    conn: psycopg.Connection, *, tenant_id: str, task_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        f"""
        SELECT {", ".join(_ESCALATION_COLUMNS)}
        FROM escalation
        WHERE tenant_id = %s AND task_id = %s AND status = 'OPEN'
        """,
        (tenant_id, task_id),
    ).fetchone()
    if row is None:
        return None
    return dict(zip(_ESCALATION_COLUMNS, row))


def create_escalation_if_absent(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    escalation_id: str,
    work_id: str,
    task_id: str,
    reason: str,
    owner: dict[str, Any],
    due_at: str,
) -> tuple[dict[str, Any], bool]:
    """Idempotent: a task already carrying an OPEN escalation returns it
    unchanged rather than opening a second one every time a scheduler tick
    re-observes the same overdue task (SD §5 step 6, SD-C-12: "UNKNOWN 及保留
    不清掉" -- but also never duplicated)."""
    existing = get_open_escalation_for_task(conn, tenant_id=tenant_id, task_id=task_id)
    if existing is not None:
        return existing, False
    row = conn.execute(
        """
        INSERT INTO escalation (tenant_id, id, work_id, task_id, reason, owner, due_at, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'OPEN')
        RETURNING tenant_id, id, work_id, task_id, reason, owner, due_at, status,
                  resolution_ref, created_at, updated_at
        """,
        (tenant_id, escalation_id, work_id, task_id, reason, json.dumps(owner, default=str), due_at),
    ).fetchone()
    return dict(zip(_ESCALATION_COLUMNS, row)), True


def resolve_escalation(
    conn: psycopg.Connection, *, tenant_id: str, escalation_id: str, resolution_ref: str
) -> None:
    conn.execute(
        """
        UPDATE escalation SET status = 'RESOLVED', resolution_ref = %s
        WHERE tenant_id = %s AND id = %s AND status = 'OPEN'
        """,
        (resolution_ref, tenant_id, escalation_id),
    )
