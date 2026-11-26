-- ENG-02 migration 0004: Quote/deal snapshot, Order projection, and the
-- minimal Payment/Refund baseline needed to prove atomic refund-quota
-- enforcement (backlog ENG-02 acceptance). Source: specs/domain/order.schema.json,
-- docs/sd/credit-and-refund.md §2-5 (full RemedyPreview/CreditGrant/Ledger/
-- PolicyBudgetReservation/SettlementEntry remain ENG-07 scope per backlog;
-- this migration only fixes the subset ENG-02 explicitly owns: quote/deal
-- snapshots, and a refund reservation primitive proven safe under concurrency).

BEGIN;

-- ---------------------------------------------------------------------------
-- QuoteSnapshot: immutable priced offer a Work/Order points to (backlog
-- ENG-02 output: "保存報價／成交快照"). Full Quote domain (supplier catalog,
-- availability) is out of scope; this fixes the identity + hash + money
-- fields other ENG-02 tables need to reference.
-- ---------------------------------------------------------------------------
CREATE TABLE quote_snapshot (
    tenant_id            uuid NOT NULL,
    id                   uuid NOT NULL,
    case_id              uuid NOT NULL,
    content              jsonb NOT NULL,
    content_hash         text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    total_amount_minor_units text NOT NULL CHECK (total_amount_minor_units ~ '^(0|[1-9][0-9]*)$'),
    total_currency       text NOT NULL CHECK (total_currency ~ '^[A-Z]{3}$'),
    total_currency_scale_ref text NOT NULL,
    expires_at           timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id)
);

CREATE TRIGGER quote_snapshot_immutable
    BEFORE UPDATE OR DELETE ON quote_snapshot
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE quote_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote_snapshot FORCE ROW LEVEL SECURITY;
CREATE POLICY quote_snapshot_tenant_isolation ON quote_snapshot
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON quote_snapshot TO app_role;

-- ---------------------------------------------------------------------------
-- Order (specs/domain/order.schema.json): customer-facing projection; never
-- the merged sum of booking/payment/refund source states (SA 04.2).
-- ---------------------------------------------------------------------------
CREATE TABLE order_record (
    tenant_id       uuid NOT NULL,
    id              uuid NOT NULL,
    case_id         uuid NOT NULL,
    quote_id        uuid NOT NULL,
    status          text NOT NULL CHECK (status IN (
                        'PENDING', 'CONFIRMED', 'COMPLETED', 'CHANGE_PENDING', 'CANCELLED', 'EXCEPTION'
                    )),
    revision        integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    total_amount_minor_units text NOT NULL CHECK (total_amount_minor_units ~ '^(0|[1-9][0-9]*)$'),
    total_currency  text NOT NULL CHECK (total_currency ~ '^[A-Z]{3}$'),
    total_currency_scale_ref text NOT NULL,
    supplier_booking_status text NOT NULL CHECK (supplier_booking_status IN (
                        'NOT_REQUESTED', 'ON_HOLD', 'PENDING', 'CONFIRMED',
                        'CANCEL_REQUESTED', 'CANCELLED', 'EXPIRED', 'UNKNOWN'
                    )),
    supplier_booking_external_ref text,
    supplier_booking_connector_account_id uuid,
    supplier_booking_hold_expires_at timestamptz,
    payment_status  text NOT NULL CHECK (payment_status IN (
                        'NOT_REQUESTED', 'PENDING', 'AUTHORIZED', 'CAPTURED', 'VOIDED', 'UNKNOWN'
                    )),
    payment_collector_account text,
    payment_external_transaction_id text,
    payment_captured_amount_minor_units text CHECK (
        payment_captured_amount_minor_units IS NULL OR payment_captured_amount_minor_units ~ '^(0|[1-9][0-9]*)$'
    ),
    payment_captured_currency text CHECK (
        payment_captured_currency IS NULL OR payment_captured_currency ~ '^[A-Z]{3}$'
    ),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id),
    FOREIGN KEY (tenant_id, quote_id) REFERENCES quote_snapshot(tenant_id, id)
);

CREATE TRIGGER order_record_set_updated_at
    BEFORE UPDATE ON order_record
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE order_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_record FORCE ROW LEVEL SECURITY;
CREATE POLICY order_record_tenant_isolation ON order_record
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON order_record TO app_role;

-- complaint.order_id (declared nullable in 0001, order_record did not exist
-- yet) can now be FK-constrained.
ALTER TABLE complaint
    ADD FOREIGN KEY (tenant_id, order_id) REFERENCES order_record(tenant_id, id);

