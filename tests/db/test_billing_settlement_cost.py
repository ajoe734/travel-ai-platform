"""ENG-12 acceptance probes through the production Postgres repositories."""
from __future__ import annotations

import hashlib
import uuid

import pytest

from db.repository import billing_repository, db as repo_db, refund_repository
from db.repository.errors import IdempotencyConflict, RepositoryError


_NOW = "2026-11-27T00:00:00+00:00"
_END = "2026-12-01T00:00:00+00:00"


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _contract(conn, tenant_id):
    contract_id = str(uuid.uuid4())
    version_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_id):
        billing_repository.create_contract_version(
            conn, tenant_id=tenant_id, contract_version_id=version_id, contract_id=contract_id,
            version=1, terms={"quota": {"unit": "case", "included": 10}, "overage": "signed"},
            terms_hash=sha256_hex("contract-v1"), currency="TWD",
            currency_scale_ref="iso4217-minor-unit-2", effective_at=_NOW,
        )
    return version_id


def test_business_fee_replay_is_idempotent_and_contract_content_is_not_reused(conn, tenant_a):
    contract_version_id = _contract(conn, tenant_a)
    args = dict(
        tenant_id=tenant_a, fee_id=str(uuid.uuid4()), contract_version_id=contract_version_id,
        business_key="enterprise-usage:case:123", request_hash=sha256_hex("case:123"),
        usage_kind="CASE", usage_quantity=1, unit="case", amount_minor_units=30,
        currency="TWD", currency_scale_ref="iso4217-minor-unit-2", occurred_at=_NOW,
        evidence={"usage_event": "case:123"},
    )
    with repo_db.tenant_transaction(conn, tenant_a):
        first = billing_repository.record_business_fee(conn, **args)
        replay = billing_repository.record_business_fee(conn, **{**args, "fee_id": str(uuid.uuid4())})
        with pytest.raises(IdempotencyConflict):
            billing_repository.record_business_fee(conn, **{**args, "fee_id": str(uuid.uuid4()), "amount_minor_units": 31})
        count = conn.execute("SELECT COUNT(*) FROM business_fee_charge WHERE tenant_id=%s", (tenant_a,)).fetchone()[0]
    assert first["id"] == replay["id"]
    assert count == 1


def test_refund_reversal_is_append_only_and_limited_to_original_settlement(conn, tenant_a, case_factory, payment_chain_factory):
    case_id = case_factory(tenant_a)
    chain = payment_chain_factory(tenant_a, case_id, 1000)
    contract_version_id = _contract(conn, tenant_a)
    refund_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_a):
        billing_repository.record_order_attribution(
            conn, tenant_id=tenant_a, order_id=chain["order_id"], attribution_kind="CHANNEL_CUSTOMER",
            source_channel="partner-a", source_customer_ref="partner-order-100", evidence={"source": "webhook"},
            attributed_at=_NOW,
        )
        gmv = billing_repository.record_settlement_entry(
            conn, tenant_id=tenant_a, entry_id=str(uuid.uuid4()), order_id=chain["order_id"],
            contract_version_id=contract_version_id, attribution_kind="CHANNEL_CUSTOMER", entry_kind="GMV",
            business_key="settlement:order-100:gmv", amount_minor_units=1000, currency="TWD",
            currency_scale_ref="iso4217-minor-unit-2", basis={"order_snapshot": chain["order_id"]}, occurred_at=_NOW,
        )
        revenue = billing_repository.record_settlement_entry(
            conn, tenant_id=tenant_a, entry_id=str(uuid.uuid4()), order_id=chain["order_id"],
            contract_version_id=contract_version_id, attribution_kind="CHANNEL_CUSTOMER", entry_kind="PLATFORM_REVENUE",
            business_key="settlement:order-100:revenue", amount_minor_units=100, currency="TWD",
            currency_scale_ref="iso4217-minor-unit-2", basis={"contract_version": contract_version_id}, occurred_at=_NOW,
        )
        refund_repository.reserve_refund(
            conn, tenant_id=tenant_a, payment_id=chain["payment_id"], refund_id=refund_id,
            business_key="refund:order-100:partial", amount_minor_units=500, currency="TWD",
            currency_scale_ref="iso4217-minor-unit-2",
        )
        refund_repository.mark_refund_succeeded(
            conn, tenant_id=tenant_a, refund_id=refund_id, provider_refund_id="provider-refund-100",
            source_revision="provider-v1", evidence={"formal_status": "SUCCEEDED"},
        )
        reversal = billing_repository.record_settlement_reversal(
            conn, tenant_id=tenant_a, reversal_id=str(uuid.uuid4()), refund_id=refund_id,
            original_entry_id=revenue["id"], business_key="settlement:refund-100:revenue",
            amount_minor_units=50, basis={"refund_ratio": "1/2"}, occurred_at=_NOW,
        )
        replay = billing_repository.record_settlement_reversal(
            conn, tenant_id=tenant_a, reversal_id=str(uuid.uuid4()), refund_id=refund_id,
            original_entry_id=revenue["id"], business_key="settlement:refund-100:revenue",
            amount_minor_units=50, basis={"refund_ratio": "1/2"}, occurred_at=_NOW,
        )
        with pytest.raises(RepositoryError):
            billing_repository.record_settlement_reversal(
                conn, tenant_id=tenant_a, reversal_id=str(uuid.uuid4()), refund_id=refund_id,
                original_entry_id=revenue["id"], business_key="settlement:refund-100:too-much",
                amount_minor_units=51, basis={}, occurred_at=_NOW,
            )
        original_amount = conn.execute(
            "SELECT amount_minor_units FROM settlement_entry WHERE tenant_id=%s AND id=%s", (tenant_a, revenue["id"])
        ).fetchone()[0]
    assert gmv["amount_minor_units"] == 1000
    assert reversal["amount_minor_units"] == -50
    assert reversal["id"] == replay["id"]
    assert original_amount == 100


