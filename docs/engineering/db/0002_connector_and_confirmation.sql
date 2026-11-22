-- Travel AI Platform migration 0002 v0.1.0
-- Adds the connector account and trusted customer confirmation records required by API v0.1.0.
-- Execute only after 0001 has been reviewed and applied to a disposable/test database.
BEGIN;

CREATE TABLE travel.connector_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  branch_id uuid,
  provider text NOT NULL,
  account_ref text NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DISABLED','REAUTH_REQUIRED','SUSPENDED')),
  granted_scopes jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(granted_scopes) = 'array'),
  capability_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  credential_secret_ref text NOT NULL,
  last_health_check_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, provider, account_ref),
  FOREIGN KEY (tenant_id, branch_id) REFERENCES travel.branches(tenant_id, id)
);

ALTER TABLE travel.execution_tasks
  ADD CONSTRAINT execution_tasks_connector_account_fk
  FOREIGN KEY (tenant_id, connector_account_id)
  REFERENCES travel.connector_accounts(tenant_id, id);

ALTER TABLE travel.execution_tasks
  ADD CONSTRAINT execution_tasks_approval_fk
  FOREIGN KEY (tenant_id, approval_id)
  REFERENCES travel.approvals(tenant_id, id);

CREATE TABLE travel.customer_confirmations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES travel.tenants(id),
  case_id uuid NOT NULL,
  quote_id uuid NOT NULL,
  channel text NOT NULL,
  channel_event_id text NOT NULL,
  confirmation_method text NOT NULL CHECK (confirmation_method IN ('SIGNED_ACTION','AUTHENTICATED_UI','VERIFIED_MESSAGE','HUMAN_RECORDED')),
  quote_revision integer NOT NULL,
  quote_payload_hash char(64) NOT NULL,
  customer_ref text NOT NULL,
  verified_at timestamptz NOT NULL,
  expires_at timestamptz,
  verification_evidence_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, channel, channel_event_id),
  FOREIGN KEY (tenant_id, case_id) REFERENCES travel.cases(tenant_id, id),
  FOREIGN KEY (tenant_id, quote_id) REFERENCES travel.quotes(tenant_id, id),
  CHECK (expires_at IS NULL OR expires_at > verified_at)
);

ALTER TABLE travel.bookings
  ADD COLUMN customer_confirmation_id uuid;

ALTER TABLE travel.bookings
  ADD CONSTRAINT bookings_customer_confirmation_fk
  FOREIGN KEY (tenant_id, customer_confirmation_id)
  REFERENCES travel.customer_confirmations(tenant_id, id);

ALTER TABLE travel.customer_confirmations
  ADD CONSTRAINT customer_confirmations_evidence_fk
  FOREIGN KEY (tenant_id, verification_evidence_id)
  REFERENCES travel.evidence(tenant_id, id);

-- Required in ENG-02B: enable and FORCE RLS on all tenant-owned tables,
-- including these two tables, then add tenant_id = current_setting('app.tenant_id')::uuid policies.
-- The app role must not own tables and must not have BYPASSRLS.
COMMIT;
