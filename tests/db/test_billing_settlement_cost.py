"""ENG-12 acceptance probes through the production Postgres repositories."""
from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal

import psycopg
import pytest

from db.repository import billing_repository, db as repo_db, refund_repository
from db.repository.errors import IdempotencyConflict, ImmutableRecordViolation, RepositoryError, translate_integrity_error


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
    refund_id_2 = str(uuid.uuid4())
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
        with pytest.raises(IdempotencyConflict):
            billing_repository.record_settlement_reversal(
                conn, tenant_id=tenant_a, reversal_id=str(uuid.uuid4()), refund_id=refund_id,
                original_entry_id=revenue["id"], business_key="settlement:refund-100:replayed-key",
                amount_minor_units=10, basis={"refund_ratio": "1/10"}, occurred_at=_NOW,
            )
        refund_repository.reserve_refund(
            conn, tenant_id=tenant_a, payment_id=chain["payment_id"], refund_id=refund_id_2,
            business_key="refund:order-100:second-partial", amount_minor_units=100, currency="TWD",
            currency_scale_ref="iso4217-minor-unit-2",
        )
        refund_repository.mark_refund_succeeded(
            conn, tenant_id=tenant_a, refund_id=refund_id_2, provider_refund_id="provider-refund-101",
            source_revision="provider-v1", evidence={"formal_status": "SUCCEEDED"},
        )
        with pytest.raises(RepositoryError, match="exceed") as excinfo:
            billing_repository.record_settlement_reversal(
                conn, tenant_id=tenant_a, reversal_id=str(uuid.uuid4()), refund_id=refund_id_2,
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
    assert not isinstance(excinfo.value, IdempotencyConflict)


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
            currency=None, currency_scale_ref=None, provider_usage_ref="voice-final-1", **common)
        actual = billing_repository.record_operational_cost(
            conn, cost_id=str(uuid.uuid4()), cost_status="ACTUAL", amount_minor_units=12,
            currency="JPY", currency_scale_ref="iso4217-minor-unit-0", provider_usage_ref="voice-final-1", **common)
        replay = billing_repository.record_operational_cost(
            conn, cost_id=str(uuid.uuid4()), cost_status="ACTUAL", amount_minor_units=12,
            currency="JPY", currency_scale_ref="iso4217-minor-unit-0", provider_usage_ref="voice-final-1", **common)
        summary = billing_repository.cost_summary_by_outcome(conn, tenant_id=tenant_a, period_start=_NOW, period_end=_END)
    assert actual["supersedes_cost_id"] == incomplete["id"]
    assert replay["id"] == actual["id"]
    assert not any(row["cost_status"] == "INCOMPLETE" for row in summary["by_outcome"])
    assert any(row["currency"] == "JPY" and row["amount_minor_units"] == 12 for row in summary["by_outcome"])


def test_cost_finalization_rejects_cross_case_or_kind_and_decimal_replay(conn, tenant_a, case_factory):
    first_case = case_factory(tenant_a)
    other_case = case_factory(tenant_a)
    common = dict(tenant_id=tenant_a, order_id=None, business_key="voice:identity:1",
                  request_hash=sha256_hex("voice:identity:1"), cost_kind="VOICE", outcome="FAILED",
                  manual_remediation=False, quantity=Decimal("12.50"), unit="second", occurred_at=_NOW,
                  evidence={"provider": "mock"})
    with repo_db.tenant_transaction(conn, tenant_a):
        billing_repository.record_operational_cost(
            conn, cost_id=str(uuid.uuid4()), case_id=first_case, cost_status="INCOMPLETE",
            amount_minor_units=None, currency=None, currency_scale_ref=None, provider_usage_ref="identity-ref", **common,
        )
        with pytest.raises(IdempotencyConflict):
            billing_repository.record_operational_cost(
                conn, cost_id=str(uuid.uuid4()), case_id=other_case, cost_status="ACTUAL",
                amount_minor_units=12, currency="JPY", currency_scale_ref="iso4217-minor-unit-0",
                provider_usage_ref="identity-ref", **common,
            )
        with pytest.raises(IdempotencyConflict):
            billing_repository.record_operational_cost(
                conn, cost_id=str(uuid.uuid4()), case_id=first_case, cost_kind="MODEL", cost_status="ACTUAL",
                amount_minor_units=12, currency="JPY", currency_scale_ref="iso4217-minor-unit-0",
                provider_usage_ref="identity-ref", **{k: v for k, v in common.items() if k != "cost_kind"},
            )
        with pytest.raises(IdempotencyConflict):
            billing_repository.record_operational_cost(
                conn, cost_id=str(uuid.uuid4()), case_id=first_case, cost_status="ACTUAL",
                amount_minor_units=12, currency="JPY", currency_scale_ref="iso4217-minor-unit-0",
                provider_usage_ref="different-ref", **common,
            )
        with pytest.raises(IdempotencyConflict):
            billing_repository.record_operational_cost(
                conn, tenant_id=tenant_a, cost_id=str(uuid.uuid4()), case_id=other_case, order_id=None,
                business_key="voice:identity:other", request_hash=sha256_hex("voice:identity:other"),
                cost_kind="VOICE", outcome="FAILED", cost_status="ACTUAL", manual_remediation=False,
                quantity="1", unit="second", amount_minor_units=1, currency="JPY",
                currency_scale_ref="iso4217-minor-unit-0", provider_usage_ref="identity-ref",
                occurred_at=_NOW, evidence={},
            )


