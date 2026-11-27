"""ENG-07 regression acceptance against the real Postgres repository path.

The suite uses the actual migration and repository functions.  It does not
mock out the ledger arithmetic or the complaint table, so it catches a schema
or tenant-scoping regression in the production persistence path.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid

import psycopg
import pytest

from db.repository import credit_repository, db as repo_db, refund_repository, remedy_repository
from db.repository.errors import CreditTermsRequired, IdempotencyConflict, ImmutableRecordViolation, InsufficientCreditBalance, InsufficientRefundBalance, RefundRouteMismatch, translate_integrity_error


def _account(conn, tenant_id: str, *, currency: str = "TWD") -> str:
    account_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        conn.execute(
            """INSERT INTO credit_account (tenant_id, id, issuer, beneficiary_ref, currency)
                VALUES (%s, %s, 'merchant-credit-mock', %s, %s)""",
            (tenant_id, account_id, json.dumps({"subject": "customer-1"}), currency),
        )
    return account_id


def _grant(conn, tenant_id: str, account_id: str, *, amount: int = 100, key: str = "grant-1",
           valid_from: str = "2000-01-01T00:00:00Z", expires_at: str = "2100-01-01T00:00:00Z") -> dict:
    with repo_db.tenant_transaction(conn, tenant_id):
        return credit_repository.issue_credit_grant(
            conn, tenant_id=tenant_id, grant_id=str(uuid.uuid4()), ledger_entry_id=str(uuid.uuid4()),
            account_id=account_id, remedy_action_id=None, operation_key=key, amount_minor_units=amount,
            currency="TWD", terms_version="merchant-credit-terms-v1", scope={"channels": ["DIRECT"]},
            valid_from=valid_from, expires_at=expires_at,
            evidence={"environment": "MOCK", "grant_ref": key},
        )


def test_duplicate_credit_grant_does_not_increase_ledger_balance(conn, tenant_a):
    account_id = _account(conn, tenant_a)
    first = _grant(conn, tenant_a, account_id, key="compensation-issue-1")
    replay = _grant(conn, tenant_a, account_id, key="compensation-issue-1")
    assert replay["id"] == first["id"]
    with repo_db.tenant_transaction(conn, tenant_a):
        entries = conn.execute(
            "SELECT entry_type, amount_minor_units FROM credit_ledger_entry WHERE tenant_id = %s AND grant_id = %s",
            (tenant_a, first["id"]),
        ).fetchall()
    assert entries == [("ISSUE", 100)]


def test_credit_terms_and_replayed_grant_content_are_fenced(conn, tenant_a):
    account_id = _account(conn, tenant_a)
    with pytest.raises(CreditTermsRequired):
        with repo_db.tenant_transaction(conn, tenant_a):
            credit_repository.issue_credit_grant(
                conn, tenant_id=tenant_a, grant_id=str(uuid.uuid4()), ledger_entry_id=str(uuid.uuid4()),
                account_id=account_id, remedy_action_id=None, operation_key="terms-required", amount_minor_units=1,
                currency="TWD", terms_version="", scope={}, valid_from="2000-01-01T00:00:00Z",
                expires_at="2100-01-01T00:00:00Z", evidence={},
            )
    _grant(conn, tenant_a, account_id, key="content-fence")
    with pytest.raises(IdempotencyConflict):
        with repo_db.tenant_transaction(conn, tenant_a):
            credit_repository.issue_credit_grant(
                conn, tenant_id=tenant_a, grant_id=str(uuid.uuid4()), ledger_entry_id=str(uuid.uuid4()),
                account_id=account_id, remedy_action_id=None, operation_key="content-fence", amount_minor_units=100,
                currency="TWD", terms_version="merchant-credit-terms-v1", scope={"channels": ["OTA"]},
                valid_from="2000-01-01T00:00:00Z", expires_at="2100-01-01T00:00:00Z", evidence={},
            )


def test_credit_reservation_prevents_overuse_and_consumes_only_once(
    conn, tenant_a, case_factory, payment_chain_factory
):
    account_id = _account(conn, tenant_a)
    grant = _grant(conn, tenant_a, account_id, amount=100)
    case_id = case_factory(tenant_a)
    order_id = payment_chain_factory(tenant_a, case_id, 100)["order_id"]
    with repo_db.tenant_transaction(conn, tenant_a):
        held = credit_repository.reserve_credit_usage(
            conn, tenant_id=tenant_a, reservation_id=str(uuid.uuid4()), account_id=account_id,
            grant_id=grant["id"], order_id=order_id, operation_key="redeem-1", amount_minor_units=70,
            currency="TWD",
        )
    with pytest.raises(InsufficientCreditBalance):
        with repo_db.tenant_transaction(conn, tenant_a):
            credit_repository.reserve_credit_usage(
                conn, tenant_id=tenant_a, reservation_id=str(uuid.uuid4()), account_id=account_id,
                grant_id=grant["id"], order_id=order_id, operation_key="redeem-2", amount_minor_units=31,
                currency="TWD",
            )
    with repo_db.tenant_transaction(conn, tenant_a):
        credit_repository.consume_credit_usage(
            conn, tenant_id=tenant_a, reservation_id=held["id"], ledger_entry_id=str(uuid.uuid4()),
        )
        credit_repository.consume_credit_usage(
            conn, tenant_id=tenant_a, reservation_id=held["id"], ledger_entry_id=str(uuid.uuid4()),
        )
        redeem_count = conn.execute(
            "SELECT count(*) FROM credit_ledger_entry WHERE tenant_id = %s AND grant_id = %s AND entry_type = 'REDEEM'",
            (tenant_a, grant["id"]),
        ).fetchone()[0]
    assert redeem_count == 1

    with repo_db.tenant_transaction(conn, tenant_a):
        redemption_id = conn.execute(
            "SELECT id FROM credit_ledger_entry WHERE tenant_id = %s AND grant_id = %s AND entry_type = 'REDEEM'",
            (tenant_a, grant["id"]),
        ).fetchone()[0]
        credit_repository.reverse_credit_redemption(
            conn, tenant_id=tenant_a, redemption_entry_id=redemption_id, reversal_entry_id=str(uuid.uuid4()),
            reversal_business_key="cancel-reversal-1",
        )
        credit_repository.reverse_credit_redemption(
            conn, tenant_id=tenant_a, redemption_entry_id=redemption_id, reversal_entry_id=str(uuid.uuid4()),
            reversal_business_key="cancel-reversal-duplicate",
        )
        reversal_count = conn.execute(
            "SELECT count(*) FROM credit_ledger_entry WHERE tenant_id = %s AND reversal_of = %s",
            (tenant_a, redemption_id),
        ).fetchone()[0]
    assert reversal_count == 1


def _reserve_credit_in_thread(database_url, tenant_id, account_id, grant_id, order_id, key, barrier, results, index):
    connection = repo_db.connect(database_url)
    try:
        barrier.wait()
        with repo_db.tenant_transaction(connection, tenant_id):
            credit_repository.reserve_credit_usage(
                connection, tenant_id=tenant_id, reservation_id=str(uuid.uuid4()), account_id=account_id,
                grant_id=grant_id, order_id=order_id, operation_key=key, amount_minor_units=60, currency="TWD",
            )
        results[index] = "ok"
    except InsufficientCreditBalance:
        results[index] = "insufficient"
    finally:
        connection.close()


def test_concurrent_credit_reservations_cannot_overspend_grant(
    app_database_url, conn, tenant_a, case_factory, payment_chain_factory
):
    account_id = _account(conn, tenant_a)
    grant = _grant(conn, tenant_a, account_id, amount=100, key="concurrent-grant")
    case_id = case_factory(tenant_a)
    order_id = payment_chain_factory(tenant_a, case_id, 100)["order_id"]
    barrier = threading.Barrier(2)
    results = [None, None]
    threads = [
        threading.Thread(
            target=_reserve_credit_in_thread,
            args=(app_database_url, tenant_a, account_id, grant["id"], order_id, f"concurrent-redeem-{i}", barrier, results, i),
        )
        for i in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert set(results) == {"ok", "insufficient"}


def test_notification_failure_does_not_close_complaint(
    conn, tenant_a, case_factory, work_factory, payment_chain_factory
):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    chain = payment_chain_factory(tenant_a, case_id, 100)
    complaint_id = str(uuid.uuid4())
    preview_id = str(uuid.uuid4())
    action_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_a):
        conn.execute(
            """INSERT INTO complaint
                    (tenant_id, id, case_id, status, verification_state, requested_outcome)
                VALUES (%s, %s, %s, 'RESOLVING', 'VERIFIED', %s)""",
            (tenant_a, complaint_id, case_id, json.dumps({"category": "REFUND", "description": "test"})),
        )
        conn.execute(
            """INSERT INTO remedy_preview
                    (tenant_id, id, case_id, complaint_id, order_id, payment_id, work_id,
                     order_revision, policy_version, payload_hash, preview_payload, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1, 'refund-policy-v1', %s, '{}'::jsonb,
                        '2027-01-01T00:00:00Z')""",
            (tenant_a, preview_id, case_id, complaint_id, chain["order_id"], chain["payment_id"], work_id,
             hashlib.sha256(b"preview").hexdigest()),
        )
        conn.execute(
            """INSERT INTO remedy_action
                    (tenant_id, id, preview_id, complaint_id, work_id, selected_item_id, action_type,
                     business_key, authorization_ref, state)
                VALUES (%s, %s, %s, %s, %s, 'refund-1', 'REFUND', 'refund:notification-test', '{}'::jsonb,
                        'SUCCEEDED')""",
            (tenant_a, action_id, preview_id, complaint_id, work_id),
        )
        remedy_repository.record_remedy_notification(
            conn, tenant_id=tenant_a, notification_id=str(uuid.uuid4()), remedy_action_id=action_id,
            business_key="notify:refund-1", state="FAILED", evidence={"environment": "MOCK"},
        )
        status = conn.execute(
            "SELECT status, resolution FROM complaint WHERE tenant_id = %s AND id = %s",
            (tenant_a, complaint_id),
        ).fetchone()
    assert status == ("RESOLVING", None)
    with repo_db.tenant_transaction(conn, tenant_a):
        remedy_repository.resolve_complaint(
            conn, tenant_id=tenant_a, complaint_id=complaint_id, resolution_reason="explicit operator decision",
            unresolved_items=["customer follow-up remains"], customer_responded=False,
        )
        resolved = conn.execute(
            "SELECT status, resolution FROM complaint WHERE tenant_id = %s AND id = %s",
            (tenant_a, complaint_id),
        ).fetchone()
    assert resolved[0] == "RESOLVED"
    assert resolved[1]["customer_responded"] is False


def test_delivered_notification_is_monotonic_and_closeout_rejects_unlisted_active_remedy(
    conn, tenant_a, case_factory, work_factory, payment_chain_factory
):
    case_id = case_factory(tenant_a)
    work_id = work_factory(tenant_a, case_id)
    chain = payment_chain_factory(tenant_a, case_id, 100)
    complaint_id, preview_id, action_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_a):
        conn.execute("""INSERT INTO complaint (tenant_id, id, case_id, status, verification_state, requested_outcome)
                        VALUES (%s, %s, %s, 'RESOLVING', 'VERIFIED', '{}'::jsonb)""", (tenant_a, complaint_id, case_id))
        conn.execute("""INSERT INTO remedy_preview (tenant_id, id, case_id, complaint_id, order_id, work_id, order_revision,
                        policy_version, payload_hash, preview_payload, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 1, 'v1', %s, '{}'::jsonb, '2027-01-01T00:00:00Z')""",
                     (tenant_a, preview_id, case_id, complaint_id, chain["order_id"], work_id, hashlib.sha256(b"active").hexdigest()))
        conn.execute("""INSERT INTO remedy_action (tenant_id, id, preview_id, complaint_id, work_id, selected_item_id, action_type,
                        business_key, authorization_ref, state)
                        VALUES (%s, %s, %s, %s, %s, 'credit-1', 'CREDIT_GRANT', 'active-remedy', '{}'::jsonb, 'PENDING')""",
                     (tenant_a, action_id, preview_id, complaint_id, work_id))
        remedy_repository.record_remedy_notification(conn, tenant_id=tenant_a, notification_id=str(uuid.uuid4()),
            remedy_action_id=action_id, business_key="monotonic-delivery", state="DELIVERED", evidence={"delivered": True})
        remedy_repository.record_remedy_notification(conn, tenant_id=tenant_a, notification_id=str(uuid.uuid4()),
            remedy_action_id=action_id, business_key="monotonic-delivery", state="FAILED", evidence={"late": True})
        assert conn.execute("SELECT state FROM remedy_notification WHERE tenant_id=%s AND business_key='monotonic-delivery'", (tenant_a,)).fetchone()[0] == "DELIVERED"
        with pytest.raises(ValueError, match="unresolved_items"):
            remedy_repository.resolve_complaint(conn, tenant_id=tenant_a, complaint_id=complaint_id,
                resolution_reason="cannot close an active remedy silently", unresolved_items=[], customer_responded=None)
        remedy_repository.resolve_complaint(conn, tenant_id=tenant_a, complaint_id=complaint_id,
            resolution_reason="explicit closure with follow-up", unresolved_items=["Credit action still pending"], customer_responded=None)
        revision, resolution = conn.execute("SELECT revision, resolution FROM complaint WHERE tenant_id=%s AND id=%s", (tenant_a, complaint_id)).fetchone()
    assert revision == 2
    assert "T" in resolution["resolved_at"]


def test_revoke_reports_redeemed_disposition_and_rejects_held_usage(conn, tenant_a, case_factory, payment_chain_factory):
    account_id = _account(conn, tenant_a)
    grant = _grant(conn, tenant_a, account_id, amount=100, key="revoke-partial")
    order_id = payment_chain_factory(tenant_a, case_factory(tenant_a), 100)["order_id"]
    with repo_db.tenant_transaction(conn, tenant_a):
        held = credit_repository.reserve_credit_usage(conn, tenant_id=tenant_a, reservation_id=str(uuid.uuid4()), account_id=account_id,
            grant_id=grant["id"], order_id=order_id, operation_key="revoke-consumed", amount_minor_units=30, currency="TWD")
        credit_repository.consume_credit_usage(conn, tenant_id=tenant_a, reservation_id=held["id"], ledger_entry_id=str(uuid.uuid4()))
        result = credit_repository.revoke_unused_credit(conn, tenant_id=tenant_a, grant_id=grant["id"], ledger_entry_id=str(uuid.uuid4()), operation_key="revoke-partial")
        replay = credit_repository.revoke_unused_credit(conn, tenant_id=tenant_a, grant_id=grant["id"], ledger_entry_id=str(uuid.uuid4()), operation_key="revoke-partial")
    assert result["revoked_minor_units"] == 70
    assert result["already_redeemed_minor_units"] == 30
    assert replay["replayed"] is True
    full_grant = _grant(conn, tenant_a, account_id, key="revoke-full")
    with repo_db.tenant_transaction(conn, tenant_a):
        full = credit_repository.revoke_unused_credit(conn, tenant_id=tenant_a, grant_id=full_grant["id"],
            ledger_entry_id=str(uuid.uuid4()), operation_key="revoke-full")
    assert full["revoked_minor_units"] == 100 and full["already_redeemed_minor_units"] == 0
    fully_used = _grant(conn, tenant_a, account_id, key="revoke-fully-used")
    with repo_db.tenant_transaction(conn, tenant_a):
        usage = credit_repository.reserve_credit_usage(conn, tenant_id=tenant_a, reservation_id=str(uuid.uuid4()), account_id=account_id,
            grant_id=fully_used["id"], order_id=order_id, operation_key="revoke-fully-used-redeem", amount_minor_units=100, currency="TWD")
        credit_repository.consume_credit_usage(conn, tenant_id=tenant_a, reservation_id=usage["id"], ledger_entry_id=str(uuid.uuid4()))
        exhausted = credit_repository.revoke_unused_credit(conn, tenant_id=tenant_a, grant_id=fully_used["id"], ledger_entry_id=str(uuid.uuid4()), operation_key="fully-used-terminal")
    assert exhausted["disposition"] == "ALREADY_FULLY_REDEEMED" and exhausted["state"] == "REVOKED"
    other = _grant(conn, tenant_a, account_id, key="revoke-other")
    with repo_db.tenant_transaction(conn, tenant_a):
        with pytest.raises(IdempotencyConflict):
            credit_repository.revoke_unused_credit(conn, tenant_id=tenant_a, grant_id=other["id"], ledger_entry_id=str(uuid.uuid4()), operation_key="fully-used-terminal")
    held_grant = _grant(conn, tenant_a, account_id, key="revoke-held")
    with repo_db.tenant_transaction(conn, tenant_a):
        credit_repository.reserve_credit_usage(conn, tenant_id=tenant_a, reservation_id=str(uuid.uuid4()), account_id=account_id,
            grant_id=held_grant["id"], order_id=order_id, operation_key="revoke-held-use", amount_minor_units=10, currency="TWD")
        with pytest.raises(InsufficientCreditBalance):
            credit_repository.revoke_unused_credit(conn, tenant_id=tenant_a, grant_id=held_grant["id"], ledger_entry_id=str(uuid.uuid4()), operation_key="revoke-held")


def test_expiry_is_idempotent_and_held_redemption_blocks_expiry(conn, tenant_a, case_factory, payment_chain_factory):
    account_id = _account(conn, tenant_a)
    expired = _grant(conn, tenant_a, account_id, key="expire-normal", expires_at="2001-01-01T00:00:00Z")
    with repo_db.tenant_transaction(conn, tenant_a):
        result = credit_repository.expire_credit_grant(conn, tenant_id=tenant_a, grant_id=expired["id"], ledger_entry_id=str(uuid.uuid4()), operation_key="expire-normal")
        replay = credit_repository.expire_credit_grant(conn, tenant_id=tenant_a, grant_id=expired["id"], ledger_entry_id=str(uuid.uuid4()), operation_key="expire-normal")
    assert result["expired_minor_units"] == 100 and replay["expired_minor_units"] == 100 and replay["replayed"] is True
    held_grant = _grant(conn, tenant_a, account_id, key="expire-held", expires_at="2001-01-01T00:00:00Z")
    order_id = payment_chain_factory(tenant_a, case_factory(tenant_a), 100)["order_id"]
    with repo_db.tenant_transaction(conn, tenant_a):
        # A pre-expiry reservation models a checkout that remained UNKNOWN across expiry.
        conn.execute("UPDATE credit_grant SET expires_at = '2100-01-01T00:00:00Z' WHERE tenant_id=%s AND id=%s", (tenant_a, held_grant["id"]))
        credit_repository.reserve_credit_usage(conn, tenant_id=tenant_a, reservation_id=str(uuid.uuid4()), account_id=account_id,
            grant_id=held_grant["id"], order_id=order_id, operation_key="expire-held-use", amount_minor_units=10, currency="TWD")
        conn.execute("UPDATE credit_grant SET expires_at = '2001-01-01T00:00:00Z' WHERE tenant_id=%s AND id=%s", (tenant_a, held_grant["id"]))
        with pytest.raises(InsufficientCreditBalance):
            credit_repository.expire_credit_grant(conn, tenant_id=tenant_a, grant_id=held_grant["id"], ledger_entry_id=str(uuid.uuid4()), operation_key="expire-held")


def test_refund_can_only_be_submitted_to_original_payment_route(
    conn, tenant_a, case_factory, payment_chain_factory
):
    case_id = case_factory(tenant_a)
    chain = payment_chain_factory(tenant_a, case_id, 100)
    refund_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_a):
        refund_repository.reserve_refund(
            conn, tenant_id=tenant_a, payment_id=chain["payment_id"], refund_id=refund_id,
            business_key="refund-original-route", amount_minor_units=50, currency="TWD",
            currency_scale_ref="iso4217-minor-unit-2",
        )
    with pytest.raises(RefundRouteMismatch):
        with repo_db.tenant_transaction(conn, tenant_a):
            refund_repository.submit_refund_to_original_collector(
                conn, tenant_id=tenant_a, refund_id=refund_id, collector_account="platform-default",
                connector_account_id=str(uuid.uuid4()), environment="MOCK",
            )
    with repo_db.tenant_transaction(conn, tenant_a):
        connector_id = str(uuid.uuid4())
        refund_repository.submit_refund_to_original_collector(
            conn, tenant_id=tenant_a, refund_id=refund_id, collector_account="mock-collector",
            connector_account_id=connector_id, environment="MOCK",
        )
        # A same-state replay must retain the exact connector fence, not just
        # accept any later caller because the refund is already SUBMITTED.
        refund_repository.submit_refund_to_original_collector(
            conn, tenant_id=tenant_a, refund_id=refund_id, collector_account="mock-collector",
            connector_account_id=connector_id, environment="MOCK",
        )
        with pytest.raises(RefundRouteMismatch):
            refund_repository.submit_refund_to_original_collector(
                conn, tenant_id=tenant_a, refund_id=refund_id, collector_account="mock-collector",
                connector_account_id=str(uuid.uuid4()), environment="MOCK",
            )
        state = conn.execute(
            "SELECT state FROM refund WHERE tenant_id = %s AND id = %s", (tenant_a, refund_id)
        ).fetchone()[0]
    assert state == "SUBMITTED"


def test_unknown_refund_holds_balance_and_terminal_state_is_not_a_route_mismatch(
    conn, tenant_a, case_factory, payment_chain_factory
):
    chain = payment_chain_factory(tenant_a, case_factory(tenant_a), 100)
    first_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_a):
        refund_repository.reserve_refund(conn, tenant_id=tenant_a, payment_id=chain["payment_id"], refund_id=first_id,
            business_key="unknown-holds", amount_minor_units=60, currency="TWD", currency_scale_ref="iso4217-minor-unit-2")
        refund_repository.submit_refund_to_original_collector(conn, tenant_id=tenant_a, refund_id=first_id,
            collector_account="mock-collector", connector_account_id=str(uuid.uuid4()), environment="MOCK")
        refund_repository.mark_refund_awaiting_reconciliation(conn, tenant_id=tenant_a, refund_id=first_id,
            state="UNKNOWN", evidence={"timeout": True})
        with pytest.raises(InsufficientRefundBalance):
            refund_repository.reserve_refund(conn, tenant_id=tenant_a, payment_id=chain["payment_id"], refund_id=str(uuid.uuid4()),
                business_key="unknown-overrun", amount_minor_units=50, currency="TWD", currency_scale_ref="iso4217-minor-unit-2")
        with pytest.raises(ValueError, match="cannot be submitted"):
            refund_repository.submit_refund_to_original_collector(conn, tenant_id=tenant_a, refund_id=first_id,
                collector_account="mock-collector", connector_account_id=str(uuid.uuid4()), environment="MOCK")


def test_eng07_schema_enforces_rls_immutable_ledger_and_composite_grant_identity(conn, admin_database_url, tenant_a, tenant_b):
    account_id = _account(conn, tenant_a)
    grant = _grant(conn, tenant_a, account_id, key="schema-guard")
    with repo_db.tenant_transaction(conn, tenant_a):
        protected = conn.execute(
            """SELECT relrowsecurity, relforcerowsecurity FROM pg_class
                 WHERE oid = 'credit_ledger_entry'::regclass"""
        ).fetchone()
        assert protected == (True, True)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute("UPDATE credit_ledger_entry SET amount_minor_units = 1 WHERE tenant_id = %s AND grant_id = %s",
                             (tenant_a, grant["id"]))
    with psycopg.connect(admin_database_url, autocommit=True) as admin_conn:
        with pytest.raises(psycopg.Error) as excinfo:
            admin_conn.execute("DELETE FROM credit_ledger_entry WHERE tenant_id = %s AND grant_id = %s", (tenant_a, grant["id"]))
        assert isinstance(translate_integrity_error(excinfo.value), ImmutableRecordViolation)
    with repo_db.tenant_transaction(conn, tenant_b):
        assert conn.execute("SELECT id FROM credit_ledger_entry WHERE tenant_id = %s", (tenant_a,)).fetchone() is None
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO credit_account (tenant_id, id, issuer, beneficiary_ref, currency) VALUES (%s, %s, 'x', '{}'::jsonb, 'TWD')", (tenant_a, str(uuid.uuid4())))
    with repo_db.tenant_transaction(conn, tenant_a):
        # The FK includes account/currency; changing either cannot attach a
        # ledger row to a grant merely because its UUID belongs to this tenant.
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    """INSERT INTO credit_ledger_entry
                            (tenant_id, id, account_id, grant_id, entry_type, amount_minor_units, currency,
                             business_key, source_operation, occurred_at)
                        VALUES (%s, %s, %s, %s, 'ISSUE', 1, 'USD', 'wrong-composite', '{}'::jsonb, clock_timestamp())""",
                    (tenant_a, str(uuid.uuid4()), account_id, grant["id"]),
                )