def test_cost_reporting_keeps_unconverted_and_incomplete_usage_and_excludes_manual_success(
    conn, tenant_a, case_factory
):
    manually_remediated_case = case_factory(tenant_a)
    automatic_case = case_factory(tenant_a)
    def record(case_id, key, **overrides):
        values = dict(
            tenant_id=tenant_a, cost_id=str(uuid.uuid4()), case_id=case_id, order_id=None,
            business_key=key, request_hash=sha256_hex(key), cost_kind="MODEL", outcome="SUCCEEDED",
            cost_status="ACTUAL", manual_remediation=False, quantity="1", unit="request",
            amount_minor_units=7, currency="TWD", currency_scale_ref="iso4217-minor-unit-2",
            provider_usage_ref=key, occurred_at=_NOW, evidence={"provider": "mock"},
        )
        values.update(overrides)
        return billing_repository.record_operational_cost(conn, **values)
    with repo_db.tenant_transaction(conn, tenant_a):
        record(manually_remediated_case, "voice-success", cost_kind="VOICE", amount_minor_units=10)
        record(manually_remediated_case, "manual-remediation", cost_kind="HUMAN", manual_remediation=True,
               quantity="15", unit="minute", amount_minor_units=50)
        record(manually_remediated_case, "query-unconverted", cost_kind="QUERY", outcome="UNCONVERTED", amount_minor_units=3)
        record(manually_remediated_case, "voice-final-pending", cost_kind="VOICE", cost_status="INCOMPLETE",
               amount_minor_units=None, currency=None, currency_scale_ref=None)
        record(automatic_case, "message-automatic", cost_kind="MESSAGE", amount_minor_units=2)
        summary = billing_repository.cost_summary_by_outcome(
            conn, tenant_id=tenant_a, period_start=_NOW, period_end=_END
        )
    assert summary["automatic_success_case_count"] == 1
    assert any(row["outcome"] == "UNCONVERTED" and row["amount_minor_units"] == 3 for row in summary["by_outcome"])
    assert any(row["cost_status"] == "INCOMPLETE" and row["amount_minor_units"] is None for row in summary["by_outcome"])


def test_late_final_usage_appends_actual_cost_and_excludes_incomplete_placeholder(conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    common = dict(tenant_id=tenant_a, case_id=case_id, order_id=None, business_key="voice:late:1",
                  request_hash=sha256_hex("voice:late:1"), cost_kind="VOICE", outcome="FAILED",
                  manual_remediation=False, quantity="12.50", unit="second", occurred_at=_NOW,
                  evidence={"provider": "mock"})
    with repo_db.tenant_transaction(conn, tenant_a):
        incomplete = billing_repository.record_operational_cost(
            conn, cost_id=str(uuid.uuid4()), cost_status="INCOMPLETE", amount_minor_units=None,
            currency=None, currency_scale_ref=None, provider_usage_ref=None, **common)
        actual = billing_repository.record_operational_cost(
            conn, cost_id=str(uuid.uuid4()), cost_status="ACTUAL", amount_minor_units=12,
            currency="JPY", currency_scale_ref="iso4217-minor-unit-0", provider_usage_ref="voice-final-1", **common)
        summary = billing_repository.cost_summary_by_outcome(conn, tenant_id=tenant_a, period_start=_NOW, period_end=_END)
    assert actual["supersedes_cost_id"] == incomplete["id"]
    assert not any(row["cost_status"] == "INCOMPLETE" for row in summary["by_outcome"])
    assert any(row["currency"] == "JPY" and row["amount_minor_units"] == 12 for row in summary["by_outcome"])
