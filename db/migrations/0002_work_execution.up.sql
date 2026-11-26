-- ENG-02 migration 0002: Work and ExecutionTask/ExecutionAttempt.
-- Source: specs/domain/work.schema.json, specs/domain/execution-task.schema.json,
-- specs/domain/execution-attempt.schema.json, docs/sd/work-execution-contract.md §2-4.

BEGIN;

-- ---------------------------------------------------------------------------
-- Work (specs/domain/work.schema.json)
-- Status-conditional nested objects (waiting_input/.../cancellation) are kept
-- as jsonb columns with a CHECK mirroring each schema allOf branch, so the
-- same "present iff status X" invariant the JSON Schema encodes is enforced
-- again at the row level rather than only trusted from the API layer.
-- ---------------------------------------------------------------------------
CREATE TABLE work (
    tenant_id                    uuid NOT NULL,
    id                           uuid NOT NULL,
    case_id                      uuid NOT NULL,
    work_type                    text NOT NULL CHECK (work_type ~ '^[A-Z][A-Z_]*$'),
    objective                    text NOT NULL,
    completion_contract_version  text NOT NULL,
    completion_conditions        jsonb NOT NULL,
    principal                    jsonb NOT NULL,
    authority_context            jsonb,
    status                       text NOT NULL CHECK (status IN (
                                     'DRAFT', 'RUNNING', 'WAITING_INPUT', 'WAITING_DECISION',
                                     'WAITING_EXTERNAL', 'VERIFYING', 'PARTIAL', 'COMPLETED',
                                     'FAILED', 'CANCELLED'
                                 )),
    revision                     integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    waiting_input                jsonb,
    waiting_decision              jsonb,
    waiting_external             jsonb,
    completion_record            jsonb,
    partial_summary               jsonb,
    failure                      jsonb,
    cancellation                 jsonb,
    created_at                   timestamptz NOT NULL DEFAULT now(),
    updated_at                   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id),
    CONSTRAINT work_waiting_input_matches_status CHECK (
        (status = 'WAITING_INPUT') = (waiting_input IS NOT NULL)
    ),
    CONSTRAINT work_waiting_decision_matches_status CHECK (
        (status = 'WAITING_DECISION') = (waiting_decision IS NOT NULL)
    ),
    CONSTRAINT work_waiting_external_matches_status CHECK (
        (status = 'WAITING_EXTERNAL') = (waiting_external IS NOT NULL)
    ),
    CONSTRAINT work_completion_record_matches_status CHECK (
        (status = 'COMPLETED') = (completion_record IS NOT NULL)
    ),
    CONSTRAINT work_partial_summary_matches_status CHECK (
        (status = 'PARTIAL') = (partial_summary IS NOT NULL)
    ),
    CONSTRAINT work_failure_matches_status CHECK (
        (status = 'FAILED') = (failure IS NOT NULL)
    ),
    -- SD §3: a Work may only reach FAILED once there are no unresolved
    -- irreversible side effects (work.schema.json failure.irreversible_effects_resolved const=true).
    CONSTRAINT work_failure_irreversible_effects_resolved CHECK (
        failure IS NULL OR (failure ->> 'irreversible_effects_resolved')::boolean IS TRUE
    ),
    CONSTRAINT work_cancellation_matches_status CHECK (
        (status = 'CANCELLED') = (cancellation IS NOT NULL)
    )
);

CREATE TRIGGER work_set_updated_at
    BEFORE UPDATE ON work
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE work ENABLE ROW LEVEL SECURITY;
ALTER TABLE work FORCE ROW LEVEL SECURITY;
CREATE POLICY work_tenant_isolation ON work
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON work TO app_role;

-- WorkPlan: (tenant_id, work_id, plan_revision) unique, append-only (SD §2).
CREATE TABLE work_plan (
    tenant_id      uuid NOT NULL,
    work_id        uuid NOT NULL,
    plan_revision  integer NOT NULL CHECK (plan_revision >= 1),
    steps          jsonb NOT NULL,
    planner_version text NOT NULL,
    context_refs   jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, work_id, plan_revision),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id)
);

CREATE TRIGGER work_plan_immutable
    BEFORE UPDATE OR DELETE ON work_plan
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE work_plan ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_plan FORCE ROW LEVEL SECURITY;
CREATE POLICY work_plan_tenant_isolation ON work_plan
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON work_plan TO app_role;

