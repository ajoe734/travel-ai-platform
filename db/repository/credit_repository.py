"""ENG-07 Credit ledger and usage-reservation repository.

All functions run inside ``tenant_transaction``.  They intentionally use the
same account-before-grant locking order for every amount-consuming operation;
the short transaction ends before any external checkout or notification I/O.
"""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .errors import CreditTermsRequired, IdempotencyConflict, InsufficientCreditBalance


def issue_credit_grant(
    conn: psycopg.Connection, *, tenant_id: str, grant_id: str, ledger_entry_id: str,
    account_id: str, remedy_action_id: str | None, operation_key: str,
    amount_minor_units: int, currency: str, terms_version: str, scope: dict[str, Any],
    valid_from: str, expires_at: str, evidence: dict[str, Any],
) -> dict[str, Any]:
    """Issue exactly one locally-managed Credit grant and immutable ISSUE row.

    A missing terms version is deliberately not treated as an implicit merchant
    policy.  Replaying the same operation returns the original grant; changing
    account, money, or terms under that business key is rejected.
    """
    if not terms_version.strip():
        raise CreditTermsRequired("a merchant Credit terms_version is required before issuing Credit")
    existing = conn.execute(
        """SELECT id, account_id, issued_amount_minor_units, currency, terms_version,
                  state, provider_grant_id, evidence
             FROM credit_grant WHERE tenant_id = %s AND grant_operation_key = %s FOR UPDATE""",
        (tenant_id, operation_key),
    ).fetchone()
    if existing is not None:
        row = dict(zip(("id", "account_id", "issued_amount_minor_units", "currency", "terms_version",
                        "state", "provider_grant_id", "evidence"), existing))
        if (str(row["account_id"]) != str(account_id) or row["issued_amount_minor_units"] != amount_minor_units
                or row["currency"] != currency or row["terms_version"] != terms_version):
            raise IdempotencyConflict("Credit grant operation key is already bound to different terms or money")
        return row
    account = conn.execute(
        "SELECT id FROM credit_account WHERE tenant_id = %s AND id = %s AND currency = %s FOR UPDATE",
        (tenant_id, account_id, currency),
    ).fetchone()
    if account is None:
        raise InsufficientCreditBalance("Credit account does not exist for this tenant/currency")
    row = conn.execute(
        """INSERT INTO credit_grant
                (tenant_id, id, account_id, remedy_action_id, grant_operation_key,
                 issued_amount_minor_units, currency, terms_version, scope, valid_from,
                 expires_at, state, evidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', %s)
            RETURNING id, account_id, issued_amount_minor_units, currency, terms_version,
                      state, provider_grant_id, evidence""",
        (tenant_id, grant_id, account_id, remedy_action_id, operation_key, amount_minor_units, currency,
         terms_version, json.dumps(scope), valid_from, expires_at, json.dumps(evidence)),
    ).fetchone()
    conn.execute(
        """INSERT INTO credit_ledger_entry
                (tenant_id, id, account_id, grant_id, entry_type, amount_minor_units, currency,
                 business_key, source_operation, occurred_at)
            VALUES (%s, %s, %s, %s, 'ISSUE', %s, %s, %s, %s, clock_timestamp())""",
        (tenant_id, ledger_entry_id, account_id, grant_id, amount_minor_units, currency,
         f"issue:{operation_key}", json.dumps({"grant_operation_key": operation_key})),
    )
    return dict(zip(("id", "account_id", "issued_amount_minor_units", "currency", "terms_version",
                     "state", "provider_grant_id", "evidence"), row))


