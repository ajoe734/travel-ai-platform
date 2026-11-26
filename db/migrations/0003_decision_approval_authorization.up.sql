-- ENG-02 migration 0003: DecisionRequest and the Approval family.
-- Source: specs/domain/decision-request.schema.json, specs/domain/approval-record.schema.json,
-- docs/sd/authorization-and-approval.md, ADR 0003.

BEGIN;

-- ---------------------------------------------------------------------------
-- DecisionRequest (specs/domain/decision-request.schema.json)
-- Each content revision of "the same decision" is its own immutable row
-- sharing the stable `id`; only `status`/`selected_option_id` may change on
-- an existing revision row (PENDING -> APPROVED/REJECTED/EXPIRED/SUPERSEDED),
-- enforced by a trigger instead of a blanket forbid_update_delete (SD §4:
-- "舊 revision 的展示內容只追加保存" -- content is append-only, status is not).
-- ---------------------------------------------------------------------------
CREATE TABLE decision_request (
    tenant_id              uuid NOT NULL,
    id                     uuid NOT NULL,
    revision               integer NOT NULL CHECK (revision >= 1),
    work_id                uuid NOT NULL,
    decision_type          text NOT NULL CHECK (decision_type ~ '^[A-Z][A-Z_]*$'),
    status                 text NOT NULL CHECK (status IN (
                               'PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', 'SUPERSEDED'
                           )),
    context_refs           jsonb NOT NULL DEFAULT '[]'::jsonb,
    options                jsonb NOT NULL,
    selected_option_id     text,
    impact_summary         text,
    display_payload        jsonb,
    payload_hash           text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    canonicalization_version text NOT NULL CHECK (canonicalization_version = 'travel-canonical-json-v1'),
    target_revision        integer NOT NULL CHECK (target_revision >= 1),
    expires_at             timestamptz NOT NULL,
    requested_role         text NOT NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id, revision),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id),
    CONSTRAINT decision_request_selected_option_matches_status CHECK (
        (status IN ('APPROVED', 'REJECTED')) = (selected_option_id IS NOT NULL)
    )
);

-- At most one PENDING revision per decision thread (SD §4 state machine: a
-- new revision immediately supersedes the old pending one in the same
-- command, it never leaves two PENDING revisions of one decision_id live).
CREATE UNIQUE INDEX decision_request_one_pending_per_id
    ON decision_request (tenant_id, id)
    WHERE status = 'PENDING';

CREATE FUNCTION decision_request_guard_mutation() RETURNS trigger AS $$
BEGIN
    IF NEW.work_id IS DISTINCT FROM OLD.work_id
       OR NEW.decision_type IS DISTINCT FROM OLD.decision_type
       OR NEW.options IS DISTINCT FROM OLD.options
       OR NEW.display_payload IS DISTINCT FROM OLD.display_payload
       OR NEW.payload_hash IS DISTINCT FROM OLD.payload_hash
       OR NEW.canonicalization_version IS DISTINCT FROM OLD.canonicalization_version
       OR NEW.target_revision IS DISTINCT FROM OLD.target_revision
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
       OR NEW.requested_role IS DISTINCT FROM OLD.requested_role
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'IMMUTABLE_RECORD: decision_request content fields are append-only; only status/selected_option_id/impact_summary/context_refs may change (SD authorization-and-approval.md §4)'
            USING ERRCODE = '0A000';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER decision_request_guard_mutation
    BEFORE UPDATE ON decision_request
    FOR EACH ROW EXECUTE FUNCTION decision_request_guard_mutation();

ALTER TABLE decision_request ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_request FORCE ROW LEVEL SECURITY;
CREATE POLICY decision_request_tenant_isolation ON decision_request
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON decision_request TO app_role;

-- ---------------------------------------------------------------------------
-- ApprovalRecord (specs/domain/approval-record.schema.json root schema)
-- FK into decision_request(tenant_id, id, revision) means an ApprovalRecord
-- can only reference a revision that actually exists, under the same
-- tenant; UNIQUE(tenant_id, decision_id, reviewed_revision) then prevents
-- that exact revision being approved twice (SD §2).
-- ---------------------------------------------------------------------------
CREATE TABLE approval_record (
    tenant_id                uuid NOT NULL,
    id                       uuid NOT NULL,
    decision_id              uuid NOT NULL,
    reviewed_revision        integer NOT NULL CHECK (reviewed_revision >= 1),
    approved_by              jsonb NOT NULL,
    verified_actor_ref       text NOT NULL,
    approved_payload         jsonb NOT NULL,
    policy_version           text,
    canonicalization_version text NOT NULL CHECK (canonicalization_version = 'travel-canonical-json-v1'),
    payload_hash             text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    scope_manifest           jsonb NOT NULL,
    approved_at              timestamptz NOT NULL,
    expires_at               timestamptz,
    confirmation_evidence    text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, decision_id, reviewed_revision),
    FOREIGN KEY (tenant_id, decision_id, reviewed_revision)
        REFERENCES decision_request (tenant_id, id, revision)
);

CREATE TRIGGER approval_record_immutable
    BEFORE UPDATE OR DELETE ON approval_record
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE approval_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_record FORCE ROW LEVEL SECURITY;
CREATE POLICY approval_record_tenant_isolation ON approval_record
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON approval_record TO app_role;