-- ---------------------------------------------------------------------------
-- Payment: minimal capture record a Refund draws down against. Full
-- Payment/PSP integration is ENG-04/07 scope; this fixes the counters the
-- atomic refund-quota invariant needs. refunded_amount_minor_units only
-- increases when a refund reaches SUCCEEDED; reserved_amount_minor_units
-- tracks the sum of RESERVED/SUBMITTED/PENDING/UNKNOWN refunds against this
-- payment (SD credit-and-refund.md §5.1).
-- ---------------------------------------------------------------------------
CREATE TABLE payment (
    tenant_id                  uuid NOT NULL,
    id                         uuid NOT NULL,
    order_id                   uuid NOT NULL,
    collector_account          text NOT NULL,
    environment                text NOT NULL CHECK (environment IN ('PRODUCTION', 'SANDBOX', 'MOCK')),
    currency                   text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    currency_scale_ref         text NOT NULL,
    captured_amount_minor_units bigint NOT NULL CHECK (captured_amount_minor_units >= 0),
    refunded_amount_minor_units bigint NOT NULL DEFAULT 0 CHECK (refunded_amount_minor_units >= 0),
    reserved_amount_minor_units bigint NOT NULL DEFAULT 0 CHECK (reserved_amount_minor_units >= 0),
    external_transaction_id    text,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, order_id) REFERENCES order_record(tenant_id, id),
    -- SD §5.1 available-balance formula, enforced as a hard floor independent
    -- of any application-layer bug: captured - refunded - reserved >= 0.
    CONSTRAINT payment_balance_not_overdrawn CHECK (
        refunded_amount_minor_units + reserved_amount_minor_units <= captured_amount_minor_units
    )
);

CREATE TRIGGER payment_set_updated_at
    BEFORE UPDATE ON payment
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE payment ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment FORCE ROW LEVEL SECURITY;
CREATE POLICY payment_tenant_isolation ON payment
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON payment TO app_role;

-- ---------------------------------------------------------------------------
-- Refund: merges the Refund + RefundReservation entities from
-- docs/sd/credit-and-refund.md §3 into one row for the ENG-02 baseline (the
-- reservation IS the refund attempt at this stage; splitting them into two
-- entities with their own history is ENG-07 scope). `operation`/`business_key`
-- give the stable UNIQUE(tenant_id, operation, business_key) SD §3 requires
-- so a changed Idempotency-Key can never create a second refund for the same
-- business operation.
-- ---------------------------------------------------------------------------
CREATE TABLE refund (
    tenant_id             uuid NOT NULL,
    id                    uuid NOT NULL,
    payment_id            uuid NOT NULL,
    operation             text NOT NULL DEFAULT 'refund',
    business_key          text NOT NULL,
    amount_minor_units    bigint NOT NULL CHECK (amount_minor_units > 0),
    currency              text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    currency_scale_ref    text NOT NULL,
    state                 text NOT NULL CHECK (state IN (
                              'RESERVED', 'SUBMITTED', 'PENDING', 'UNKNOWN',
                              'SUCCEEDED', 'FAILED', 'CANCELLED'
                          )),
    connector_account_id  uuid,
    environment           text CHECK (environment IS NULL OR environment IN ('PRODUCTION', 'SANDBOX', 'MOCK')),
    provider_refund_id    text,
    source_revision       text,
    evidence              jsonb,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, operation, business_key),
    FOREIGN KEY (tenant_id, payment_id) REFERENCES payment(tenant_id, id)
);

-- SD credit-and-refund.md §3: UNIQUE(tenant_id, connector_account_id,
-- environment, provider_refund_id) prevents importing the same externally
-- observed refund twice.
-- NULLS NOT DISTINCT: connector_account_id/environment are nullable; without
-- it, two imported rows for the same provider_refund_id with both columns
-- NULL would not violate this index (plain UNIQUE treats NULLs as distinct).
CREATE UNIQUE INDEX refund_provider_dedupe
    ON refund (tenant_id, connector_account_id, environment, provider_refund_id)
    NULLS NOT DISTINCT
    WHERE provider_refund_id IS NOT NULL;

CREATE TRIGGER refund_set_updated_at
    BEFORE UPDATE ON refund
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE refund ENABLE ROW LEVEL SECURITY;
ALTER TABLE refund FORCE ROW LEVEL SECURITY;
CREATE POLICY refund_tenant_isolation ON refund
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON refund TO app_role;

COMMIT;
