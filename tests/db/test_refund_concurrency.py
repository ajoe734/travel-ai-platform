"""backlog ENG-02 acceptance: 原子退款額度不因併發超退.

db/repository/refund_repository.py:reserve_refund folds the balance check and
the reservation increment into one UPDATE ... WHERE statement so the row
lock Postgres takes for that UPDATE serializes two concurrent reservations
against the same payment. This test proves that under real concurrency (two
threads, two separate connections, started via a barrier) rather than just
reading the code.
"""
from __future__ import annotations

import threading
import uuid

import psycopg
import pytest

from db.repository import db as repo_db, refund_repository
from db.repository.errors import InsufficientRefundBalance


def _reserve_in_thread(database_url, tenant_id, payment_id, amount, business_key, barrier, results, index):
    connection = repo_db.connect(database_url)
    try:
        barrier.wait()
        with repo_db.tenant_transaction(connection, tenant_id):
            row = refund_repository.reserve_refund(
                connection,
                tenant_id=tenant_id,
                payment_id=payment_id,
                refund_id=str(uuid.uuid4()),
                business_key=business_key,
                amount_minor_units=amount,
                currency="TWD",
                currency_scale_ref="iso4217-minor-unit-2",
            )
        results[index] = ("ok", row)
    except InsufficientRefundBalance:
        results[index] = ("insufficient", None)
    finally:
        connection.close()


def test_two_concurrent_reservations_cannot_both_exceed_the_captured_amount(
    app_database_url, conn, tenant_a, case_factory, payment_chain_factory
):
    case_id = case_factory(tenant_a)
    chain = payment_chain_factory(tenant_a, case_id, 100)
    payment_id = chain["payment_id"]

    barrier = threading.Barrier(2)
    results = [None, None]
    threads = [
        threading.Thread(
            target=_reserve_in_thread,
            args=(app_database_url, tenant_a, payment_id, 60, f"refund-concurrent-{i}", barrier, results, i),
        )
        for i in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    outcomes = {result[0] for result in results}
    assert outcomes == {"ok", "insufficient"}, f"expected exactly one success, got {results}"

    with repo_db.tenant_transaction(conn, tenant_a):
        row = conn.execute(
            """
            SELECT captured_amount_minor_units, refunded_amount_minor_units, reserved_amount_minor_units
            FROM payment WHERE tenant_id = %s AND id = %s
            """,
            (tenant_a, payment_id),
        ).fetchone()

    captured, refunded, reserved = row
    assert reserved == 60
    assert captured - refunded - reserved >= 0


def test_a_fresh_business_key_that_would_overdraw_is_rejected_without_mutating_the_payment(
    conn, tenant_a, case_factory, payment_chain_factory
):
    case_id = case_factory(tenant_a)
    chain = payment_chain_factory(tenant_a, case_id, 50)
    payment_id = chain["payment_id"]

    with pytest.raises(InsufficientRefundBalance):
        with repo_db.tenant_transaction(conn, tenant_a):
            refund_repository.reserve_refund(
                conn,
                tenant_id=tenant_a,
                payment_id=payment_id,
                refund_id=str(uuid.uuid4()),
                business_key="refund-too-big",
                amount_minor_units=51,
                currency="TWD",
                currency_scale_ref="iso4217-minor-unit-2",
            )

    with repo_db.tenant_transaction(conn, tenant_a):
        row = conn.execute(
            "SELECT reserved_amount_minor_units FROM payment WHERE tenant_id = %s AND id = %s",
            (tenant_a, payment_id),
        ).fetchone()
    assert row[0] == 0
