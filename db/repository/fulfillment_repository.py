"""Repository for the QuoteSnapshot/Order rows the ENG-05 fulfillment
workflow needs (db/migrations/0004_quote_order_refund_baseline.up.sql;
specs/domain/order.schema.json). Full Quote/Order/Payment domains are ENG-02
scope; this module only adds the read/write paths ENG-02 did not need for
its own refund-concurrency acceptance (ENG-02's fixtures insert these two
tables with raw SQL directly in tests/db/conftest.py; this is the first
production call site).
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

_QUOTE_COLUMNS = [
    "tenant_id", "id", "case_id", "content", "content_hash",
    "total_amount_minor_units", "total_currency", "total_currency_scale_ref",
    "expires_at", "created_at",
]

_ORDER_COLUMNS = [
    "tenant_id", "id", "case_id", "quote_id", "status", "revision",
    "total_amount_minor_units", "total_currency", "total_currency_scale_ref",
    "supplier_booking_status", "supplier_booking_external_ref", "supplier_booking_connector_account_id",
    "supplier_booking_hold_expires_at", "payment_status", "payment_collector_account",
    "payment_external_transaction_id", "payment_captured_amount_minor_units", "payment_captured_currency",
    "created_at", "updated_at",
]


def create_quote_snapshot(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    quote_id: str,
    case_id: str,
    content: dict[str, Any],
    content_hash: str,
    total_amount_minor_units: str,
    total_currency: str,
    total_currency_scale_ref: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    row = conn.execute(
        f"""
        INSERT INTO quote_snapshot
            (tenant_id, id, case_id, content, content_hash, total_amount_minor_units,
             total_currency, total_currency_scale_ref, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING {", ".join(_QUOTE_COLUMNS)}
        """,
        (
            tenant_id, quote_id, case_id, json.dumps(content, default=str), content_hash,
            total_amount_minor_units, total_currency, total_currency_scale_ref, expires_at,
        ),
    ).fetchone()
    return dict(zip(_QUOTE_COLUMNS, row))


def get_quote_snapshot(conn: psycopg.Connection, *, tenant_id: str, quote_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_QUOTE_COLUMNS)} FROM quote_snapshot WHERE tenant_id = %s AND id = %s",
        (tenant_id, quote_id),
    ).fetchone()
    return dict(zip(_QUOTE_COLUMNS, row)) if row is not None else None


def create_order(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    order_id: str,
    case_id: str,
    quote_id: str,
    total_amount_minor_units: str,
    total_currency: str,
    total_currency_scale_ref: str,
) -> dict[str, Any]:
    """Order starts PENDING/NOT_REQUESTED/NOT_REQUESTED: the three domains
    (order/booking/payment) are independent even at creation (SA 04.2)."""
    row = conn.execute(
        f"""
        INSERT INTO order_record
            (tenant_id, id, case_id, quote_id, status, total_amount_minor_units, total_currency,
             total_currency_scale_ref, supplier_booking_status, payment_status)
        VALUES (%s, %s, %s, %s, 'PENDING', %s, %s, %s, 'NOT_REQUESTED', 'NOT_REQUESTED')
        RETURNING {", ".join(_ORDER_COLUMNS)}
        """,
        (tenant_id, order_id, case_id, quote_id, total_amount_minor_units, total_currency, total_currency_scale_ref),
    ).fetchone()
    return dict(zip(_ORDER_COLUMNS, row))


def get_order(conn: psycopg.Connection, *, tenant_id: str, order_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {', '.join(_ORDER_COLUMNS)} FROM order_record WHERE tenant_id = %s AND id = %s",
        (tenant_id, order_id),
    ).fetchone()
    return dict(zip(_ORDER_COLUMNS, row)) if row is not None else None


def update_order_supplier_booking(
    conn: psycopg.Connection,
    *,
    tenant_id: str,
    order_id: str,
    supplier_booking_status: str,
    external_ref: str | None = None,
    connector_account_id: str | None = None,
) -> dict[str, Any]:
    """Updates only the booking domain column (plus promoting Order.status
    PENDING -> CONFIRMED exactly when the booking is CONFIRMED); payment and
    order status otherwise never move as a side effect of this call (SA 04.2:
    三個來源狀態分開, never merged by one write)."""
    row = conn.execute(
        f"""
        UPDATE order_record
        SET supplier_booking_status = %s,
            supplier_booking_external_ref = COALESCE(%s, supplier_booking_external_ref),
            supplier_booking_connector_account_id = COALESCE(%s, supplier_booking_connector_account_id),
            status = CASE WHEN %s = 'CONFIRMED' AND status = 'PENDING' THEN 'CONFIRMED' ELSE status END
        WHERE tenant_id = %s AND id = %s
        RETURNING {", ".join(_ORDER_COLUMNS)}
        """,
        (
            supplier_booking_status, external_ref, connector_account_id, supplier_booking_status,
            tenant_id, order_id,
        ),
    ).fetchone()
    return dict(zip(_ORDER_COLUMNS, row))
