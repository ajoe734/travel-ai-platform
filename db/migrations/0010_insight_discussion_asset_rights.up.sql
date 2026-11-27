-- ENG-11 migration 0010: reproducible operating observations, merchant discussion and media rights.
-- Facts, hypotheses and a permission to use an asset deliberately remain separate.
BEGIN;

CREATE TABLE operating_insight (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    query_version text NOT NULL,
    metric_key text NOT NULL,
    period_start timestamptz NOT NULL,
    period_end timestamptz NOT NULL CHECK (period_end > period_start),
    numerator jsonb NOT NULL,
    denominator jsonb NOT NULL,
    coverage jsonb NOT NULL,
    case_dedupe_version text NOT NULL,
    observed_facts jsonb NOT NULL,
    hypotheses jsonb NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs jsonb NOT NULL,
    result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id),
    CHECK (jsonb_typeof(numerator) = 'object' AND jsonb_typeof(denominator) = 'object'
           AND jsonb_typeof(coverage) = 'object' AND jsonb_typeof(observed_facts) = 'array'
           AND jsonb_typeof(hypotheses) = 'array' AND jsonb_typeof(evidence_refs) = 'array')
);

CREATE TABLE change_proposal (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    work_id uuid NOT NULL,
    insight_id uuid,
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    status text NOT NULL CHECK (status IN ('DRAFT','DISCUSSING','VALIDATED','AWAITING_APPROVAL','APPROVED','SUPERSEDED','REJECTED')),
    evidence_refs jsonb NOT NULL,
    hypothesis_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    content_diff jsonb NOT NULL,
    cost_impact jsonb NOT NULL,
    shared_resource_impact jsonb NOT NULL,
    required_material jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id),
    FOREIGN KEY (tenant_id, work_id) REFERENCES work(tenant_id, id),
    FOREIGN KEY (tenant_id, insight_id) REFERENCES operating_insight(tenant_id, id),
    CHECK (jsonb_typeof(evidence_refs) = 'array' AND jsonb_typeof(hypothesis_refs) = 'array'
           AND jsonb_typeof(content_diff) = 'object' AND jsonb_typeof(cost_impact) = 'object'
           AND jsonb_typeof(shared_resource_impact) = 'object' AND jsonb_typeof(required_material) = 'array')
);
CREATE TRIGGER change_proposal_set_updated_at BEFORE UPDATE ON change_proposal FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE merchant_discussion_message (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    proposal_id uuid NOT NULL,
    sequence integer NOT NULL CHECK (sequence >= 1),
    speaker text NOT NULL CHECK (speaker IN ('ASSISTANT','MERCHANT')),
    message_kind text NOT NULL CHECK (message_kind IN ('QUESTION','ANSWER','FACT','HYPOTHESIS','DECISION')),
    body jsonb NOT NULL,
    source_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, proposal_id, sequence),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES change_proposal(tenant_id, id),
    CHECK (jsonb_typeof(body) = 'object' AND jsonb_typeof(source_refs) = 'array')
);

CREATE TABLE material_request (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    proposal_id uuid NOT NULL,
    required_items jsonb NOT NULL,
    requested_channels jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('REQUESTED','PARTIALLY_RECEIVED','SATISFIED','CANCELLED')),
    deadline timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES change_proposal(tenant_id, id),
    CHECK (jsonb_typeof(required_items) = 'array' AND jsonb_typeof(requested_channels) = 'array')
);

CREATE TABLE asset (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    material_request_id uuid,
    proposal_id uuid,
    parent_asset_id uuid,
    source_scope text NOT NULL CHECK (source_scope IN ('MERCHANT_SUBMITTED','COMPLAINT_EVIDENCE','SYSTEM_GENERATED')),
    media_kind text NOT NULL CHECK (media_kind IN ('IMAGE','AUDIO','VIDEO','DOCUMENT')),
    source_ref text NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    scan_status text NOT NULL CHECK (scan_status IN ('RECEIVED','QUARANTINED','CHECKED','REJECTED')),
    lifecycle_status text NOT NULL CHECK (lifecycle_status IN ('RECEIVED','CLARIFYING','READY_FOR_REVIEW','APPROVED','AVAILABLE','REVOKED','EXPIRED','REJECTED')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, material_request_id) REFERENCES material_request(tenant_id, id),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES change_proposal(tenant_id, id),
    FOREIGN KEY (tenant_id, parent_asset_id) REFERENCES asset(tenant_id, id),
    CHECK (jsonb_typeof(metadata) = 'object'),
    CHECK (NOT (source_scope = 'COMPLAINT_EVIDENCE' AND lifecycle_status IN ('APPROVED','AVAILABLE')))
);
CREATE UNIQUE INDEX asset_parent_content_hash_unique ON asset(tenant_id, parent_asset_id, content_hash) WHERE parent_asset_id IS NOT NULL;

CREATE TABLE asset_rights_grant (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    asset_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision >= 1),
    rights_holder_ref text NOT NULL,
    permitted_purposes jsonb NOT NULL,
    permitted_channels jsonb NOT NULL,
    permitted_languages jsonb NOT NULL,
    effective_at timestamptz NOT NULL,
    expires_at timestamptz,
    status text NOT NULL CHECK (status IN ('PENDING','APPROVED','REVOKED','EXPIRED','REJECTED')),
    approval_ref text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, asset_id, revision),
    FOREIGN KEY (tenant_id, asset_id) REFERENCES asset(tenant_id, id),
    CHECK (expires_at IS NULL OR expires_at > effective_at),
    CHECK (jsonb_typeof(permitted_purposes) = 'array' AND jsonb_typeof(permitted_channels) = 'array'
           AND jsonb_typeof(permitted_languages) = 'array')
);

CREATE TABLE proposal_asset_use (
    tenant_id uuid NOT NULL,
    proposal_id uuid NOT NULL,
    asset_id uuid NOT NULL,
    rights_grant_id uuid NOT NULL,
    purpose text NOT NULL,
    channel text NOT NULL,
    language text NOT NULL,
    PRIMARY KEY (tenant_id, proposal_id, asset_id, rights_grant_id, purpose, channel, language),
    FOREIGN KEY (tenant_id, proposal_id) REFERENCES change_proposal(tenant_id, id),
    FOREIGN KEY (tenant_id, asset_id) REFERENCES asset(tenant_id, id),
    FOREIGN KEY (tenant_id, rights_grant_id) REFERENCES asset_rights_grant(tenant_id, id)
);

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['operating_insight','change_proposal','merchant_discussion_message','material_request','asset','asset_rights_grant','proposal_asset_use'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY %I ON %I USING (tenant_id = current_setting(''app.tenant_id'', true)::uuid) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true)::uuid)', t || '_tenant_isolation', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO app_role', t);
  END LOOP;
END $$;

COMMIT;
