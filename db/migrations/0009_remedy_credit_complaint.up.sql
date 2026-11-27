-- ENG-07: remedy actions, Credit ledger, notification delivery and explicit
-- complaint closure. Source: docs/sd/credit-and-refund.md §1-7.
-- This extends (rather than rewrites) the ENG-02 payment/refund baseline.

BEGIN;

CREATE TABLE remedy_preview (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    complaint_id uuid,
    order_id uuid NOT NULL,
    payment_id uuid,
    work_id uuid NOT NULL,
    order_revision integer NOT NULL CHECK (order_revision >= 1),
    policy_version text NOT NULL,
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    preview_payload jsonb NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id),
    FOREIGN KEY (tenant_id, complaint_id) REFERENCES complaint(tenant_id, id),
    FOREIGN KEY (tenant_id, order_id) REFERENCES order_record(tenant_id, id),
    FOREIGN KEY (tenant_id, payment_id) REFERENCES payment(tenant_id, id),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id)
);
CREATE TRIGGER remedy_preview_immutable BEFORE UPDATE OR DELETE ON remedy_preview
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE remedy_preview ENABLE ROW LEVEL SECURITY;
ALTER TABLE remedy_preview FORCE ROW LEVEL SECURITY;
CREATE POLICY remedy_preview_tenant_isolation ON remedy_preview
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON remedy_preview TO app_role;

CREATE TABLE remedy_action (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    preview_id uuid NOT NULL,
    complaint_id uuid,
    work_id uuid NOT NULL,
    root_task_id uuid,
    selected_item_id text NOT NULL,
    action_type text NOT NULL CHECK (action_type IN ('REFUND', 'CREDIT_GRANT', 'CREDIT_REVERSAL', 'OTHER')),
    business_key text NOT NULL,
    authorization_ref jsonb NOT NULL,
    customer_consent_ref jsonb,
    state text NOT NULL CHECK (state IN ('RESERVED', 'SUBMITTED', 'PENDING', 'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, preview_id, selected_item_id),
    UNIQUE (tenant_id, business_key),
    FOREIGN KEY (tenant_id, preview_id) REFERENCES remedy_preview(tenant_id, id),
    FOREIGN KEY (tenant_id, complaint_id) REFERENCES complaint(tenant_id, id),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id),
    FOREIGN KEY (tenant_id, root_task_id) REFERENCES execution_task(tenant_id, id)
);
CREATE TRIGGER remedy_action_set_updated_at BEFORE UPDATE ON remedy_action
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE remedy_action ENABLE ROW LEVEL SECURITY;
ALTER TABLE remedy_action FORCE ROW LEVEL SECURITY;
CREATE POLICY remedy_action_tenant_isolation ON remedy_action
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON remedy_action TO app_role;

-- The ENG-02 refund row remains the reservation/counter source of truth; this
-- optional link supplies ENG-07's selected, approved remedy provenance.
ALTER TABLE refund ADD COLUMN remedy_action_id uuid;
ALTER TABLE refund ADD CONSTRAINT refund_remedy_action_fkey
    FOREIGN KEY (tenant_id, remedy_action_id) REFERENCES remedy_action(tenant_id, id);

CREATE TABLE credit_account (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    issuer text NOT NULL,
    beneficiary_ref jsonb NOT NULL,
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, id, currency)
);
CREATE TRIGGER credit_account_set_updated_at BEFORE UPDATE ON credit_account
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE credit_account ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_account FORCE ROW LEVEL SECURITY;
CREATE POLICY credit_account_tenant_isolation ON credit_account
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON credit_account TO app_role;

CREATE TABLE credit_grant (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    account_id uuid NOT NULL,
    remedy_action_id uuid,
    grant_operation_key text NOT NULL,
    issued_amount_minor_units bigint NOT NULL CHECK (issued_amount_minor_units > 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    terms_version text NOT NULL,
    scope jsonb NOT NULL,
    valid_from timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    state text NOT NULL CHECK (state IN ('PENDING', 'UNKNOWN', 'ACTIVE', 'EXHAUSTED', 'EXPIRED', 'REVOKED', 'FAILED')),
    provider_grant_id text,
    terminal_operation_key text,
    evidence jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, grant_operation_key),
    UNIQUE (tenant_id, id, account_id, currency),
    FOREIGN KEY (tenant_id, account_id, currency) REFERENCES credit_account(tenant_id, id, currency),
    FOREIGN KEY (tenant_id, remedy_action_id) REFERENCES remedy_action(tenant_id, id),
    CONSTRAINT credit_grant_valid_period CHECK (expires_at > valid_from)
);
CREATE UNIQUE INDEX credit_grant_provider_dedupe
    ON credit_grant (tenant_id, provider_grant_id)
    WHERE provider_grant_id IS NOT NULL;
