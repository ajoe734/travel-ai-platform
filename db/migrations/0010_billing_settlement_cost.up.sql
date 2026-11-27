-- ENG-12: versioned enterprise billing, sale attribution, settlement and cost
-- evidence.  Amounts are integer minor units; no row supplies a default rate.
BEGIN;

CREATE TABLE billing_contract_version (
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    id uuid NOT NULL,
    contract_id text NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    terms jsonb NOT NULL,
    terms_hash text NOT NULL CHECK (terms_hash ~ '^[0-9a-f]{64}$'),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    currency_scale_ref text NOT NULL,
    effective_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, contract_id, version),
    UNIQUE (tenant_id, id, currency)
);
-- A contract/version is the evidence used when a usage charge is recorded;
-- corrections create a new version, never alter the old commercial terms.
CREATE TRIGGER billing_contract_version_immutable BEFORE UPDATE OR DELETE ON billing_contract_version
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE billing_contract_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_contract_version FORCE ROW LEVEL SECURITY;
CREATE POLICY billing_contract_version_tenant_isolation ON billing_contract_version
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON billing_contract_version TO app_role;

CREATE TABLE business_fee_charge (
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    id uuid NOT NULL,
    contract_version_id uuid NOT NULL,
    operation text NOT NULL CHECK (operation IN ('ENTERPRISE_USAGE_FEE')),
    business_key text NOT NULL,
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    usage_kind text NOT NULL,
    usage_quantity bigint NOT NULL CHECK (usage_quantity > 0),
    unit text NOT NULL,
    amount_minor_units bigint NOT NULL CHECK (amount_minor_units >= 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    currency_scale_ref text NOT NULL,
    occurred_at timestamptz NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, operation, business_key),
    FOREIGN KEY (tenant_id, contract_version_id, currency)
        REFERENCES billing_contract_version(tenant_id, id, currency)
);
CREATE TRIGGER business_fee_charge_immutable BEFORE UPDATE OR DELETE ON business_fee_charge
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE business_fee_charge ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_fee_charge FORCE ROW LEVEL SECURITY;
CREATE POLICY business_fee_charge_tenant_isolation ON business_fee_charge
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON business_fee_charge TO app_role;

CREATE TABLE order_attribution (
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    order_id uuid NOT NULL,
    attribution_kind text NOT NULL CHECK (attribution_kind IN ('ORIGINAL_CUSTOMER', 'CHANNEL_CUSTOMER', 'DIRECT_CUSTOMER')),
    source_channel text,
    source_customer_ref text,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    attributed_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, order_id),
    UNIQUE (tenant_id, order_id, attribution_kind),
    FOREIGN KEY (tenant_id, order_id) REFERENCES order_record(tenant_id, id),
    CONSTRAINT order_attribution_channel_required CHECK (
        attribution_kind <> 'CHANNEL_CUSTOMER' OR source_channel IS NOT NULL
    )
);
CREATE TRIGGER order_attribution_immutable BEFORE UPDATE OR DELETE ON order_attribution
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE order_attribution ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_attribution FORCE ROW LEVEL SECURITY;
CREATE POLICY order_attribution_tenant_isolation ON order_attribution
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON order_attribution TO app_role;

