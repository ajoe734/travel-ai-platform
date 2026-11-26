-- Rollback for 0005_idempotency_outbox_inbox. Safe against an
-- empty-of-data schema only.

BEGIN;

DROP TABLE IF EXISTS inbox_event_conflict;
DROP TRIGGER IF EXISTS inbox_event_guard_mutation ON inbox_event;
DROP FUNCTION IF EXISTS inbox_event_guard_mutation();
DROP TABLE IF EXISTS inbox_event;
DROP TRIGGER IF EXISTS outbox_event_guard_mutation ON outbox_event;
DROP FUNCTION IF EXISTS outbox_event_guard_mutation();
DROP TABLE IF EXISTS outbox_event;
DROP TABLE IF EXISTS idempotency_key_record;

COMMIT;