-- WorkContext: typed reference from a Work to Order/Quote/ServiceVersion/etc.
-- (work.schema.json $defs/WorkContext). Mutable (purpose/target_revision may
-- be refreshed), unlike WorkPlan/CompletionEvidence.
CREATE TABLE work_context (
    tenant_id       uuid NOT NULL,
    id              uuid NOT NULL,
    work_id         uuid NOT NULL,
    ref_kind        text NOT NULL CHECK (ref_kind IN (
                        'ORDER', 'QUOTE', 'SERVICE_VERSION', 'COMPLAINT', 'PUBLICATION', 'ASSET', 'OTHER'
                    )),
    target_tenant_id uuid NOT NULL,
    target_id       uuid NOT NULL,
    target_revision integer CHECK (target_revision IS NULL OR target_revision >= 1),
    purpose         text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id),
    CONSTRAINT work_context_target_same_tenant CHECK (target_tenant_id = tenant_id),
    UNIQUE (tenant_id, work_id, ref_kind, target_id)
);

CREATE TRIGGER work_context_set_updated_at
    BEFORE UPDATE ON work_context
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE work_context ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_context FORCE ROW LEVEL SECURITY;
CREATE POLICY work_context_tenant_isolation ON work_context
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON work_context TO app_role;

-- CompletionEvidence: immutable (work.schema.json $defs/CompletionEvidence).
CREATE TABLE completion_evidence (
    tenant_id        uuid NOT NULL,
    id               uuid NOT NULL,
    work_id          uuid NOT NULL,
    task_id          uuid,
    evidence_type    text NOT NULL,
    source_account   text,
    environment      text NOT NULL CHECK (environment IN ('PRODUCTION', 'SANDBOX', 'MOCK')),
    external_ref     text NOT NULL,
    source_revision  text,
    observed_at      timestamptz NOT NULL,
    verified_at      timestamptz,
    payload_ref      text,
    payload_hash     text CHECK (payload_hash IS NULL OR payload_hash ~ '^[0-9a-f]{64}$'),
    verifier_version text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id)
);

CREATE TRIGGER completion_evidence_immutable
    BEFORE UPDATE OR DELETE ON completion_evidence
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE completion_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE completion_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY completion_evidence_tenant_isolation ON completion_evidence
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON completion_evidence TO app_role;

-- Escalation: mutable (OPEN -> RESOLVED), independent of task/work status (SD §2).
CREATE TABLE escalation (
    tenant_id      uuid NOT NULL,
    id             uuid NOT NULL,
    work_id        uuid NOT NULL,
    task_id        uuid,
    reason         text NOT NULL,
    owner          jsonb NOT NULL,
    due_at         timestamptz NOT NULL,
    status         text NOT NULL CHECK (status IN ('OPEN', 'RESOLVED')),
    resolution_ref text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id)
);

CREATE TRIGGER escalation_set_updated_at
    BEFORE UPDATE ON escalation
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE escalation ENABLE ROW LEVEL SECURITY;
ALTER TABLE escalation FORCE ROW LEVEL SECURITY;
CREATE POLICY escalation_tenant_isolation ON escalation
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON escalation TO app_role;

-- WorkEvent: append-only, (tenant_id, work_id, sequence) unique (SD §2/§8).
CREATE TABLE work_event (
    tenant_id         uuid NOT NULL,
    work_id           uuid NOT NULL,
    sequence          bigint NOT NULL CHECK (sequence >= 1),
    event_type        text NOT NULL,
    schema_version    text NOT NULL,
    causation_id      uuid,
    correlation_id    uuid,
    resource_revision integer,
    payload           jsonb NOT NULL,
    occurred_at       timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, work_id, sequence),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id)
);

CREATE TRIGGER work_event_immutable
    BEFORE UPDATE OR DELETE ON work_event
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE work_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_event FORCE ROW LEVEL SECURITY;
CREATE POLICY work_event_tenant_isolation ON work_event
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON work_event TO app_role;

