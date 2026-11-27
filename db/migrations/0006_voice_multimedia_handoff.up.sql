-- ENG-10: durable voice, transfer and asynchronous-media handoff records.
-- This records provider facts and policy decisions; it is deliberately not a
-- substitute for a telecom account or a real payment gateway integration.

BEGIN;

CREATE TABLE voice_session (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    transport text NOT NULL CHECK (transport IN ('WEBRTC', 'SIP_TEST')),
    provider_session_ref text NOT NULL,
    status text NOT NULL CHECK (status IN ('CONNECTING', 'ACTIVE', 'TRANSFERRING', 'DISCONNECTED', 'CLOSED')),
    recording_policy jsonb NOT NULL,
    recording_status text NOT NULL CHECK (recording_status IN ('NOT_REQUESTED', 'NOTICE_GIVEN', 'DECLINED', 'RECORDING', 'REDACTED')),
    case_owner_revision integer NOT NULL CHECK (case_owner_revision >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, transport, provider_session_ref),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id)
);
CREATE TRIGGER voice_session_set_updated_at BEFORE UPDATE ON voice_session FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE voice_session ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_session FORCE ROW LEVEL SECURITY;
CREATE POLICY voice_session_tenant_isolation ON voice_session USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON voice_session TO app_role;

CREATE TABLE voice_turn (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    turn_no integer NOT NULL CHECK (turn_no >= 1),
    demand_revision integer NOT NULL CHECK (demand_revision >= 1),
    status text NOT NULL CHECK (status IN ('PARTIAL', 'FINAL', 'CONFIRMED', 'SUPERSEDED')),
    transcript_ref text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, session_id, turn_no),
    FOREIGN KEY (tenant_id, session_id) REFERENCES voice_session(tenant_id, id)
);
ALTER TABLE voice_turn ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_turn FORCE ROW LEVEL SECURITY;
CREATE POLICY voice_turn_tenant_isolation ON voice_turn USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON voice_turn TO app_role;

CREATE TABLE voice_playback (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    demand_revision integer NOT NULL CHECK (demand_revision >= 1),
    status text NOT NULL CHECK (status IN ('QUEUED', 'PLAYING', 'PLAYED', 'INTERRUPTED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, session_id) REFERENCES voice_session(tenant_id, id)
);
CREATE TRIGGER voice_playback_set_updated_at BEFORE UPDATE ON voice_playback FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE voice_playback ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_playback FORCE ROW LEVEL SECURITY;
CREATE POLICY voice_playback_tenant_isolation ON voice_playback USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON voice_playback TO app_role;

CREATE TABLE voice_transfer (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    destination_ref text NOT NULL,
    status text NOT NULL CHECK (status IN ('REQUESTED', 'RINGING', 'CONNECTED', 'FAILED')),
    provider_result_ref text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, session_id) REFERENCES voice_session(tenant_id, id)
);
CREATE TRIGGER voice_transfer_set_updated_at BEFORE UPDATE ON voice_transfer FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE voice_transfer ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_transfer FORCE ROW LEVEL SECURITY;
CREATE POLICY voice_transfer_tenant_isolation ON voice_transfer USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE ON voice_transfer TO app_role;

CREATE TABLE asynchronous_media_intake (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    source_event_id text NOT NULL,
    media_kind text NOT NULL CHECK (media_kind IN ('AUDIO_MESSAGE', 'IMAGE', 'VIDEO', 'DOCUMENT')),
    asset_ref text NOT NULL,
    status text NOT NULL CHECK (status IN ('RECEIVED', 'SCANNING', 'READY', 'REJECTED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, source_event_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES case_record(tenant_id, id)
);
CREATE TRIGGER asynchronous_media_intake_immutable BEFORE UPDATE OR DELETE ON asynchronous_media_intake FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE asynchronous_media_intake ENABLE ROW LEVEL SECURITY;
ALTER TABLE asynchronous_media_intake FORCE ROW LEVEL SECURITY;
CREATE POLICY asynchronous_media_intake_tenant_isolation ON asynchronous_media_intake USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON asynchronous_media_intake TO app_role;

CREATE TABLE voice_payment_handoff (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    order_id uuid,
    payment_link_ref text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, session_id) REFERENCES voice_session(tenant_id, id),
    FOREIGN KEY (tenant_id, order_id) REFERENCES order_record(tenant_id, id)
);
CREATE TRIGGER voice_payment_handoff_immutable BEFORE UPDATE OR DELETE ON voice_payment_handoff FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();
ALTER TABLE voice_payment_handoff ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_payment_handoff FORCE ROW LEVEL SECURITY;
CREATE POLICY voice_payment_handoff_tenant_isolation ON voice_payment_handoff USING (tenant_id = current_setting('app.tenant_id', true)::uuid) WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
GRANT SELECT, INSERT ON voice_payment_handoff TO app_role;

COMMIT;
