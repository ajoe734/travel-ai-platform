"""ENG-07 regression acceptance against the real Postgres repository path.

The suite uses the actual migration and repository functions.  It does not
mock out the ledger arithmetic or the complaint table, so it catches a schema
or tenant-scoping regression in the production persistence path.
"""
from __future__ import annotations

import hashlib
import json
import uuid

import pytest

from db.repository import credit_repository, db as repo_db, remedy_repository
from db.repository.errors import InsufficientCreditBalance


def _account(conn, tenant_id: str, *, currency: str = "TWD") -> str:
    account_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        conn.execute(
            """INSERT INTO credit_account (tenant_id, id, issuer, beneficiary_ref, currency)
                VALUES (%s, %s, 'merchant-credit-mock', %s, %s)""",
            (tenant_id, account_id, json.dumps({"subject": "customer-1"}), currency),
        )
    return account_id


def _grant(conn, tenant_id: str, account_id: str, *, amount: int = 100, key: str = "grant-1") -> dict:
    with repo_db.tenant_transaction(conn, tenant_id):
        return credit_repository.issue_credit_grant(
            conn, tenant_id=tenant_id, grant_id=str(uuid.uuid4()), ledger_entry_id=str(uuid.uuid4()),
            account_id=account_id, remedy_action_id=None, operation_key=key, amount_minor_units=amount,
            currency="TWD", terms_version="merchant-credit-terms-v1", scope={"channels": ["DIRECT"]},
            valid_from="2000-01-01T00:00:00Z", expires_at="2100-01-01T00:00:00Z",
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