CREATE TABLE settlement_entry (
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    id uuid NOT NULL,
    order_id uuid NOT NULL,
    refund_id uuid,
    contract_version_id uuid,
    attribution_kind text NOT NULL CHECK (attribution_kind IN ('ORIGINAL_CUSTOMER', 'CHANNEL_CUSTOMER', 'DIRECT_CUSTOMER')),
    entry_kind text NOT NULL CHECK (entry_kind IN ('GMV', 'PLATFORM_REVENUE', 'CHANNEL_COMMISSION', 'SUPPLIER_PAYABLE')),
    business_key text NOT NULL,
    amount_minor_units bigint NOT NULL CHECK (amount_minor_units <> 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    currency_scale_ref text NOT NULL,
    basis jsonb NOT NULL,
    reversal_of uuid,
    occurred_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, business_key),
    UNIQUE (tenant_id, id, currency),
    UNIQUE (tenant_id, id, order_id, entry_kind, attribution_kind, currency),
    FOREIGN KEY (tenant_id, order_id) REFERENCES order_record(tenant_id, id),
    FOREIGN KEY (tenant_id, refund_id) REFERENCES refund(tenant_id, id),
    FOREIGN KEY (tenant_id, contract_version_id, currency)
        REFERENCES billing_contract_version(tenant_id, id, currency),
    FOREIGN KEY (tenant_id, order_id, attribution_kind)
        REFERENCES order_attribution(tenant_id, order_id, attribution_kind),
    FOREIGN KEY (tenant_id, reversal_of, order_id, entry_kind, attribution_kind, currency)
        REFERENCES settlement_entry(tenant_id, id, order_id, entry_kind, attribution_kind, currency),
    CONSTRAINT settlement_reversal_shape CHECK (
        (reversal_of IS NULL AND refund_id IS NULL) OR (reversal_of IS NOT NULL AND refund_id IS NOT NULL)
    ),
    CONSTRAINT settlement_entry_sign_shape CHECK (
        (reversal_of IS NULL AND amount_minor_units > 0) OR (reversal_of IS NOT NULL AND amount_minor_units < 0)
    ),
    CONSTRAINT settlement_channel_commission_attribution CHECK (
        entry_kind <> 'CHANNEL_COMMISSION' OR attribution_kind = 'CHANNEL_CUSTOMER'
    )
);
CREATE TRIGGER settlement_entry_immutable BEFORE UPDATE OR DELETE ON settlement_entry
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE settlement_entry ENABLE ROW LEVEL SECURITY;
ALTER TABLE settlement_entry FORCE ROW LEVEL SECURITY;
CREATE POLICY settlement_entry_tenant_isolation ON settlement_entry
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON settlement_entry TO app_role;

CREATE UNIQUE INDEX settlement_reversal_once_per_refund
    ON settlement_entry (tenant_id, reversal_of, refund_id)
    WHERE reversal_of IS NOT NULL;

CREATE TABLE operational_cost_record (
    tenant_id uuid NOT NULL REFERENCES tenant(id),
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    order_id uuid,
    business_key text NOT NULL,
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    cost_kind text NOT NULL CHECK (cost_kind IN ('VOICE', 'MODEL', 'MESSAGE', 'QUERY', 'HUMAN')),
    outcome text NOT NULL CHECK (outcome IN ('SUCCEEDED', 'UNCONVERTED', 'FAILED', 'CANCELLED')),
    cost_status text NOT NULL CHECK (cost_status IN ('ACTUAL', 'ESTIMATED', 'INCOMPLETE')),
    manual_remediation boolean NOT NULL DEFAULT false,
    quantity numeric NOT NULL CHECK (quantity >= 0),
    unit text NOT NULL,
    amount_minor_units bigint,
    currency text CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    currency_scale_ref text,
    provider_usage_ref text,
    supersedes_cost_id uuid,
    occurred_at timestamptz NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, business_key),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id),
    FOREIGN KEY (tenant_id, order_id) REFERENCES order_record(tenant_id, id),
    FOREIGN KEY (tenant_id, supersedes_cost_id) REFERENCES operational_cost_record(tenant_id, id),
    CONSTRAINT operational_cost_amount_shape CHECK (
        (amount_minor_units IS NULL AND currency IS NULL AND currency_scale_ref IS NULL)
        OR (amount_minor_units IS NOT NULL AND amount_minor_units >= 0 AND currency IS NOT NULL AND currency_scale_ref IS NOT NULL)
    ),
    CONSTRAINT operational_cost_incomplete_amount_shape CHECK (
        (cost_status = 'INCOMPLETE') = (amount_minor_units IS NULL)
    )
);
CREATE TRIGGER operational_cost_record_immutable BEFORE UPDATE OR DELETE ON operational_cost_record
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE operational_cost_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE operational_cost_record FORCE ROW LEVEL SECURITY;
CREATE POLICY operational_cost_record_tenant_isolation ON operational_cost_record
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON operational_cost_record TO app_role;

CREATE UNIQUE INDEX operational_cost_provider_usage_dedupe
    ON operational_cost_record (tenant_id, provider_usage_ref)
    WHERE provider_usage_ref IS NOT NULL;
CREATE UNIQUE INDEX operational_cost_one_finalization_per_incomplete
    ON operational_cost_record (tenant_id, supersedes_cost_id)
    WHERE supersedes_cost_id IS NOT NULL;

COMMIT;