def test_jpy_partial_refund_commission_reversal_and_cross_currency_rejection(
    conn, tenant_a, case_factory, payment_chain_factory
):
    case_id = case_factory(tenant_a)
    chain = payment_chain_factory(tenant_a, case_id, 1000, "JPY", "iso4217-minor-unit-0")
    contract_version_id = _contract(conn, tenant_a)
    refund_id = str(uuid.uuid4())
    with repo_db.tenant_transaction(conn, tenant_a):
        # This contract is deliberately TWD, so its currency cannot be reused
        # for a JPY settlement row.
        billing_repository.record_order_attribution(
            conn, tenant_id=tenant_a, order_id=chain["order_id"], attribution_kind="CHANNEL_CUSTOMER",
            source_channel="partner-jp", source_customer_ref="jp-100", evidence={}, attributed_at=_NOW,
        )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                billing_repository.record_settlement_entry(
                    conn, tenant_id=tenant_a, entry_id=str(uuid.uuid4()), order_id=chain["order_id"],
                    contract_version_id=contract_version_id, attribution_kind="CHANNEL_CUSTOMER", entry_kind="GMV",
                    business_key="jpy:wrong-contract", amount_minor_units=1000, currency="JPY",
                    currency_scale_ref="iso4217-minor-unit-0", basis={}, occurred_at=_NOW,
                )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                billing_repository.record_business_fee(
                    conn, tenant_id=tenant_a, fee_id=str(uuid.uuid4()), contract_version_id=contract_version_id,
                    business_key="jpy:wrong-fee-contract", request_hash=sha256_hex("jpy:wrong-fee-contract"),
                    usage_kind="CASE", usage_quantity=1, unit="case", amount_minor_units=1, currency="JPY",
                    currency_scale_ref="iso4217-minor-unit-0", occurred_at=_NOW, evidence={},
                )
        commission = billing_repository.record_settlement_entry(
            conn, tenant_id=tenant_a, entry_id=str(uuid.uuid4()), order_id=chain["order_id"],
            contract_version_id=None, attribution_kind="CHANNEL_CUSTOMER", entry_kind="CHANNEL_COMMISSION",
            business_key="jpy:commission", amount_minor_units=100, currency="JPY",
            currency_scale_ref="iso4217-minor-unit-0", basis={"original": 1000}, occurred_at=_NOW,
        )
        refund_repository.reserve_refund(conn, tenant_id=tenant_a, payment_id=chain["payment_id"], refund_id=refund_id,
                                         business_key="jpy:refund", amount_minor_units=500, currency="JPY",
                                         currency_scale_ref="iso4217-minor-unit-0")
        refund_repository.mark_refund_succeeded(conn, tenant_id=tenant_a, refund_id=refund_id,
                                                  provider_refund_id="jpy-provider", source_revision="v1", evidence={})
        reversal = billing_repository.record_settlement_reversal(
            conn, tenant_id=tenant_a, reversal_id=str(uuid.uuid4()), refund_id=refund_id,
            original_entry_id=commission["id"], business_key="jpy:commission:refund", amount_minor_units=50,
            basis={"refund_ratio": "1/2"}, occurred_at=_NOW,
        )
    assert reversal["amount_minor_units"] == -50
    assert reversal["currency"] == "JPY"