def reserve_credit_usage(
    conn: psycopg.Connection, *, tenant_id: str, reservation_id: str, account_id: str,
    grant_id: str, order_id: str, operation_key: str, amount_minor_units: int, currency: str,
) -> dict[str, Any]:
    """Atomically hold available Credit; PENDING/UNKNOWN callers retain HELD.

    The balance is ledger-derived rather than copied into a mutable counter:
    ISSUE and REDEEM_REVERSAL add value, while REDEEM/EXPIRE/REVOKE consume it.
    Existing HELD reservations reduce the available amount before a checkout is
    dispatched, preventing two concurrent checkouts from overspending a grant.
    """
    existing = conn.execute(
        """SELECT id, account_id, grant_id, order_id, amount_minor_units, currency, state
             FROM credit_usage_reservation
             WHERE tenant_id = %s AND redeem_operation_key = %s FOR UPDATE""",
        (tenant_id, operation_key),
    ).fetchone()
    if existing is not None:
        row = dict(zip(("id", "account_id", "grant_id", "order_id", "amount_minor_units", "currency", "state"), existing))
        if (str(row["account_id"]) != str(account_id) or str(row["grant_id"]) != str(grant_id)
                or str(row["order_id"]) != str(order_id) or row["amount_minor_units"] != amount_minor_units
                or row["currency"] != currency):
            raise IdempotencyConflict("Credit redemption key is already bound to different usage")
        return row
    # Global ENG-07 amount-operation lock order: account before grant.
    account = conn.execute(
        "SELECT id FROM credit_account WHERE tenant_id = %s AND id = %s AND currency = %s FOR UPDATE",
        (tenant_id, account_id, currency),
    ).fetchone()
    grant = conn.execute(
        """SELECT id FROM credit_grant
             WHERE tenant_id = %s AND id = %s AND account_id = %s AND currency = %s
               AND state = 'ACTIVE' AND valid_from <= clock_timestamp() AND expires_at > clock_timestamp()
             FOR UPDATE""",
        (tenant_id, grant_id, account_id, currency),
    ).fetchone()
    if account is None or grant is None or amount_minor_units <= 0:
        raise InsufficientCreditBalance("Credit account/grant is not usable for this redemption")
    ledger_balance = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN entry_type IN ('ISSUE', 'REDEEM_REVERSAL')
                                     THEN amount_minor_units ELSE -amount_minor_units END), 0)
             FROM credit_ledger_entry WHERE tenant_id = %s AND grant_id = %s""",
        (tenant_id, grant_id),
    ).fetchone()[0]
    held = conn.execute(
        """SELECT COALESCE(SUM(amount_minor_units), 0) FROM credit_usage_reservation
             WHERE tenant_id = %s AND grant_id = %s AND state = 'HELD'""",
        (tenant_id, grant_id),
    ).fetchone()[0]
    if ledger_balance - held < amount_minor_units:
        raise InsufficientCreditBalance("Credit grant has insufficient available balance")
    row = conn.execute(
        """INSERT INTO credit_usage_reservation
                (tenant_id, id, account_id, grant_id, order_id, redeem_operation_key,
                 amount_minor_units, currency, state)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'HELD')
            RETURNING id, account_id, grant_id, order_id, amount_minor_units, currency, state""",
        (tenant_id, reservation_id, account_id, grant_id, order_id, operation_key, amount_minor_units, currency),
    ).fetchone()
    return dict(zip(("id", "account_id", "grant_id", "order_id", "amount_minor_units", "currency", "state"), row))


def consume_credit_usage(
    conn: psycopg.Connection, *, tenant_id: str, reservation_id: str, ledger_entry_id: str,
) -> None:
    """Commit a HELD usage exactly once after a verified redemption result."""
    row = conn.execute(
        """UPDATE credit_usage_reservation SET state = 'CONSUMED'
             WHERE tenant_id = %s AND id = %s AND state = 'HELD'
             RETURNING account_id, grant_id, amount_minor_units, currency, redeem_operation_key""",
        (tenant_id, reservation_id),
    ).fetchone()
    if row is None:
        return
    account_id, grant_id, amount, currency, operation_key = row
    conn.execute(
        """INSERT INTO credit_ledger_entry
                (tenant_id, id, account_id, grant_id, entry_type, amount_minor_units, currency,
                 business_key, source_operation, occurred_at)
            VALUES (%s, %s, %s, %s, 'REDEEM', %s, %s, %s, %s, clock_timestamp())""",
        (tenant_id, ledger_entry_id, account_id, grant_id, amount, currency,
         f"redeem:{operation_key}", json.dumps({"reservation_id": str(reservation_id)})),
    )


def release_credit_usage(conn: psycopg.Connection, *, tenant_id: str, reservation_id: str) -> None:
    """Release only a proven-no-effect HELD redemption; UNKNOWN must stay HELD."""
    conn.execute(
        """UPDATE credit_usage_reservation SET state = 'RELEASED'
             WHERE tenant_id = %s AND id = %s AND state = 'HELD'""",
        (tenant_id, reservation_id),
    )


def reverse_credit_redemption(
    conn: psycopg.Connection, *, tenant_id: str, redemption_entry_id: str,
    reversal_entry_id: str, reversal_business_key: str,
) -> None:
    """Append one reversal for a verified cancelled redemption, never re-ISSUE.

    ``UNIQUE(tenant_id, reversal_of)`` plus the targeted ``ON CONFLICT`` is
    the database backstop against concurrent/replayed cancellation webhooks.
    Ledger rows are immutable and ``app_role`` deliberately has no UPDATE
    privilege, so this reads the original without a row-lock clause.  The
    original REDEEM remains in the evidence trail and is offset by a linked
    REDEEM_REVERSAL.
    """
    original = conn.execute(
        """SELECT account_id, grant_id, amount_minor_units, currency, entry_type
             FROM credit_ledger_entry WHERE tenant_id = %s AND id = %s""",
        (tenant_id, redemption_entry_id),
    ).fetchone()
    if original is None or original[4] != "REDEEM":
        raise ValueError("Credit reversal must reference an existing REDEEM entry")
    account_id, grant_id, amount, currency, _ = original
    conn.execute(
        """INSERT INTO credit_ledger_entry
                (tenant_id, id, account_id, grant_id, entry_type, amount_minor_units, currency,
                 business_key, source_operation, reversal_of, occurred_at)
            VALUES (%s, %s, %s, %s, 'REDEEM_REVERSAL', %s, %s, %s, %s, %s, clock_timestamp())
            ON CONFLICT (tenant_id, reversal_of) DO NOTHING""",
        (tenant_id, reversal_entry_id, account_id, grant_id, amount, currency, reversal_business_key,
         json.dumps({"redemption_entry_id": str(redemption_entry_id)}), redemption_entry_id),
    )


def revoke_unused_credit(
    conn: psycopg.Connection, *, tenant_id: str, grant_id: str, ledger_entry_id: str,
    operation_key: str,
) -> None:
    """Revoke only the currently reclaimable balance; unknown usage stays held.

    This is the explicit policy-authorized path for a grant after issuance.
    It refuses to guess around a HELD usage reservation, rather than expiring
    and consuming the same amount concurrently.
    """
    grant = conn.execute(
        """SELECT account_id, currency FROM credit_grant
             WHERE tenant_id = %s AND id = %s AND state = 'ACTIVE' FOR UPDATE""",
        (tenant_id, grant_id),
    ).fetchone()
    if grant is None:
        return
    account_id, currency = grant
    conn.execute(
        "SELECT id FROM credit_account WHERE tenant_id = %s AND id = %s FOR UPDATE",
        (tenant_id, account_id),
    )
    held = conn.execute(
        "SELECT COALESCE(SUM(amount_minor_units), 0) FROM credit_usage_reservation WHERE tenant_id = %s AND grant_id = %s AND state = 'HELD'",
        (tenant_id, grant_id),
    ).fetchone()[0]
    if held:
        raise InsufficientCreditBalance("cannot revoke Credit while a redemption result is unresolved")
    available = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN entry_type IN ('ISSUE', 'REDEEM_REVERSAL')
                                     THEN amount_minor_units ELSE -amount_minor_units END), 0)
             FROM credit_ledger_entry WHERE tenant_id = %s AND grant_id = %s""",
        (tenant_id, grant_id),
    ).fetchone()[0]
    conn.execute("UPDATE credit_grant SET state = 'REVOKED' WHERE tenant_id = %s AND id = %s", (tenant_id, grant_id))
    if available > 0:
        conn.execute(
            """INSERT INTO credit_ledger_entry
                    (tenant_id, id, account_id, grant_id, entry_type, amount_minor_units, currency,
                     business_key, source_operation, occurred_at)
                VALUES (%s, %s, %s, %s, 'REVOKE', %s, %s, %s, %s, clock_timestamp())""",
            (tenant_id, ledger_entry_id, account_id, grant_id, available, currency, operation_key,
             json.dumps({"grant_id": str(grant_id)})),
        )
