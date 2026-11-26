-- ENG-02 migration 0001: tenancy primitives, shared triggers, Case/Complaint.
-- Source: specs/domain/case.schema.json, specs/domain/complaint.schema.json,
-- docs/sd/work-execution-contract.md §1-2, docs/sd/README.md (every business FK carries tenant_id).

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Least-privilege application role. Migrations run as the connecting admin
-- role; the application connects as app_role so RLS (FORCE ROW LEVEL
-- SECURITY below) actually applies -- a table owner/superuser bypasses RLS
-- by default, so tenant isolation evidence must be collected through this
-- role, not through the migration role.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role') THEN
    CREATE ROLE app_role NOLOGIN NOINHERIT;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO app_role;

-- ---------------------------------------------------------------------------
-- Tenant registry. Not part of the ENG-01 domain contracts, but required by
-- ENG-02 so every tenant_id used across fixtures/tests/production carries an
-- explicit environment marking (backlog ENG-02 output: "測試種子與非正式資料
-- 標記"). PRODUCTION tenants are never seeded with example/demo data.
-- ---------------------------------------------------------------------------
CREATE TABLE tenant (
    id            uuid PRIMARY KEY,
    name          text NOT NULL,
    environment   text NOT NULL CHECK (environment IN ('PRODUCTION', 'SANDBOX', 'TEST')),
    created_at    timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT ON tenant TO app_role;

-- ---------------------------------------------------------------------------
-- Shared trigger functions
-- ---------------------------------------------------------------------------

-- Enforces the append-only / immutable objects listed in
-- specs/domain/relationships.md "不可變與 append-only 物件": ApprovalRecord,
-- CustomerConsent, ApprovalRevocation, ExecutionAuthorization,
-- AuthorizationUse, ExecutionAttempt, CompletionEvidence, WorkPlan, WorkEvent.
-- A BEFORE trigger is used (not just REVOKE UPDATE/DELETE) so the guarantee
-- holds even for the table owner/migration role, matching ADR 0003's "不可
-- UPDATE/DELETE" requirement rather than a revocable grant.
CREATE FUNCTION forbid_update_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'IMMUTABLE_RECORD: % on %.% is not permitted (append-only per ADR 0003 / specs/domain/relationships.md)',
        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = '0A000';
END;
$$ LANGUAGE plpgsql;

-- Case/Complaint/Work/... carry updated_at; keep it server-controlled instead
-- of trusting a client-supplied value, matching the revision-based
-- optimistic-concurrency fields fixed in specs/domain/common/identifiers.schema.json.
CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- Case (specs/domain/case.schema.json)
-- ---------------------------------------------------------------------------
CREATE TABLE case_record (
    tenant_id        uuid NOT NULL REFERENCES tenant(id),
    id               uuid NOT NULL,
    revision         integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    case_type        text NOT NULL CHECK (case_type ~ '^[A-Z][A-Z_]*$'),
    status           text NOT NULL CHECK (status IN ('OPEN', 'ARCHIVED')),
    demand_revision  integer NOT NULL CHECK (demand_revision >= 1),
    owner_revision   integer NOT NULL DEFAULT 0 CHECK (owner_revision >= 0),
    current_owner    jsonb NOT NULL,
    next_step        jsonb NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, id, revision)
);

CREATE TRIGGER case_record_set_updated_at
    BEFORE UPDATE ON case_record
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE case_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE case_record FORCE ROW LEVEL SECURITY;
CREATE POLICY case_record_tenant_isolation ON case_record
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON case_record TO app_role;

-- Case <-> Conversation join (SD work-execution-contract.md §1 ERD:
-- CASE_CONVERSATION). Conversation itself is out of ENG-02 scope; this table
-- only fixes the tenant-scoped link shape case.schema.json#conversation_refs
-- requires.
CREATE TABLE case_conversation (
    tenant_id        uuid NOT NULL,
    case_id          uuid NOT NULL,
    conversation_id  uuid NOT NULL,
    linked_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, case_id, conversation_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id)
);

ALTER TABLE case_conversation ENABLE ROW LEVEL SECURITY;
ALTER TABLE case_conversation FORCE ROW LEVEL SECURITY;
CREATE POLICY case_conversation_tenant_isolation ON case_conversation
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, DELETE ON case_conversation TO app_role;

-- ---------------------------------------------------------------------------
-- Complaint (specs/domain/complaint.schema.json)
-- ---------------------------------------------------------------------------
CREATE TABLE complaint (
    tenant_id            uuid NOT NULL,
    id                   uuid NOT NULL,
    revision             integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    case_id              uuid NOT NULL,
    order_id             uuid,
    status               text NOT NULL CHECK (status IN (
                             'OPEN', 'CHECKING', 'WAITING_CUSTOMER', 'WAITING_MERCHANT',
                             'WAITING_CHANNEL', 'RESOLVING', 'RESOLVED', 'CLOSED',
                             'ESCALATED', 'REOPENED'
                         )),
    verification_state   text NOT NULL CHECK (verification_state IN ('UNVERIFIED', 'VERIFIED')),
    customer_statements  jsonb NOT NULL DEFAULT '[]'::jsonb,
    confirmed_facts      jsonb NOT NULL DEFAULT '[]'::jsonb,
    requested_outcome    jsonb NOT NULL,
    remedy_action_refs   jsonb NOT NULL DEFAULT '[]'::jsonb,
    resolution           jsonb,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id),
    -- complaint.schema.json allOf: resolution present iff status is RESOLVED/CLOSED
    -- (resolveComplaint is the only command that may populate it, SD 05).
    CONSTRAINT complaint_resolution_matches_status CHECK (
        (status IN ('RESOLVED', 'CLOSED')) = (resolution IS NOT NULL)
    )
);

CREATE TRIGGER complaint_set_updated_at
    BEFORE UPDATE ON complaint
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE complaint ENABLE ROW LEVEL SECURITY;
ALTER TABLE complaint FORCE ROW LEVEL SECURITY;
CREATE POLICY complaint_tenant_isolation ON complaint
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON complaint TO app_role;

COMMIT;