def test_original_customer_cannot_receive_channel_commission(conn, tenant_a, case_factory, payment_chain_factory):
    case_id = case_factory(tenant_a)
    chain = payment_chain_factory(tenant_a, case_id, 100)
    with repo_db.tenant_transaction(conn, tenant_a):
        billing_repository.record_order_attribution(
            conn, tenant_id=tenant_a, order_id=chain["order_id"], attribution_kind="ORIGINAL_CUSTOMER",
            source_channel=None, source_customer_ref="merchant-crm", evidence={}, attributed_at=_NOW,
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                billing_repository.record_settlement_entry(
                    conn, tenant_id=tenant_a, entry_id=str(uuid.uuid4()), order_id=chain["order_id"],
                    contract_version_id=None, attribution_kind="ORIGINAL_CUSTOMER", entry_kind="CHANNEL_COMMISSION",
                    business_key="original:commission", amount_minor_units=10, currency="TWD",
                    currency_scale_ref="iso4217-minor-unit-2", basis={}, occurred_at=_NOW,
                )


def test_cost_summary_excludes_cancelled_human_and_superseded_rows_from_automatic_success(
    conn, tenant_a, case_factory
):
    case_id = case_factory(tenant_a)
    base = dict(tenant_id=tenant_a, case_id=case_id, order_id=None, request_hash=sha256_hex("automatic"),
                outcome="SUCCEEDED", cost_status="ACTUAL", manual_remediation=False, quantity="1", unit="request",
                amount_minor_units=1, currency="TWD", currency_scale_ref="iso4217-minor-unit-2", occurred_at=_NOW,
                evidence={})
    with repo_db.tenant_transaction(conn, tenant_a):
        billing_repository.record_operational_cost(
            conn, cost_id=str(uuid.uuid4()), business_key="automatic:old", cost_kind="MODEL",
            provider_usage_ref="automatic-old", **base,
        )
        billing_repository.record_operational_cost(
            conn, cost_id=str(uuid.uuid4()), business_key="automatic:human", cost_kind="HUMAN",
            provider_usage_ref="automatic-human", outcome="CANCELLED", manual_remediation=False, **{
                k: v for k, v in base.items() if k not in {"outcome", "manual_remediation"}
            },
        )
        summary = billing_repository.cost_summary_by_outcome(
            conn, tenant_id=tenant_a, period_start=_NOW, period_end=_END,
        )
    assert summary["automatic_success_case_count"] == 0
    assert any(row["outcome"] == "CANCELLED" for row in summary["by_outcome"])


def test_decimal_cost_replay_and_later_period_human_do_not_change_this_period(conn, tenant_a, case_factory):
    case_id = case_factory(tenant_a)
    args = dict(tenant_id=tenant_a, case_id=case_id, order_id=None, business_key="decimal:replay",
                request_hash=sha256_hex("decimal:replay"), cost_kind="MODEL", outcome="SUCCEEDED",
                cost_status="ACTUAL", manual_remediation=False, quantity=Decimal("1.250"), unit="request",
                amount_minor_units=1, currency="TWD", currency_scale_ref="iso4217-minor-unit-2",
                provider_usage_ref="decimal-replay", occurred_at=_NOW, evidence={})
    with repo_db.tenant_transaction(conn, tenant_a):
        first = billing_repository.record_operational_cost(conn, cost_id=str(uuid.uuid4()), **args)
        replay = billing_repository.record_operational_cost(
            conn, cost_id=str(uuid.uuid4()), **{**args, "quantity": Decimal("1.25")}
        )
        billing_repository.record_operational_cost(
            conn, tenant_id=tenant_a, cost_id=str(uuid.uuid4()), case_id=case_id, order_id=None,
            business_key="future:human",
            request_hash=sha256_hex("future:human"), cost_kind="HUMAN", outcome="CANCELLED", cost_status="ACTUAL",
            manual_remediation=False, quantity="1", unit="minute", amount_minor_units=1, currency="TWD",
            currency_scale_ref="iso4217-minor-unit-2", provider_usage_ref="future-human",
            occurred_at="2026-12-02T00:00:00+00:00", evidence={},
        )
        summary = billing_repository.cost_summary_by_outcome(conn, tenant_id=tenant_a, period_start=_NOW, period_end=_END)
    assert first["id"] == replay["id"]
    assert summary["automatic_success_case_count"] == 1


def test_cost_summary_excludes_prior_human_but_keeps_currencies_separate(conn, tenant_a, case_factory):
    remediated_case = case_factory(tenant_a)
    automatic_case = case_factory(tenant_a)
    with repo_db.tenant_transaction(conn, tenant_a):
        billing_repository.record_operational_cost(
            conn, tenant_id=tenant_a, cost_id=str(uuid.uuid4()), case_id=remediated_case, order_id=None,
            business_key="prior:human", request_hash=sha256_hex("prior:human"), cost_kind="HUMAN",
            outcome="CANCELLED", cost_status="ACTUAL", manual_remediation=False, quantity="1", unit="minute",
            amount_minor_units=3, currency="TWD", currency_scale_ref="iso4217-minor-unit-2",
            provider_usage_ref="prior-human", occurred_at="2026-11-26T00:00:00+00:00", evidence={},
        )
        for case_id, key, currency, scale, amount in (
            (remediated_case, "prior:model", "TWD", "iso4217-minor-unit-2", 10),
            (automatic_case, "automatic:jpy", "JPY", "iso4217-minor-unit-0", 20),
        ):
            billing_repository.record_operational_cost(
                conn, tenant_id=tenant_a, cost_id=str(uuid.uuid4()), case_id=case_id, order_id=None,
                business_key=key, request_hash=sha256_hex(key), cost_kind="MODEL", outcome="SUCCEEDED",
                cost_status="ACTUAL", manual_remediation=False, quantity="1", unit="request",
                amount_minor_units=amount, currency=currency, currency_scale_ref=scale,
                provider_usage_ref=key, occurred_at=_NOW, evidence={},
            )
        summary = billing_repository.cost_summary_by_outcome(conn, tenant_id=tenant_a, period_start=_NOW, period_end=_END)
    amounts = {(row["outcome"], row["currency"]): row["amount_minor_units"] for row in summary["by_outcome"]}
    assert summary["automatic_success_case_count"] == 1
    assert amounts[("SUCCEEDED", "TWD")] == 10
    assert amounts[("SUCCEEDED", "JPY")] == 20


def test_billing_schema_has_rls_and_immutable_records_for_all_eng12_tables(
    conn, admin_database_url, tenant_a, tenant_b, case_factory, payment_chain_factory
):
    case_id = case_factory(tenant_a)
    case_b = case_factory(tenant_b)
    chain = payment_chain_factory(tenant_a, case_id, 100)
    contract_id = _contract(conn, tenant_a)
    with repo_db.tenant_transaction(conn, tenant_a):
        fee = billing_repository.record_business_fee(
            conn, tenant_id=tenant_a, fee_id=str(uuid.uuid4()), contract_version_id=contract_id,
            business_key="schema:fee", request_hash=sha256_hex("schema:fee"), usage_kind="CASE", usage_quantity=1,
            unit="case", amount_minor_units=1, currency="TWD", currency_scale_ref="iso4217-minor-unit-2",
            occurred_at=_NOW, evidence={},
        )
        attribution = billing_repository.record_order_attribution(
            conn, tenant_id=tenant_a, order_id=chain["order_id"], attribution_kind="DIRECT_CUSTOMER",
            source_channel=None, source_customer_ref="site", evidence={}, attributed_at=_NOW,
        )
        settlement = billing_repository.record_settlement_entry(
            conn, tenant_id=tenant_a, entry_id=str(uuid.uuid4()), order_id=chain["order_id"],
            contract_version_id=contract_id, attribution_kind="DIRECT_CUSTOMER", entry_kind="GMV",
            business_key="schema:settlement", amount_minor_units=100, currency="TWD",
            currency_scale_ref="iso4217-minor-unit-2", basis={}, occurred_at=_NOW,
        )
        cost = billing_repository.record_operational_cost(
            conn, tenant_id=tenant_a, cost_id=str(uuid.uuid4()), case_id=case_id, order_id=None,
            business_key="schema:cost", request_hash=sha256_hex("schema:cost"), cost_kind="MODEL",
            outcome="SUCCEEDED", cost_status="ACTUAL", manual_remediation=False, quantity="1", unit="request",
            amount_minor_units=1, currency="TWD", currency_scale_ref="iso4217-minor-unit-2",
            provider_usage_ref="schema-cost", occurred_at=_NOW, evidence={},
        )
        tables = ("billing_contract_version", "business_fee_charge", "order_attribution", "settlement_entry", "operational_cost_record")
        for table in tables:
            assert conn.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", (table,)
            ).fetchone() == (True, True)
    with repo_db.tenant_transaction(conn, tenant_b):
        for table in tables:
            assert conn.execute(f"SELECT 1 FROM {table} WHERE tenant_id=%s", (tenant_a,)).fetchone() is None
    updates = (
        ("billing_contract_version", "id", contract_id, "version = 2"),
        ("business_fee_charge", "id", fee["id"], "amount_minor_units = 2"),
        ("order_attribution", "order_id", attribution["order_id"], "source_customer_ref = 'changed'"),
        ("settlement_entry", "id", settlement["id"], "amount_minor_units = 2"),
        ("operational_cost_record", "id", cost["id"], "amount_minor_units = 2"),
    )
    with psycopg.connect(admin_database_url, autocommit=True) as admin_conn:
        # These writes bypass RLS so this is a migration-level proof that every
        # child relation carries tenant ownership in its FK, rather than merely
        # relying on an application-side tenant filter.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            admin_conn.execute(
                """INSERT INTO business_fee_charge
                   (tenant_id,id,contract_version_id,operation,business_key,request_hash,usage_kind,usage_quantity,
                    unit,amount_minor_units,currency,currency_scale_ref,occurred_at)
                   VALUES (%s,%s,%s,'ENTERPRISE_USAGE_FEE','cross:fee',%s,'CASE',1,'case',1,'TWD',
                           'iso4217-minor-unit-2',%s)""",
                (tenant_b, str(uuid.uuid4()), contract_id, sha256_hex("cross:fee"), _NOW),
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            admin_conn.execute(
                """INSERT INTO order_attribution
                   (tenant_id,order_id,attribution_kind,source_customer_ref,attributed_at)
                   VALUES (%s,%s,'DIRECT_CUSTOMER','cross',%s)""",
                (tenant_b, chain["order_id"], _NOW),
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            admin_conn.execute(
                """INSERT INTO settlement_entry
                   (tenant_id,id,order_id,attribution_kind,entry_kind,business_key,amount_minor_units,
                    currency,currency_scale_ref,basis,occurred_at)
                   VALUES (%s,%s,%s,'DIRECT_CUSTOMER','GMV','cross:settlement',1,'TWD',
                           'iso4217-minor-unit-2','{}'::jsonb,%s)""",
                (tenant_b, str(uuid.uuid4()), chain["order_id"], _NOW),
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            admin_conn.execute(
                """INSERT INTO operational_cost_record
                   (tenant_id,id,case_id,business_key,request_hash,cost_kind,outcome,cost_status,
                    quantity,unit,amount_minor_units,currency,currency_scale_ref,occurred_at)
                   VALUES (%s,%s,%s,'cross:case',%s,'MODEL','FAILED','ACTUAL',1,'request',1,'TWD',
                           'iso4217-minor-unit-2',%s)""",
                (tenant_b, str(uuid.uuid4()), case_id, sha256_hex("cross:case"), _NOW),
            )
        # order_id is intentionally NULL: this must still reject the tenant-A
        # parent through the four-column self-reference.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            admin_conn.execute(
                """INSERT INTO operational_cost_record
                   (tenant_id,id,case_id,business_key,request_hash,cost_kind,outcome,cost_status,
                    quantity,unit,amount_minor_units,currency,currency_scale_ref,supersedes_cost_id,occurred_at)
                   VALUES (%s,%s,%s,'cross:supersedes',%s,'MODEL','SUCCEEDED','ACTUAL',1,'request',1,'TWD',
                           'iso4217-minor-unit-2',%s,%s)""",
                (tenant_b, str(uuid.uuid4()), case_b, sha256_hex("cross:supersedes"), cost["id"], _NOW),
            )
        for table, key, identifier, assignment in updates:
            with pytest.raises(psycopg.Error) as excinfo:
                admin_conn.execute(f"UPDATE {table} SET {assignment} WHERE tenant_id=%s AND {key}=%s", (tenant_a, identifier))
            assert isinstance(translate_integrity_error(excinfo.value), ImmutableRecordViolation)
        for table, key, identifier in (
            ("billing_contract_version", "id", contract_id),
            ("business_fee_charge", "id", fee["id"]),
            ("order_attribution", "order_id", attribution["order_id"]),
            ("settlement_entry", "id", settlement["id"]),
            ("operational_cost_record", "id", cost["id"]),
        ):
            with pytest.raises(psycopg.Error) as excinfo:
                admin_conn.execute(f"DELETE FROM {table} WHERE tenant_id=%s AND {key}=%s", (tenant_a, identifier))
            assert isinstance(translate_integrity_error(excinfo.value), ImmutableRecordViolation)
