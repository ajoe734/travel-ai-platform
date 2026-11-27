-- ENG-08: immutable service revisions and per-channel publication projection.
-- A ServiceVersion is intentionally separate from an Order: an existing
-- order keeps the version it promised even when the service is republished.
BEGIN;

CREATE TABLE service_version (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    service_id uuid NOT NULL,
    version integer NOT NULL CHECK (version >= 1),
    content jsonb NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    approval_id uuid,
    approved_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, service_id, version),
    FOREIGN KEY (tenant_id, approval_id) REFERENCES approval_record(tenant_id, id)
);
CREATE TRIGGER service_version_immutable BEFORE UPDATE OR DELETE ON service_version
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE service_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_version FORCE ROW LEVEL SECURITY;
CREATE POLICY service_version_tenant_isolation ON service_version
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON service_version TO app_role;

-- Access is a separate, explicit projection. Connector capability alone is
-- not permission to publish (AGENTS.md execution invariants).
CREATE TABLE channel_publication_access (
    tenant_id uuid NOT NULL,
    channel text NOT NULL,
    connector_account_id text NOT NULL,
    environment text NOT NULL CHECK (environment IN ('PRODUCTION','SANDBOX','MOCK')),
    publication_enabled boolean NOT NULL,
    reason text,
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, channel, connector_account_id, environment)
);
CREATE TRIGGER channel_publication_access_set_updated_at BEFORE UPDATE ON channel_publication_access
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE channel_publication_access ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_publication_access FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_publication_access_tenant_isolation ON channel_publication_access
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON channel_publication_access TO app_role;

CREATE TABLE channel_publication (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    service_version_id uuid NOT NULL,
    channel text NOT NULL,
    connector_account_id text NOT NULL,
    environment text NOT NULL CHECK (environment IN ('PRODUCTION','SANDBOX','MOCK')),
    business_key text NOT NULL,
    desired_version integer NOT NULL CHECK (desired_version >= 1),
    submitted_version integer,
    observed_version integer,
    status text NOT NULL CHECK (status IN ('NOT_STARTED','PENDING','UNKNOWN','LIVE','FAILED','BLOCKED')),
    external_reference text,
    reconciliation_token text,
    observed_at timestamptz,
    failure_reason text,
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, service_version_id, channel, connector_account_id, environment),
    UNIQUE (tenant_id, business_key),
    FOREIGN KEY (tenant_id, service_version_id) REFERENCES service_version(tenant_id, id),
    CONSTRAINT publication_pending_has_submission CHECK (
      status NOT IN ('PENDING','UNKNOWN','LIVE') OR submitted_version IS NOT NULL
    ),
    CONSTRAINT publication_live_is_readback CHECK (
      status <> 'LIVE' OR (observed_version = desired_version AND observed_at IS NOT NULL AND external_reference IS NOT NULL)
    )
);
CREATE TRIGGER channel_publication_set_updated_at BEFORE UPDATE ON channel_publication
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE channel_publication ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_publication FORCE ROW LEVEL SECURITY;
CREATE POLICY channel_publication_tenant_isolation ON channel_publication
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON channel_publication TO app_role;
COMMIT;
