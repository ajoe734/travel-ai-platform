"""Refund reservation against a Payment's refundable balance
(docs/sd/credit-and-refund.md §5). This is the ENG-02 baseline described in
db/migrations/0004_quote_order_refund_baseline.md -- a merged Refund+
RefundReservation row, not the full ENG-07 ledger.

reserve_refund is the function the backlog ENG-02 acceptance criterion
"原子退款額度不因併發超退" is tested against (tests/db/test_refund_concurrency.py):
the balance check and the reservation increment happen in the same UPDATE
statement guarded by its WHERE clause, so the row lock Postgres takes for the
UPDATE is what makes two concurrent reservations against the same payment
serialize correctly -- no SELECT ... FOR UPDATE + separate UPDATE race, and
no advisory lock needed.
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .errors import IdempotencyConflict, InsufficientRefundBalance
from .rows import row_as_dict

_REFUND_COLUMNS = [
    "tenant_id", "id", "payment_id", "operation", "business_key", "amount_minor_units",
    "currency", "currency_scale_ref", "state", "connector_account_id", "environment",
    "provider_refund_id", "source_revision", "evidence", "created_at", "updated_at",
]


def reserve_refund(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    payment_id: str,
    refund_id: str,
    business_key: str,
    amount_minor_units: int,
    currency: str,
    currency_scale_ref: str,
) -> dict[str, Any]:
    """RESERVED-state refund row, drawing down Payment.reserved_amount_minor_units.

    Same business_key + same amount/currency is an idempotent replay
    (returns the existing row unchanged). Same business_key with a different
    amount/currency is rejected (IdempotencyConflict) rather than silently
    reusing the first reservation's amount. A fresh business_key that would
    push captured - refunded - reserved below zero is rejected
    (InsufficientRefundBalance) and the payment's counters are left
    untouched (the guarded UPDATE below updates zero rows, so there is
    nothing to roll back).
    """
    existing = conn.execute(
        """
        SELECT tenant_id, id, payment_id, operation, business_key, amount_minor_units,
               currency, currency_scale_ref, state, connector_account_id, environment,
               provider_refund_id, source_revision, evidence, created_at, updated_at
        FROM refund
        WHERE tenant_id = %s AND operation = 'refund' AND business_key = %s
        FOR UPDATE
        """,
        (tenant_id, business_key),
    ).fetchone()
    if existing is not None:
        row = row_as_dict(_REFUND_COLUMNS, existing)
        if (
            str(row["payment_id"]) != str(payment_id)
            or row["amount_minor_units"] != amount_minor_units
            or row["currency"] != currency
            or row["currency_scale_ref"] != currency_scale_ref
        ):
            raise IdempotencyConflict(
                f"business_key {business_key!r} already reserved against a different payment/amount/currency"
            )
        return row

    reserved = conn.execute(
        """
        UPDATE payment
        SET reserved_amount_minor_units = reserved_amount_minor_units + %s
        WHERE tenant_id = %s AND id = %s AND currency = %s
          AND %s > 0
          AND captured_amount_minor_units - refunded_amount_minor_units - reserved_amount_minor_units >= %s
        RETURNING id
        """,
        (amount_minor_units, tenant_id, payment_id, currency, amount_minor_units, amount_minor_units),
    ).fetchone()
    if reserved is None:
        raise InsufficientRefundBalance(
            f"payment {payment_id!r} has insufficient refundable balance for {amount_minor_units} {currency}"
        )

    row = conn.execute(
        """
        INSERT INTO refund
            (tenant_id, id, payment_id, operation, business_key, amount_minor_units, currency,
             currency_scale_ref, state)
        VALUES (%s, %s, %s, 'refund', %s, %s, %s, %s, 'RESERVED')
        RETURNING tenant_id, id, payment_id, operation, business_key, amount_minor_units,
                  currency, currency_scale_ref, state, connector_account_id, environment,
                  provider_refund_id, source_revision, evidence, created_at, updated_at
        """,
        (tenant_id, refund_id, payment_id, business_key, amount_minor_units, currency, currency_scale_ref),
    ).fetchone()
    return row_as_dict(_REFUND_COLUMNS, row)


def mark_refund_succeeded(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    refund_id: str,
    provider_refund_id: str,
    source_revision: str,
    evidence: dict[str, Any],
) -> None:
    """RESERVED/SUBMITTED/PENDING/UNKNOWN -> SUCCEEDED: moves the amount from
    reserved to refunded (SD §4 state table), in one statement so the two
    counters never observably disagree.
    """
    # Transition the refund row first, guarded by its current state, and
    # only move the payment's counters if this call actually performed the
    # transition -- otherwise a retry/duplicate call (refund already
    # SUCCEEDED) would move reserved -> refunded a second time with no
    # corresponding reservation left to draw down.
    transitioned = conn.execute(
        """
        UPDATE refund
        SET state = 'SUCCEEDED', provider_refund_id = %s, source_revision = %s, evidence = %s
        WHERE tenant_id = %s AND id = %s
          AND state IN ('RESERVED', 'SUBMITTED', 'PENDING', 'UNKNOWN')
        RETURNING payment_id, amount_minor_units
        """,
        (provider_refund_id, source_revision, json.dumps(evidence), tenant_id, refund_id),
    ).fetchone()
    if transitioned is None:
        return
    payment_id, amount_minor_units = transitioned
    conn.execute(
        """
        UPDATE payment
        SET reserved_amount_minor_units = reserved_amount_minor_units - %s,
            refunded_amount_minor_units = refunded_amount_minor_units + %s
        WHERE tenant_id = %s AND id = %s
        """,
        (amount_minor_units, amount_minor_units, tenant_id, payment_id),
    )


def release_refund_reservation(
    conn: psycopg.Connection, *, tenant_id: str, refund_id: str, terminal_state: str
) -> None:
    """RESERVED/SUBMITTED -> FAILED/CANCELLED with proven no side effect
    (SD §4: only release once there is no unresolved external action).
    UNKNOWN reservations must never be released through this path.
    """
    if terminal_state not in ("FAILED", "CANCELLED"):
        raise ValueError("release_refund_reservation only accepts FAILED or CANCELLED")
    # Same pattern as mark_refund_succeeded: transition refund first, and
    # only touch the payment's reserved counter if this call actually
    # performed the transition.
    transitioned = conn.execute(
        """
        UPDATE refund
        SET state = %s
        WHERE tenant_id = %s AND id = %s AND state IN ('RESERVED', 'SUBMITTED', 'PENDING')
        RETURNING payment_id, amount_minor_units
        """,
        (terminal_state, tenant_id, refund_id),
    ).fetchone()
    if transitioned is None:
        return
    payment_id, amount_minor_units = transitioned
    conn.execute(
        """
        UPDATE payment
        SET reserved_amount_minor_units = reserved_amount_minor_units - %s
        WHERE tenant_id = %s AND id = %s
        """,
        (amount_minor_units, tenant_id, payment_id),
    )
