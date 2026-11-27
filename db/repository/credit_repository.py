"""ENG-07 Credit ledger and usage-reservation repository.

All functions run inside ``tenant_transaction``.  They intentionally use the
same account-before-grant locking order for every amount-consuming operation;
the short transaction ends before any external checkout or notification I/O.
"""
from __future__ import annotations

import json
from datetime import datetime
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
        """SELECT id, account_id, remedy_action_id, issued_amount_minor_units, currency, terms_version,
                  scope, valid_from, expires_at, state, provider_grant_id, evidence
             FROM credit_grant WHERE tenant_id = %s AND grant_operation_key = %s FOR UPDATE""",
        (tenant_id, operation_key),
    ).fetchone()
    if existing is not None:
        row = dict(zip(("id", "account_id", "remedy_action_id", "issued_amount_minor_units", "currency", "terms_version",
                        "scope", "valid_from", "expires_at", "state", "provider_grant_id", "evidence"), existing))
        if (str(row["account_id"]) != str(account_id) or row["issued_amount_minor_units"] != amount_minor_units
                or row["currency"] != currency or row["terms_version"] != terms_version
                or str(row["remedy_action_id"]) != str(remedy_action_id)
                or row["scope"] != scope
                or _same_timestamp(row["valid_from"], valid_from) is False
                or _same_timestamp(row["expires_at"], expires_at) is False):
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
            RETURNING id, account_id, remedy_action_id, issued_amount_minor_units, currency, terms_version,
                      scope, valid_from, expires_at, state, provider_grant_id, evidence""",
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
    return dict(zip(("id", "account_id", "remedy_action_id", "issued_amount_minor_units", "currency", "terms_version",
                     "scope", "valid_from", "expires_at", "state", "provider_grant_id", "evidence"), row))


def _same_timestamp(stored: Any, requested: str) -> bool:
    """Compare instants, accepting RFC3339's ``Z`` spelling on API input."""
    return stored == datetime.fromisoformat(requested.replace("Z", "+00:00"))


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
    # One statement gives ledger and HELD reads one MVCC snapshot.  The
    # account->grant lock also serializes consume/release with this check.
    ledger_balance, held = conn.execute(
        """SELECT
                COALESCE((SELECT SUM(CASE WHEN entry_type IN ('ISSUE', 'REDEEM_REVERSAL')
                    THEN amount_minor_units ELSE -amount_minor_units END)
                    FROM credit_ledger_entry WHERE tenant_id = %s AND grant_id = %s), 0),
                COALESCE((SELECT SUM(amount_minor_units) FROM credit_usage_reservation
                    WHERE tenant_id = %s AND grant_id = %s AND state = 'HELD'), 0)""",
        (tenant_id, grant_id, tenant_id, grant_id),
    ).fetchone()
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
    identity = conn.execute(
        "SELECT grant_id FROM credit_usage_reservation WHERE tenant_id = %s AND id = %s",
        (tenant_id, reservation_id),
    ).fetchone()
    if identity is None:
        return
    _lock_grant_in_account_order(conn, tenant_id=tenant_id, grant_id=str(identity[0]))
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
    identity = conn.execute(
        "SELECT grant_id FROM credit_usage_reservation WHERE tenant_id = %s AND id = %s",
        (tenant_id, reservation_id),
    ).fetchone()
    if identity is None:
        return
    _lock_grant_in_account_order(conn, tenant_id=tenant_id, grant_id=str(identity[0]))
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
    existing = conn.execute(
        """SELECT reversal_of FROM credit_ledger_entry
             WHERE tenant_id = %s AND business_key = %s""",
        (tenant_id, reversal_business_key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != str(redemption_entry_id):
            raise IdempotencyConflict("Credit reversal key is already bound to another redemption")
        return
    original = conn.execute(
        """SELECT account_id, grant_id, amount_minor_units, currency, entry_type
             FROM credit_ledger_entry WHERE tenant_id = %s AND id = %s""",
        (tenant_id, redemption_entry_id),
    ).fetchone()
    if original is None or original[4] != "REDEEM":
        raise ValueError("Credit reversal must reference an existing REDEEM entry")
    account_id, grant_id, amount, currency, _ = original
    # Match every mutable Credit operation's account -> grant lock order.
    _lock_grant_in_account_order(conn, tenant_id=tenant_id, grant_id=str(grant_id))
    try:
        # This function is called inside tenant_transaction.  ``reversal_of``
        # is the targeted conflict arbiter, but a concurrent request can still
        # violate UNIQUE(tenant_id, business_key).  Contain that error in a
        # savepoint so the outer tenant transaction remains usable for the
        # replay/conflict lookup below.
        with conn.transaction():
            inserted = conn.execute(
                """INSERT INTO credit_ledger_entry
                    (tenant_id, id, account_id, grant_id, entry_type, amount_minor_units, currency,
                     business_key, source_operation, reversal_of, occurred_at)
                VALUES (%s, %s, %s, %s, 'REDEEM_REVERSAL', %s, %s, %s, %s, %s, clock_timestamp())
                ON CONFLICT (tenant_id, reversal_of) DO NOTHING
                RETURNING reversal_of""",
                (tenant_id, reversal_entry_id, account_id, grant_id, amount, currency, reversal_business_key,
                 json.dumps({"redemption_entry_id": str(redemption_entry_id)}), redemption_entry_id),
            ).fetchone()
    except psycopg.errors.UniqueViolation:
        # The nested transaction has rolled back to its savepoint.  Resolve the
        # now-visible winner below without poisoning tenant_transaction.
        inserted = None
    if inserted is None:
        # ``DO NOTHING`` can also be reached through the reversal_of arbiter.
        # Inspect business_key explicitly: it is the stable operation contract,
        # so the same key must never be silently rebound to another redemption.
        replay = conn.execute(
            "SELECT reversal_of FROM credit_ledger_entry WHERE tenant_id = %s AND business_key = %s",
            (tenant_id, reversal_business_key),
        ).fetchone()
        if replay is not None and str(replay[0]) == str(redemption_entry_id):
            return
        if replay is not None:
            raise IdempotencyConflict("Credit reversal key is already bound to another redemption")


def _existing_grant_operation(
    conn: psycopg.Connection, *, tenant_id: str, grant_id: str, operation_key: str, entry_type: str,
) -> dict[str, Any] | None:
    """Find a replay before taking mutable amount-operation locks."""
    row = conn.execute(
        """SELECT grant_id, amount_minor_units FROM credit_ledger_entry
             WHERE tenant_id = %s AND business_key = %s""",
        (tenant_id, operation_key),
    ).fetchone()
    amount_key = "revoked_minor_units" if entry_type == "REVOKE" else "expired_minor_units"
    if row is None:
        terminal = conn.execute(
            """SELECT id, state, terminal_operation_key FROM credit_grant
                 WHERE tenant_id = %s AND terminal_operation_key = %s""",
            (tenant_id, operation_key),
        ).fetchone()
        expected_state = "REVOKED" if entry_type == "REVOKE" else "EXPIRED"
        if terminal is not None:
            if str(terminal[0]) == str(grant_id) and terminal[1] == expected_state:
                return {"grant_id": str(grant_id), amount_key: 0, "replayed": True}
            raise IdempotencyConflict("Credit terminal operation key is already bound to another operation")
        return None
    if str(row[0]) != str(grant_id):
        raise IdempotencyConflict("Credit operation key is already bound to another grant")
    recorded_type = conn.execute(
        "SELECT entry_type FROM credit_ledger_entry WHERE tenant_id = %s AND business_key = %s",
        (tenant_id, operation_key),
    ).fetchone()[0]
    if recorded_type != entry_type:
        raise IdempotencyConflict("Credit operation key is already bound to another operation type")
    return {"grant_id": str(row[0]), amount_key: row[1], "replayed": True}


def _lock_grant_in_account_order(
    conn: psycopg.Connection, *, tenant_id: str, grant_id: str,
) -> tuple[Any, Any] | None:
    """Lock account then grant, never reversing reserve_credit_usage's order."""
    identity = conn.execute(
        "SELECT account_id, currency FROM credit_grant WHERE tenant_id = %s AND id = %s",
        (tenant_id, grant_id),
    ).fetchone()
    if identity is None:
        return None
    account_id, currency = identity
    conn.execute(
        "SELECT id FROM credit_account WHERE tenant_id = %s AND id = %s AND currency = %s FOR UPDATE",
        (tenant_id, account_id, currency),
    ).fetchone()
    return conn.execute(
        """SELECT account_id, currency, state, terminal_operation_key FROM credit_grant
             WHERE tenant_id = %s AND id = %s FOR UPDATE""",
        (tenant_id, grant_id),
    ).fetchone()


def _credit_balance_breakdown(conn: psycopg.Connection, *, tenant_id: str, grant_id: str) -> tuple[int, int]:
    available = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN entry_type IN ('ISSUE', 'REDEEM_REVERSAL')
                                     THEN amount_minor_units ELSE -amount_minor_units END), 0)
             FROM credit_ledger_entry WHERE tenant_id = %s AND grant_id = %s""",
        (tenant_id, grant_id),
    ).fetchone()[0]
    redeemed = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN entry_type = 'REDEEM' THEN amount_minor_units
                                     WHEN entry_type = 'REDEEM_REVERSAL' THEN -amount_minor_units ELSE 0 END), 0)
             FROM credit_ledger_entry WHERE tenant_id = %s AND grant_id = %s""",
        (tenant_id, grant_id),
    ).fetchone()[0]
    return available, redeemed