-- ---------------------------------------------------------------------------
-- CustomerConsent ($defs/CustomerConsent): immutable.
-- ---------------------------------------------------------------------------
CREATE TABLE customer_consent (
    tenant_id             uuid NOT NULL,
    id                    uuid NOT NULL,
    case_id               uuid NOT NULL,
    subject               jsonb NOT NULL,
    target_type           text NOT NULL,
    target_id             uuid NOT NULL,
    target_revision       integer NOT NULL CHECK (target_revision >= 1),
    target_hash           text NOT NULL CHECK (target_hash ~ '^[0-9a-f]{64}$'),
    purpose               text NOT NULL,
    confirmation_nonce_id text NOT NULL,
    evidence_ref          text NOT NULL,
    issued_at             timestamptz NOT NULL,
    expires_at            timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id),
    UNIQUE (tenant_id, confirmation_nonce_id)
);

CREATE TRIGGER customer_consent_immutable
    BEFORE UPDATE OR DELETE ON customer_consent
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE customer_consent ENABLE ROW LEVEL SECURITY;
ALTER TABLE customer_consent FORCE ROW LEVEL SECURITY;
CREATE POLICY customer_consent_tenant_isolation ON customer_consent
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON customer_consent TO app_role;

-- ---------------------------------------------------------------------------
-- ApprovalRevocation ($defs/ApprovalRevocation): append-only, never mutates
-- the ApprovalRecord it targets (ADR 0003). `revoked_at` is a read-model
-- projection computed from this table, never a column on approval_record.
-- ---------------------------------------------------------------------------
CREATE TABLE approval_revocation (
    tenant_id    uuid NOT NULL,
    id           uuid NOT NULL,
    approval_id  uuid NOT NULL,
    revoked_by   jsonb NOT NULL,
    reason       text NOT NULL,
    effective_at timestamptz NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, approval_id) REFERENCES approval_record(tenant_id, id)
);

CREATE TRIGGER approval_revocation_immutable
    BEFORE UPDATE OR DELETE ON approval_revocation
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE approval_revocation ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_revocation FORCE ROW LEVEL SECURITY;
CREATE POLICY approval_revocation_tenant_isolation ON approval_revocation
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON approval_revocation TO app_role;

-- ---------------------------------------------------------------------------
-- ExecutionAuthorization ($defs/ExecutionAuthorization): immutable; needs at
-- least one of grant_refs/approval_refs (SD §1, SD-A-10, anyOf in schema).
-- ---------------------------------------------------------------------------
CREATE TABLE execution_authorization (
    tenant_id        uuid NOT NULL,
    id               uuid NOT NULL,
    work_id          uuid NOT NULL,
    root_business_key text NOT NULL,
    capabilities     jsonb NOT NULL,
    resource_refs    jsonb NOT NULL DEFAULT '[]'::jsonb,
    grant_refs       jsonb,
    consent_refs     jsonb,
    approval_refs    jsonb,
    policy_versions  jsonb NOT NULL DEFAULT '[]'::jsonb,
    manifest_hash    text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    expiry           timestamptz,
    issued_at        timestamptz NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id),
    CONSTRAINT execution_authorization_basis_present CHECK (
        grant_refs IS NOT NULL OR approval_refs IS NOT NULL
    )
);

CREATE TRIGGER execution_authorization_immutable
    BEFORE UPDATE OR DELETE ON execution_authorization
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE execution_authorization ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_authorization FORCE ROW LEVEL SECURITY;
CREATE POLICY execution_authorization_tenant_isolation ON execution_authorization
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON execution_authorization TO app_role;

-- ---------------------------------------------------------------------------
-- AuthorizationUse ($defs/AuthorizationUse): immutable; UNIQUE per
-- authorization_id (SD §5: "每 authorization 唯一，綁定後不換 task").
-- AUTHORIZATION_USE_ALREADY_BOUND (error-codes.json) maps to a violation of
-- the UNIQUE(tenant_id, authorization_id) constraint below.
-- ---------------------------------------------------------------------------
CREATE TABLE authorization_use (
    tenant_id         uuid NOT NULL,
    id                uuid NOT NULL,
    authorization_id  uuid NOT NULL,
    root_task_id      uuid NOT NULL,
    root_business_key text NOT NULL,
    request_hash      text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    used_at           timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, authorization_id),
    FOREIGN KEY (tenant_id, authorization_id) REFERENCES execution_authorization(tenant_id, id),
    FOREIGN KEY (tenant_id, root_task_id) REFERENCES execution_task(tenant_id, id)
);

CREATE TRIGGER authorization_use_immutable
    BEFORE UPDATE OR DELETE ON authorization_use
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE authorization_use ENABLE ROW LEVEL SECURITY;
ALTER TABLE authorization_use FORCE ROW LEVEL SECURITY;
CREATE POLICY authorization_use_tenant_isolation ON authorization_use
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON authorization_use TO app_role;

-- Now that authorization_use exists, close the loop on execution_task.
ALTER TABLE execution_task
    ADD FOREIGN KEY (tenant_id, authorization_use_id) REFERENCES authorization_use(tenant_id, id);

COMMIT;
