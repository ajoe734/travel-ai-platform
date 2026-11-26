-- ENG-02 migration 0005: API idempotency dedupe and the transactional
-- outbox/inbox. Source: docs/sd/work-execution-contract.md §6.1-6.2,
-- docs/sd/connector-result-and-reconciliation.md §6-7.

BEGIN;

-- ---------------------------------------------------------------------------
-- IdempotencyKeyRecord: API-level dedupe keyed on
-- (tenant_id, actor_id, operation, idempotency_key) per SD §6.1. Distinct
-- from the ExecutionTask business_key UNIQUE constraint (0002), which
-- survives a changed idempotency key.
-- ---------------------------------------------------------------------------
CREATE TABLE idempotency_key_record (
    tenant_id         uuid NOT NULL,
    actor_id          uuid NOT NULL,
    operation         text NOT NULL,
    idempotency_key   text NOT NULL,
    request_hash      text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    response_snapshot jsonb NOT NULL,
    resource_ref      jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, actor_id, operation, idempotency_key)
);

CREATE TRIGGER idempotency_key_record_immutable
    BEFORE UPDATE OR DELETE ON idempotency_key_record
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE idempotency_key_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_key_record FORCE ROW LEVEL SECURITY;
CREATE POLICY idempotency_key_record_tenant_isolation ON idempotency_key_record
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON idempotency_key_record TO app_role;

-- ---------------------------------------------------------------------------
-- Outbox: written in the same transaction as the business row it describes
-- (SD connector-result-and-reconciliation.md §7: "outbox 與業務變更同一
-- transaction"). (tenant_id, aggregate_type, aggregate_id, sequence) is
-- unique and append-only; publish/dispatch bookkeeping columns are the only
-- ones a worker may update.
-- ---------------------------------------------------------------------------
CREATE TABLE outbox_event (
    tenant_id         uuid NOT NULL,
    id                uuid NOT NULL,
    aggregate_type    text NOT NULL,
    aggregate_id      uuid NOT NULL,
    sequence          bigint NOT NULL CHECK (sequence >= 1),
    event_type        text NOT NULL,
    schema_version    text NOT NULL,
    causation_id      uuid,
    correlation_id    uuid,
    resource_revision integer,
    payload           jsonb NOT NULL,
    occurred_at       timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    published_at      timestamptz,
    dispatch_attempts integer NOT NULL DEFAULT 0 CHECK (dispatch_attempts >= 0),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, aggregate_type, aggregate_id, sequence)
);

CREATE FUNCTION outbox_event_guard_mutation() RETURNS trigger AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.id IS DISTINCT FROM OLD.id
       OR NEW.aggregate_type IS DISTINCT FROM OLD.aggregate_type
       OR NEW.aggregate_id IS DISTINCT FROM OLD.aggregate_id
       OR NEW.sequence IS DISTINCT FROM OLD.sequence
       OR NEW.event_type IS DISTINCT FROM OLD.event_type
       OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
       OR NEW.causation_id IS DISTINCT FROM OLD.causation_id
       OR NEW.correlation_id IS DISTINCT FROM OLD.correlation_id
       OR NEW.resource_revision IS DISTINCT FROM OLD.resource_revision
       OR NEW.payload IS DISTINCT FROM OLD.payload
       OR NEW.occurred_at IS DISTINCT FROM OLD.occurred_at
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'IMMUTABLE_RECORD: outbox_event business fields are append-only; only published_at/dispatch_attempts may change'
            USING ERRCODE = '0A000';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER outbox_event_guard_mutation
    BEFORE UPDATE ON outbox_event
    FOR EACH ROW EXECUTE FUNCTION outbox_event_guard_mutation();

ALTER TABLE outbox_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_event FORCE ROW LEVEL SECURITY;
CREATE POLICY outbox_event_tenant_isolation ON outbox_event
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON outbox_event TO app_role;

-- ---------------------------------------------------------------------------
-- Inbox: dedupe key is (tenant_id, connector_account_id, environment,
-- producer, source_event_id) per SD connector-result-and-reconciliation.md
-- §7. Same id + same hash is an idempotent ACK (no new row). Same id +
-- different hash must NOT silently update the stored event -- it is
-- quarantined via inbox_event_conflict instead (§7: "隔離告警，不更新交易").
-- ---------------------------------------------------------------------------
CREATE TABLE inbox_event (
    tenant_id            uuid NOT NULL,
    id                   uuid NOT NULL,
    connector_account_id uuid,
    environment          text CHECK (environment IS NULL OR environment IN ('PRODUCTION', 'SANDBOX', 'MOCK')),
    producer             text NOT NULL,
    source_event_id      text NOT NULL,
    raw_hash             text NOT NULL CHECK (raw_hash ~ '^[0-9a-f]{64}$'),
    raw_payload          jsonb NOT NULL,
    received_at          timestamptz NOT NULL DEFAULT now(),
    processing_status    text NOT NULL DEFAULT 'RECEIVED' CHECK (processing_status IN (
                              'RECEIVED', 'PROCESSED', 'QUARANTINED', 'DEAD_LETTER'
                          )),
    processed_at         timestamptz,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, connector_account_id, environment, producer, source_event_id)
);

CREATE FUNCTION inbox_event_guard_mutation() RETURNS trigger AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.id IS DISTINCT FROM OLD.id
       OR NEW.connector_account_id IS DISTINCT FROM OLD.connector_account_id
       OR NEW.environment IS DISTINCT FROM OLD.environment
       OR NEW.producer IS DISTINCT FROM OLD.producer
       OR NEW.source_event_id IS DISTINCT FROM OLD.source_event_id
       OR NEW.raw_hash IS DISTINCT FROM OLD.raw_hash
       OR NEW.raw_payload IS DISTINCT FROM OLD.raw_payload
       OR NEW.received_at IS DISTINCT FROM OLD.received_at
    THEN
        RAISE EXCEPTION 'IMMUTABLE_RECORD: inbox_event identity/payload fields are append-only; only processing_status/processed_at may change'
            USING ERRCODE = '0A000';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inbox_event_guard_mutation
    BEFORE UPDATE ON inbox_event
    FOR EACH ROW EXECUTE FUNCTION inbox_event_guard_mutation();

ALTER TABLE inbox_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_event FORCE ROW LEVEL SECURITY;
CREATE POLICY inbox_event_tenant_isolation ON inbox_event
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON inbox_event TO app_role;

-- Logs a same-id-different-hash conflict without touching the original
-- inbox_event row (§7: 隔離告警，不更新交易). Append-only.
CREATE TABLE inbox_event_conflict (
    tenant_id       uuid NOT NULL,
    id              uuid NOT NULL,
    inbox_event_id  uuid NOT NULL,
    conflicting_hash text NOT NULL CHECK (conflicting_hash ~ '^[0-9a-f]{64}$'),
    conflicting_payload jsonb NOT NULL,
    detected_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, inbox_event_id) REFERENCES inbox_event(tenant_id, id)
);

CREATE TRIGGER inbox_event_conflict_immutable
    BEFORE UPDATE OR DELETE ON inbox_event_conflict
    FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

ALTER TABLE inbox_event_conflict ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_event_conflict FORCE ROW LEVEL SECURITY;
CREATE POLICY inbox_event_conflict_tenant_isolation ON inbox_event_conflict
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT ON inbox_event_conflict TO app_role;

COMMIT;