-- ---------------------------------------------------------------------------
-- ExecutionTask (specs/domain/execution-task.schema.json)
-- parent_task_id must be same tenant AND same Work (SD §2): enforced via a
-- composite FK against a (tenant_id, work_id, id) unique key on this same
-- table, rather than a same-tenant-only FK plus an application-level check.
-- ---------------------------------------------------------------------------
CREATE TABLE execution_task (
    tenant_id             uuid NOT NULL,
    id                    uuid NOT NULL,
    work_id               uuid NOT NULL,
    kind                  text NOT NULL CHECK (kind IN ('ACTION', 'GROUP')),
    parent_task_id        uuid,
    operation             text NOT NULL CHECK (operation ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'),
    business_key          text NOT NULL,
    request_hash          text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    request_snapshot      jsonb NOT NULL,
    status                text NOT NULL CHECK (status IN (
                              'NEW', 'VALIDATING', 'READY', 'EXECUTING', 'WAITING',
                              'VERIFYING', 'UNKNOWN', 'DONE', 'FAILED', 'CANCELLED', 'PARTIAL'
                          )),
    revision              integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    owner_revision        integer NOT NULL DEFAULT 0 CHECK (owner_revision >= 0),
    postcondition_version text NOT NULL,
    postcondition         jsonb NOT NULL,
    authorization_use_id  uuid,
    manifest_item_id      text,
    deadline              timestamptz,
    next_run_at           timestamptz,
    lease_holder          text,
    lease_fence_token     bigint CHECK (lease_fence_token IS NULL OR lease_fence_token >= 1),
    lease_until           timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, work_id, id),
    UNIQUE (tenant_id, operation, business_key),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id),
    FOREIGN KEY (tenant_id, work_id, parent_task_id) REFERENCES execution_task(tenant_id, work_id, id),
    -- SD §4: PARTIAL is only a valid aggregation state for a GROUP task.
    CONSTRAINT execution_task_partial_requires_group CHECK (
        status <> 'PARTIAL' OR kind = 'GROUP'
    ),
    -- SD authorization-and-approval.md §5 / execution-task.schema.json allOf:
    -- a child ACTION task consuming an AuthorizationUse must pin exactly one
    -- manifest_item_id; a GROUP root may hold authorization_use_id for the
    -- whole manifest without one.
    CONSTRAINT execution_task_action_manifest_item CHECK (
        kind <> 'ACTION' OR authorization_use_id IS NULL OR manifest_item_id IS NOT NULL
    )
);

CREATE TRIGGER execution_task_set_updated_at
    BEFORE UPDATE ON execution_task
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE execution_task ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_task FORCE ROW LEVEL SECURITY;
CREATE POLICY execution_task_tenant_isolation ON execution_task
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON execution_task TO app_role;

-- ---------------------------------------------------------------------------
-- ExecutionAttempt + ExecutionAttemptObservation
-- (specs/domain/execution-attempt.schema.json): the attempt row itself is
-- fully immutable; new observations are appended as separate rows so "the
-- attempt is append-only" and "observations keep appending" are both true
-- without contradiction (ADR 0001/SD §2).
-- ---------------------------------------------------------------------------
CREATE TABLE execution_attempt (
    tenant_id     uuid NOT NULL,
    id            uuid NOT NULL,
    task_id       uuid NOT NULL,
    attempt_no    integer NOT NULL CHECK (attempt_no >= 1),
    attempt_kind  text NOT NULL CHECK (attempt_kind IN ('DISPATCH', 'RECONCILE', 'VERIFY')),
    fence_token   bigint NOT NULL CHECK (fence_token >= 1),
    request_hash  text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    request_ref   text,
    started_at    timestamptz NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, task_id, attempt_no),
    FOREIGN KEY (tenant_id, task_id) REFERENCES execution_task(tenant_id, id)
);

CREATE TRIGGER execution_attempt_immutable
    BEFORE UPDATE OR DELETE ON execution_attempt
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE execution_attempt ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_attempt FORCE ROW LEVEL SECURITY;
CREATE POLICY execution_attempt_tenant_isolation ON execution_attempt
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON execution_attempt TO app_role;

CREATE TABLE execution_attempt_observation (
    tenant_id        uuid NOT NULL,
    attempt_id       uuid NOT NULL,
    sequence         integer NOT NULL CHECK (sequence >= 1),
    observed_at      timestamptz NOT NULL,
    transport_result text NOT NULL CHECK (transport_result IN (
                          'RESPONSE_RECEIVED', 'TIMEOUT', 'CONNECTION_RESET', 'PARSE_ERROR'
                      )),
    external_ref     text,
    evidence_ref     text,
    outcome          text NOT NULL CHECK (outcome IN ('SUCCEEDED', 'PENDING', 'UNKNOWN', 'FAILED')),
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, attempt_id, sequence),
    FOREIGN KEY (tenant_id, attempt_id) REFERENCES execution_attempt(tenant_id, id)
);

CREATE TRIGGER execution_attempt_observation_immutable
    BEFORE UPDATE OR DELETE ON execution_attempt_observation
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE execution_attempt_observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_attempt_observation FORCE ROW LEVEL SECURITY;
CREATE POLICY execution_attempt_observation_tenant_isolation ON execution_attempt_observation
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON execution_attempt_observation TO app_role;

-- Deferred FKs onto execution_task, now that it exists in this same migration.
ALTER TABLE completion_evidence
    ADD FOREIGN KEY (tenant_id, task_id) REFERENCES execution_task(tenant_id, id);
ALTER TABLE escalation
    ADD FOREIGN KEY (tenant_id, task_id) REFERENCES execution_task(tenant_id, id);

COMMIT;
