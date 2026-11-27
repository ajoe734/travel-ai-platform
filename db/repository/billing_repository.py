"""Append-only ENG-12 billing, settlement, attribution and cost records.

The caller supplies an amount only after applying the referenced commercial
contract.  This repository deliberately does not invent rates from a usage
type or a prototype example.  Every public function is invoked inside
``tenant_transaction`` so RLS and the composite tenant references remain the
authoritative isolation boundary.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import psycopg

from .errors import IdempotencyConflict, RepositoryError
from .rows import row_as_dict


_CONTRACT_COLUMNS = [
    "tenant_id", "id", "contract_id", "version", "terms", "terms_hash",
    "currency", "currency_scale_ref", "effective_at", "created_at",
]
_FEE_COLUMNS = [
    "tenant_id", "id", "contract_version_id", "operation", "business_key",
    "request_hash", "usage_kind", "usage_quantity", "unit", "amount_minor_units",
    "currency", "currency_scale_ref", "occurred_at", "evidence", "created_at",
]
_ATTRIBUTION_COLUMNS = [
    "tenant_id", "order_id", "attribution_kind", "source_channel",
    "source_customer_ref", "evidence", "attributed_at",
]
_SETTLEMENT_COLUMNS = [
    "tenant_id", "id", "order_id", "refund_id", "contract_version_id",
    "attribution_kind", "entry_kind", "business_key", "amount_minor_units",
    "currency", "currency_scale_ref", "basis", "reversal_of", "occurred_at", "created_at",
]
_COST_COLUMNS = [
    "tenant_id", "id", "case_id", "order_id", "business_key", "request_hash",
    "cost_kind", "outcome", "cost_status", "manual_remediation", "quantity", "unit",
    "amount_minor_units", "currency", "currency_scale_ref", "provider_usage_ref",
    "occurred_at", "evidence", "supersedes_cost_id", "created_at",
]


def _row(columns: list[str], value: Any) -> dict[str, Any]:
    return row_as_dict(columns, value)


def _lock_keys(conn: psycopg.Connection, *keys: str) -> None:
    """Serialize immutable keys without asking app_role for UPDATE privilege."""
    for key in sorted(set(keys)):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


def _same_cost(result: dict[str, Any], expected: tuple[Any, ...]) -> bool:
    actual = (str(result["case_id"]), str(result["order_id"]) if result["order_id"] else None,
              result["request_hash"], result["cost_kind"], result["outcome"], result["cost_status"],
              result["manual_remediation"], Decimal(str(result["quantity"])), result["unit"],
              result["amount_minor_units"], result["currency"], result["currency_scale_ref"],
              result["provider_usage_ref"])
    return actual == (*expected[:7], Decimal(str(expected[7])), *expected[8:])


def create_contract_version(
    conn: psycopg.Connection, *, tenant_id: str, contract_version_id: str,
    contract_id: str, version: int, terms: dict[str, Any], terms_hash: str,
    currency: str, currency_scale_ref: str, effective_at: str,
) -> dict[str, Any]:
    row = conn.execute(
        f"""INSERT INTO billing_contract_version
            (tenant_id,id,contract_id,version,terms,terms_hash,currency,currency_scale_ref,effective_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING {', '.join(_CONTRACT_COLUMNS)}""",
        (tenant_id, contract_version_id, contract_id, version, json.dumps(terms), terms_hash,
         currency, currency_scale_ref, effective_at),
    ).fetchone()
    return _row(_CONTRACT_COLUMNS, row)


def record_business_fee(
    conn: psycopg.Connection, *, tenant_id: str, fee_id: str, contract_version_id: str,
    business_key: str, request_hash: str, usage_kind: str, usage_quantity: int,
    unit: str, amount_minor_units: int, currency: str, currency_scale_ref: str,
    occurred_at: str, evidence: dict[str, Any],
) -> dict[str, Any]:
    """Record a contract-versioned fee once per stable business operation."""
    _lock_keys(conn, f"{tenant_id}:business-fee:{business_key}")
    existing = conn.execute(
        f"SELECT {', '.join(_FEE_COLUMNS)} FROM business_fee_charge "
        "WHERE tenant_id=%s AND operation='ENTERPRISE_USAGE_FEE' AND business_key=%s",
        (tenant_id, business_key),
    ).fetchone()
    if existing is not None:
        result = _row(_FEE_COLUMNS, existing)
        expected = (contract_version_id, request_hash, usage_kind, usage_quantity, unit,
                    amount_minor_units, currency, currency_scale_ref)
        actual = (str(result["contract_version_id"]), result["request_hash"], result["usage_kind"], result["usage_quantity"], result["unit"],
                  result["amount_minor_units"], result["currency"], result["currency_scale_ref"])
        if actual != expected:
            raise IdempotencyConflict("business fee key was replayed with different contract or charge content")
        return result
    row = conn.execute(
        f"""INSERT INTO business_fee_charge
            (tenant_id,id,contract_version_id,operation,business_key,request_hash,usage_kind,usage_quantity,
             unit,amount_minor_units,currency,currency_scale_ref,occurred_at,evidence)
            VALUES (%s,%s,%s,'ENTERPRISE_USAGE_FEE',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING {', '.join(_FEE_COLUMNS)}""",
        (tenant_id, fee_id, contract_version_id, business_key, request_hash, usage_kind,
         usage_quantity, unit, amount_minor_units, currency, currency_scale_ref, occurred_at,
         json.dumps(evidence)),
    ).fetchone()
    return _row(_FEE_COLUMNS, row)


def record_order_attribution(
    conn: psycopg.Connection, *, tenant_id: str, order_id: str, attribution_kind: str,
    source_channel: str | None, source_customer_ref: str | None, evidence: dict[str, Any],
    attributed_at: str,
) -> dict[str, Any]:
    _lock_keys(conn, f"{tenant_id}:attribution:{order_id}")
    existing = conn.execute(
        f"SELECT {', '.join(_ATTRIBUTION_COLUMNS)} FROM order_attribution "
        "WHERE tenant_id=%s AND order_id=%s", (tenant_id, order_id),
    ).fetchone()
    if existing is not None:
        result = _row(_ATTRIBUTION_COLUMNS, existing)
        if tuple(result[k] for k in ("attribution_kind", "source_channel", "source_customer_ref")) != (
            attribution_kind, source_channel, source_customer_ref
        ):
            raise IdempotencyConflict("order attribution is immutable; a different source needs an auditable correction")
        return result
    row = conn.execute(
        f"""INSERT INTO order_attribution
            (tenant_id,order_id,attribution_kind,source_channel,source_customer_ref,evidence,attributed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING {', '.join(_ATTRIBUTION_COLUMNS)}""",
        (tenant_id, order_id, attribution_kind, source_channel, source_customer_ref,
         json.dumps(evidence), attributed_at),
    ).fetchone()
    return _row(_ATTRIBUTION_COLUMNS, row)


def record_settlement_entry(
    conn: psycopg.Connection, *, tenant_id: str, entry_id: str, order_id: str,
    contract_version_id: str | None, attribution_kind: str, entry_kind: str,
    business_key: str, amount_minor_units: int, currency: str, currency_scale_ref: str,
    basis: dict[str, Any], occurred_at: str,
) -> dict[str, Any]:
    """Append original GMV/revenue/commission/payable rows, never a reversal."""
    if amount_minor_units <= 0:
        raise ValueError("original settlement entries must be positive; use record_settlement_reversal")
    _lock_keys(conn, f"{tenant_id}:settlement:{business_key}")
    attribution = conn.execute(
        "SELECT attribution_kind FROM order_attribution WHERE tenant_id=%s AND order_id=%s",
        (tenant_id, order_id),
    ).fetchone()
    if attribution is None or attribution[0] != attribution_kind:
        raise RepositoryError("settlement entry must use the persisted order attribution")
    existing = conn.execute(
        f"SELECT {', '.join(_SETTLEMENT_COLUMNS)} FROM settlement_entry "
        "WHERE tenant_id=%s AND business_key=%s", (tenant_id, business_key),
    ).fetchone()
    if existing is not None:
        result = _row(_SETTLEMENT_COLUMNS, existing)
        actual = (str(result["order_id"]), str(result["contract_version_id"]) if result["contract_version_id"] else None,
                  result["attribution_kind"], result["entry_kind"], result["amount_minor_units"], result["currency"], result["currency_scale_ref"], result["basis"])
        expected = (order_id, contract_version_id, attribution_kind, entry_kind, amount_minor_units, currency, currency_scale_ref, basis)
        if actual != expected:
            raise IdempotencyConflict("settlement business key was replayed with different content")
        return result
    row = conn.execute(
        f"""INSERT INTO settlement_entry
            (tenant_id,id,order_id,contract_version_id,attribution_kind,entry_kind,business_key,
             amount_minor_units,currency,currency_scale_ref,basis,occurred_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING {', '.join(_SETTLEMENT_COLUMNS)}""",
        (tenant_id, entry_id, order_id, contract_version_id, attribution_kind, entry_kind,
         business_key, amount_minor_units, currency, currency_scale_ref, json.dumps(basis), occurred_at),
    ).fetchone()
    return _row(_SETTLEMENT_COLUMNS, row)


def record_settlement_reversal(
    conn: psycopg.Connection, *, tenant_id: str, reversal_id: str, refund_id: str,
    original_entry_id: str, business_key: str, amount_minor_units: int, basis: dict[str, Any],
    occurred_at: str,
) -> dict[str, Any]:
    """Append a negative adjustment against a succeeded refund and original entry.

    The source entry is locked and the sum of prior reversals is checked, so
    duplicate refund delivery cannot over-reverse a commission or revenue row.
    """
    _lock_keys(conn, f"{tenant_id}:settlement:{business_key}", f"{tenant_id}:settlement-source:{original_entry_id}")
    existing = conn.execute(
        f"SELECT {', '.join(_SETTLEMENT_COLUMNS)} FROM settlement_entry "
        "WHERE tenant_id=%s AND business_key=%s", (tenant_id, business_key),
    ).fetchone()
    if existing is not None:
        result = _row(_SETTLEMENT_COLUMNS, existing)
        if (str(result["refund_id"]) != str(refund_id) or str(result["reversal_of"]) != str(original_entry_id)
                or result["amount_minor_units"] != -amount_minor_units or result["basis"] != basis):
            raise IdempotencyConflict("settlement reversal key was replayed with different content")
        return result
    if amount_minor_units <= 0:
        raise ValueError("reversal amount must be positive before its ledger sign is applied")
    refund = conn.execute(
        "SELECT p.order_id,p.currency,r.state FROM refund r JOIN payment p ON (p.tenant_id=r.tenant_id AND p.id=r.payment_id) "
        "WHERE r.tenant_id=%s AND r.id=%s",
        (tenant_id, refund_id),
    ).fetchone()
    if refund is None or refund[2] != "SUCCEEDED":
        raise RepositoryError("settlement reversal requires a succeeded refund with formal evidence")
    original = conn.execute(
        f"SELECT {', '.join(_SETTLEMENT_COLUMNS)} FROM settlement_entry "
        "WHERE tenant_id=%s AND id=%s", (tenant_id, original_entry_id),
    ).fetchone()
    if original is None:
        raise RepositoryError("original settlement entry not found")
    source = _row(_SETTLEMENT_COLUMNS, original)
    if str(source["order_id"]) != str(refund[0]) or source["currency"] != refund[1] or source["amount_minor_units"] <= 0:
        raise RepositoryError("refund and original settlement entry do not form a valid reversal pair")
    # The refund provider can redeliver the same formal refund under a new
    # business key.  The database's tuple uniqueness is the final concurrency
    # guard, but inspect it first so the public repository contract never
    # leaks a raw UniqueViolation.
    prior_refund_reversal = conn.execute(
        f"SELECT {', '.join(_SETTLEMENT_COLUMNS)} FROM settlement_entry "
        "WHERE tenant_id=%s AND reversal_of=%s AND refund_id=%s",
        (tenant_id, original_entry_id, refund_id),
    ).fetchone()
    if prior_refund_reversal is not None:
        result = _row(_SETTLEMENT_COLUMNS, prior_refund_reversal)
        if (result["business_key"] != business_key or result["amount_minor_units"] != -amount_minor_units
                or result["basis"] != basis):
            raise IdempotencyConflict("refund reversal is already bound to different settlement content")
        return result
    reversed_so_far = conn.execute(
        "SELECT COALESCE(-SUM(amount_minor_units), 0) FROM settlement_entry "
        "WHERE tenant_id=%s AND reversal_of=%s", (tenant_id, original_entry_id),
    ).fetchone()[0]
    if reversed_so_far + amount_minor_units > source["amount_minor_units"]:
        raise RepositoryError("settlement reversal would exceed the original entry amount")
    row = conn.execute(
        f"""INSERT INTO settlement_entry
            (tenant_id,id,order_id,refund_id,contract_version_id,attribution_kind,entry_kind,business_key,
             amount_minor_units,currency,currency_scale_ref,basis,reversal_of,occurred_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
            RETURNING {', '.join(_SETTLEMENT_COLUMNS)}""",
        (tenant_id, reversal_id, source["order_id"], refund_id, source["contract_version_id"],
         source["attribution_kind"], source["entry_kind"], business_key, -amount_minor_units,
         source["currency"], source["currency_scale_ref"], json.dumps(basis), original_entry_id, occurred_at),
    ).fetchone()
    if row is not None:
        return _row(_SETTLEMENT_COLUMNS, row)
    raced = conn.execute(
        f"SELECT {', '.join(_SETTLEMENT_COLUMNS)} FROM settlement_entry "
        "WHERE tenant_id=%s AND reversal_of=%s AND refund_id=%s",
        (tenant_id, original_entry_id, refund_id),
    ).fetchone()
    if raced is not None:
        result = _row(_SETTLEMENT_COLUMNS, raced)
        if (result["business_key"] == business_key and result["amount_minor_units"] == -amount_minor_units
                and result["basis"] == basis):
            return result
    raise IdempotencyConflict("refund reversal is already bound to different settlement content")


def record_operational_cost(
    conn: psycopg.Connection, *, tenant_id: str, cost_id: str, case_id: str, order_id: str | None,
    business_key: str, request_hash: str, cost_kind: str, outcome: str, cost_status: str,
    manual_remediation: bool, quantity: str, unit: str, amount_minor_units: int | None,
    currency: str | None, currency_scale_ref: str | None, provider_usage_ref: str | None,
    occurred_at: str, evidence: dict[str, Any],
) -> dict[str, Any]:
    final_key = f"{business_key}:final"
    _lock_keys(
        conn,
        f"{tenant_id}:cost:{business_key}",
        f"{tenant_id}:cost:{final_key}",
        *(() if provider_usage_ref is None else (f"{tenant_id}:provider-usage:{provider_usage_ref}",)),
    )
    if order_id is not None:
        belongs = conn.execute(
            "SELECT 1 FROM order_record WHERE tenant_id=%s AND id=%s AND case_id=%s",
            (tenant_id, order_id, case_id),
        ).fetchone()
        if belongs is None:
            raise RepositoryError("operational cost order must belong to the same case")
    existing = conn.execute(
        f"SELECT {', '.join(_COST_COLUMNS)} FROM operational_cost_record "
        "WHERE tenant_id=%s AND business_key=%s", (tenant_id, business_key),
    ).fetchone()
    if existing is not None:
        result = _row(_COST_COLUMNS, existing)
        expected = (case_id, order_id, request_hash, cost_kind, outcome, cost_status, manual_remediation,
                    quantity, unit, amount_minor_units, currency, currency_scale_ref, provider_usage_ref)
        if not _same_cost(result, expected):
            # Provider final usage corrects an immutable INCOMPLETE evidence row
            # by appending one linked ACTUAL row; it never rewrites or re-bills it.
            if result["cost_status"] == "INCOMPLETE" and cost_status == "ACTUAL":
                correction_identity = (
                    str(result["case_id"]), str(result["order_id"]) if result["order_id"] else None,
                    result["request_hash"], result["cost_kind"], result["outcome"],
                    result["manual_remediation"], Decimal(str(result["quantity"])), result["unit"],
                )
                incoming_identity = (
                    str(case_id), str(order_id) if order_id else None, request_hash, cost_kind,
                    outcome, manual_remediation, Decimal(str(quantity)), unit,
                )
                if correction_identity != incoming_identity:
                    raise IdempotencyConflict("final provider usage must retain its incomplete cost identity")
                final = conn.execute(
                    f"SELECT {', '.join(_COST_COLUMNS)} FROM operational_cost_record "
                    "WHERE tenant_id=%s AND business_key=%s", (tenant_id, final_key),
                ).fetchone()
                if final is not None:
                    final_result = _row(_COST_COLUMNS, final)
                    if final_result["supersedes_cost_id"] == result["id"] and _same_cost(final_result, expected):
                        return final_result
                    raise IdempotencyConflict("final provider usage is already bound to different cost content")
                row = conn.execute(
                    f"""INSERT INTO operational_cost_record
                        (tenant_id,id,case_id,order_id,business_key,request_hash,cost_kind,outcome,cost_status,
                         manual_remediation,quantity,unit,amount_minor_units,currency,currency_scale_ref,
                         provider_usage_ref,occurred_at,evidence,supersedes_cost_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT DO NOTHING RETURNING {', '.join(_COST_COLUMNS)}""",
                    (tenant_id, cost_id, case_id, order_id, final_key, request_hash, cost_kind, outcome,
                     cost_status, manual_remediation, quantity, unit, amount_minor_units, currency,
                     currency_scale_ref, provider_usage_ref, occurred_at, json.dumps(evidence), result["id"]),
                ).fetchone()
                if row is not None:
                    return _row(_COST_COLUMNS, row)
                raise IdempotencyConflict("final provider usage is already bound to another cost event")
            raise IdempotencyConflict("cost business key was replayed with different content")
        return result
    if provider_usage_ref is not None:
        provider_existing = conn.execute(
            f"SELECT {', '.join(_COST_COLUMNS)} FROM operational_cost_record "
            "WHERE tenant_id=%s AND provider_usage_ref=%s", (tenant_id, provider_usage_ref),
        ).fetchone()
        if provider_existing is not None:
            raise IdempotencyConflict("provider usage was already recorded under another business key")
    row = conn.execute(
        f"""INSERT INTO operational_cost_record
            (tenant_id,id,case_id,order_id,business_key,request_hash,cost_kind,outcome,cost_status,
             manual_remediation,quantity,unit,amount_minor_units,currency,currency_scale_ref,
             provider_usage_ref,occurred_at,evidence,supersedes_cost_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)
            RETURNING {', '.join(_COST_COLUMNS)}""",
        (tenant_id, cost_id, case_id, order_id, business_key, request_hash, cost_kind, outcome,
         cost_status, manual_remediation, quantity, unit, amount_minor_units, currency,
         currency_scale_ref, provider_usage_ref, occurred_at, json.dumps(evidence)),
    ).fetchone()
    return _row(_COST_COLUMNS, row)


def cost_summary_by_outcome(
    conn: psycopg.Connection, *, tenant_id: str, period_start: str, period_end: str,
) -> dict[str, Any]:
    """Return one period's cost evidence without treating incomplete usage as zero.

    ``automatic_success_case_count`` excludes every case that has a HUMAN
    remediation record in the period, even if it later reaches success.
    """
    rows = conn.execute(
        """SELECT outcome, cost_status, currency, SUM(amount_minor_units), COUNT(*)
           FROM operational_cost_record
           WHERE tenant_id=%s AND occurred_at >= %s AND occurred_at < %s
             AND NOT EXISTS (SELECT 1 FROM operational_cost_record final
                             WHERE final.tenant_id=operational_cost_record.tenant_id
                               AND final.supersedes_cost_id=operational_cost_record.id)
           GROUP BY outcome, cost_status, currency ORDER BY outcome, cost_status, currency""",
        (tenant_id, period_start, period_end),
    ).fetchall()
    automatic = conn.execute(
        """SELECT COUNT(*) FROM (
              SELECT case_id, bool_or(manual_remediation) AS had_manual,
                     bool_or(outcome = 'SUCCEEDED') AS had_success
              FROM operational_cost_record
              WHERE tenant_id=%s AND occurred_at >= %s AND occurred_at < %s
                AND NOT EXISTS (SELECT 1 FROM operational_cost_record final
                                WHERE final.tenant_id=operational_cost_record.tenant_id
                                  AND final.supersedes_cost_id=operational_cost_record.id)
                AND NOT EXISTS (SELECT 1 FROM operational_cost_record human
                                WHERE human.tenant_id=operational_cost_record.tenant_id
                                  AND human.case_id=operational_cost_record.case_id
                                  AND (human.manual_remediation OR human.cost_kind='HUMAN'))
              GROUP BY case_id
           ) cases WHERE had_success AND NOT had_manual""",
        (tenant_id, period_start, period_end),
    ).fetchone()[0]
    return {
        "period_start": period_start,
        "period_end": period_end,
        "by_outcome": [
            {"outcome": row[0], "cost_status": row[1], "currency": row[2],
             "amount_minor_units": row[3], "record_count": row[4]}
            for row in rows
        ],
        "automatic_success_case_count": automatic,
    }