def revoke_unused_credit(
    conn: psycopg.Connection, *, tenant_id: str, grant_id: str, ledger_entry_id: str,
    operation_key: str,
) -> dict[str, Any]:
    """Revoke only the currently reclaimable balance; unknown usage stays held.

    This is the explicit policy-authorized path for a grant after issuance.
    It refuses to guess around a HELD usage reservation, rather than expiring
    and consuming the same amount concurrently.
    """
    replay = _existing_grant_operation(
        conn, tenant_id=tenant_id, grant_id=grant_id, operation_key=operation_key, entry_type="REVOKE",
    )
    if replay is not None:
        _, redeemed = _credit_balance_breakdown(conn, tenant_id=tenant_id, grant_id=grant_id)
        return {**replay, "already_redeemed_minor_units": redeemed, "disposition": "REPLAYED"}
    grant = _lock_grant_in_account_order(conn, tenant_id=tenant_id, grant_id=grant_id)
    if grant is None:
        raise ValueError("Credit grant does not exist for this tenant")
    account_id, currency, state, _ = grant
    if state != "ACTIVE":
        if state == "REVOKED" and grant[3] == operation_key:
            replay = _existing_grant_operation(
                conn, tenant_id=tenant_id, grant_id=grant_id, operation_key=operation_key, entry_type="REVOKE"
            )
            _, redeemed = _credit_balance_breakdown(conn, tenant_id=tenant_id, grant_id=grant_id)
            return {**(replay or {"grant_id": str(grant_id), "revoked_minor_units": 0}), "state": state,
                    "already_redeemed_minor_units": redeemed, "disposition": "REPLAYED", "replayed": True}
        raise ValueError("Credit grant is not active and cannot be revoked")
    held = conn.execute(
        "SELECT COALESCE(SUM(amount_minor_units), 0) FROM credit_usage_reservation WHERE tenant_id = %s AND grant_id = %s AND state = 'HELD'",
        (tenant_id, grant_id),
    ).fetchone()[0]
    if held:
        raise InsufficientCreditBalance("cannot revoke Credit while a redemption result is unresolved")
    available, redeemed = _credit_balance_breakdown(conn, tenant_id=tenant_id, grant_id=grant_id)
    conn.execute("""UPDATE credit_grant SET state = 'REVOKED', terminal_operation_key = %s
                    WHERE tenant_id = %s AND id = %s""", (operation_key, tenant_id, grant_id))
    if available > 0:
        conn.execute(
            """INSERT INTO credit_ledger_entry
                    (tenant_id, id, account_id, grant_id, entry_type, amount_minor_units, currency,
                     business_key, source_operation, occurred_at)
                VALUES (%s, %s, %s, %s, 'REVOKE', %s, %s, %s, %s, clock_timestamp())""",
            (tenant_id, ledger_entry_id, account_id, grant_id, available, currency, operation_key,
             json.dumps({"grant_id": str(grant_id)})),
        )
    return {"grant_id": str(grant_id), "state": "REVOKED", "revoked_minor_units": available,
            "already_redeemed_minor_units": redeemed,
            "disposition": ("REVOKED_UNUSED_BALANCE" if available else "ALREADY_FULLY_REDEEMED")
            if redeemed else "REVOKED_FULL_UNUSED_BALANCE",
            "replayed": False}