CREATE UNIQUE INDEX credit_grant_terminal_operation_dedupe
    ON credit_grant (tenant_id, terminal_operation_key)
    WHERE terminal_operation_key IS NOT NULL;
CREATE TRIGGER credit_grant_set_updated_at BEFORE UPDATE ON credit_grant
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE credit_grant ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_grant FORCE ROW LEVEL SECURITY;
CREATE POLICY credit_grant_tenant_isolation ON credit_grant
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON credit_grant TO app_role;

CREATE TABLE credit_ledger_entry (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    account_id uuid NOT NULL,
    grant_id uuid NOT NULL,
    entry_type text NOT NULL CHECK (entry_type IN ('ISSUE', 'REDEEM', 'REDEEM_REVERSAL', 'EXPIRE', 'REVOKE')),
    amount_minor_units bigint NOT NULL CHECK (amount_minor_units > 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    business_key text NOT NULL,
    source_operation jsonb NOT NULL,
    reversal_of uuid,
    occurred_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, business_key),
    UNIQUE (tenant_id, reversal_of),
    FOREIGN KEY (tenant_id, account_id, currency) REFERENCES credit_account(tenant_id, id, currency),
    FOREIGN KEY (tenant_id, grant_id, account_id, currency)
        REFERENCES credit_grant(tenant_id, id, account_id, currency),
    FOREIGN KEY (tenant_id, reversal_of) REFERENCES credit_ledger_entry(tenant_id, id),
    CONSTRAINT credit_ledger_reversal_requires_original CHECK (
        (entry_type = 'REDEEM_REVERSAL') = (reversal_of IS NOT NULL)
    )
);
CREATE TRIGGER credit_ledger_entry_immutable BEFORE UPDATE OR DELETE ON credit_ledger_entry
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE credit_ledger_entry ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_ledger_entry FORCE ROW LEVEL SECURITY;
CREATE POLICY credit_ledger_entry_tenant_isolation ON credit_ledger_entry
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON credit_ledger_entry TO app_role;

CREATE TABLE credit_usage_reservation (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    account_id uuid NOT NULL,
    grant_id uuid NOT NULL,
    order_id uuid NOT NULL,
    redeem_operation_key text NOT NULL,
    amount_minor_units bigint NOT NULL CHECK (amount_minor_units > 0),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    state text NOT NULL CHECK (state IN ('HELD', 'CONSUMED', 'RELEASED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, redeem_operation_key),
    FOREIGN KEY (tenant_id, account_id, currency) REFERENCES credit_account(tenant_id, id, currency),
    FOREIGN KEY (tenant_id, grant_id, account_id, currency)
        REFERENCES credit_grant(tenant_id, id, account_id, currency),
    FOREIGN KEY (tenant_id, order_id) REFERENCES order_record(tenant_id, id)
);
CREATE TRIGGER credit_usage_reservation_set_updated_at BEFORE UPDATE ON credit_usage_reservation
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE credit_usage_reservation ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_usage_reservation FORCE ROW LEVEL SECURITY;
CREATE POLICY credit_usage_reservation_tenant_isolation ON credit_usage_reservation
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON credit_usage_reservation TO app_role;

-- Notification is a separate delivery record; its failure never rolls back a
-- monetary result. Complaint closure remains an explicit repository command.
CREATE TABLE remedy_notification (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    remedy_action_id uuid NOT NULL,
    business_key text NOT NULL,
    state text NOT NULL CHECK (state IN ('PENDING', 'DELIVERED', 'FAILED')),
    evidence jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, business_key),
    FOREIGN KEY (tenant_id, remedy_action_id) REFERENCES remedy_action(tenant_id, id)
);
CREATE TRIGGER remedy_notification_set_updated_at BEFORE UPDATE ON remedy_notification
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE remedy_notification ENABLE ROW LEVEL SECURITY;
ALTER TABLE remedy_notification FORCE ROW LEVEL SECURITY;
CREATE POLICY remedy_notification_tenant_isolation ON remedy_notification
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON remedy_notification TO app_role;

COMMIT;
