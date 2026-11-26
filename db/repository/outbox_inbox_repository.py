"""Transactional outbox/inbox (docs/sd/connector-result-and-reconciliation.md §6-7).

append_outbox_event must always be called inside the same transaction as the
business write it describes -- this module does not open its own
transaction, by design, so that invariant is visible at every call site via
db.tenant_transaction(...).
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

_INBOX_COLUMNS = [
    "tenant_id", "id", "connector_account_id", "environment", "producer", "source_event_id",
    "raw_hash", "raw_payload", "received_at", "processing_status", "processed_at",
]


def append_outbox_event(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    event_id: str,
    aggregate_type: str,
    aggregate_id: str,
    sequence: int,
    event_type: str,
    schema_version: str,
    payload: dict[str, Any],
    occurred_at: str,
    causation_id: str | None = None,
    correlation_id: str | None = None,
    resource_revision: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO outbox_event
            (tenant_id, id, aggregate_type, aggregate_id, sequence, event_type, schema_version,
             causation_id, correlation_id, resource_revision, payload, occurred_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            tenant_id, event_id, aggregate_type, aggregate_id, sequence, event_type, schema_version,
            causation_id, correlation_id, resource_revision, json.dumps(payload), occurred_at,
        ),
    )


def mark_outbox_published(conn: psycopg.Connection, *, tenant_id: str, event_id: str) -> None:
    conn.execute(
        """
        UPDATE outbox_event
        SET published_at = now(), dispatch_attempts = dispatch_attempts + 1
        WHERE tenant_id = %s AND id = %s
        """,
        (tenant_id, event_id),
    )


class InboxOutcome:
    CREATED = "created"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"

    def __init__(self, outcome: str, row: dict[str, Any] | None):
        self.outcome = outcome
        self.row = row


def record_inbound_event(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    event_id: str,
    connector_account_id: str | None,
    environment: str | None,
    producer: str,
    source_event_id: str,
    raw_hash: str,
    raw_payload: dict[str, Any],
) -> InboxOutcome:
    """SD §7: same id + same hash is an idempotent ACK; same id + different
    hash is quarantined (a conflict row is appended, the original inbox_event
    is left untouched) rather than updating the stored event in place.
    """
    existing = conn.execute(
        """
        SELECT tenant_id, id, connector_account_id, environment, producer, source_event_id,
               raw_hash, raw_payload, received_at, processing_status, processed_at
        FROM inbox_event
        WHERE tenant_id = %s AND connector_account_id IS NOT DISTINCT FROM %s
          AND environment IS NOT DISTINCT FROM %s
          AND producer = %s AND source_event_id = %s
        FOR UPDATE
        """,
        (tenant_id, connector_account_id, environment, producer, source_event_id),
    ).fetchone()
    if existing is not None:
        row = dict(zip(_INBOX_COLUMNS, existing))
        if row["raw_hash"] == raw_hash:
            return InboxOutcome(InboxOutcome.DUPLICATE, row)
        conn.execute(
            """
            INSERT INTO inbox_event_conflict (tenant_id, id, inbox_event_id, conflicting_hash, conflicting_payload)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (tenant_id, event_id, row["id"], raw_hash, json.dumps(raw_payload)),
        )
        conn.execute(
            "UPDATE inbox_event SET processing_status = 'QUARANTINED' WHERE tenant_id = %s AND id = %s",
            (tenant_id, row["id"]),
        )
        return InboxOutcome(InboxOutcome.CONFLICT, row)

    row = conn.execute(
        """
        INSERT INTO inbox_event
            (tenant_id, id, connector_account_id, environment, producer, source_event_id, raw_hash, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING tenant_id, id, connector_account_id, environment, producer, source_event_id,
                  raw_hash, raw_payload, received_at, processing_status, processed_at
        """,
        (tenant_id, event_id, connector_account_id, environment, producer, source_event_id, raw_hash, json.dumps(raw_payload)),
    ).fetchone()
    return InboxOutcome(InboxOutcome.CREATED, dict(zip(_INBOX_COLUMNS, row)))