def expire_credit_grant(
    conn: psycopg.Connection, *, tenant_id: str, grant_id: str, ledger_entry_id: str, operation_key: str,
) -> dict[str, Any]:
    """Expire only an elapsed, unreserved grant; UNKNOWN/PENDING use remains HELD."""
    replay = _existing_grant_operation(
        conn, tenant_id=tenant_id, grant_id=grant_id, operation_key=operation_key, entry_type="EXPIRE",
    )
    if replay is not None:
        _, redeemed = _credit_balance_breakdown(conn, tenant_id=tenant_id, grant_id=grant_id)
        return {**replay, "already_redeemed_minor_units": redeemed, "disposition": "REPLAYED"}
    grant = _lock_grant_in_account_order(conn, tenant_id=tenant_id, grant_id=grant_id)
    if grant is None:
        raise ValueError("Credit grant does not exist for this tenant")
    account_id, currency, state, _ = grant
    if state != "ACTIVE":
        if state == "EXPIRED" and grant[3] == operation_key:
            replay = _existing_grant_operation(
                conn, tenant_id=tenant_id, grant_id=grant_id, operation_key=operation_key, entry_type="EXPIRE"
            )
            _, redeemed = _credit_balance_breakdown(conn, tenant_id=tenant_id, grant_id=grant_id)
            return {**(replay or {"grant_id": str(grant_id), "expired_minor_units": 0}), "state": state,
                    "already_redeemed_minor_units": redeemed, "disposition": "REPLAYED", "replayed": True}
        raise ValueError("Credit grant is not active and cannot expire")
    expired = conn.execute(
        "SELECT expires_at <= clock_timestamp() FROM credit_grant WHERE tenant_id = %s AND id = %s",
        (tenant_id, grant_id),
    ).fetchone()[0]
    if not expired:
        raise ValueError("Credit grant has not reached its expiry")
    held = conn.execute(
        """SELECT COALESCE(SUM(amount_minor_units), 0) FROM credit_usage_reservation
             WHERE tenant_id = %s AND grant_id = %s AND state = 'HELD'""",
        (tenant_id, grant_id),
    ).fetchone()[0]
    if held:
        raise InsufficientCreditBalance("cannot expire Credit while a redemption result is unresolved")
    available, redeemed = _credit_balance_breakdown(conn, tenant_id=tenant_id, grant_id=grant_id)
    conn.execute("""UPDATE credit_grant SET state = 'EXPIRED', terminal_operation_key = %s
                    WHERE tenant_id = %s AND id = %s""", (operation_key, tenant_id, grant_id))
    if available > 0:
        conn.execute(
            """INSERT INTO credit_ledger_entry
                    (tenant_id, id, account_id, grant_id, entry_type, amount_minor_units, currency,
                     business_key, source_operation, occurred_at)
                VALUES (%s, %s, %s, %s, 'EXPIRE', %s, %s, %s, %s, clock_timestamp())""",
            (tenant_id, ledger_entry_id, account_id, grant_id, available, currency, operation_key,
             json.dumps({"grant_id": str(grant_id)})),
        )
    return {"grant_id": str(grant_id), "state": "EXPIRED", "expired_minor_units": available,
            "already_redeemed_minor_units": redeemed, "disposition": "EXPIRED", "replayed": False}
