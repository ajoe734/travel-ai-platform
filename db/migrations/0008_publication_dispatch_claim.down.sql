BEGIN;
UPDATE channel_publication SET status='UNKNOWN', failure_reason='ROLLBACK_REQUIRED: dispatch claim pending reconciliation',
  reconciliation_token=COALESCE(reconciliation_token, 'rollback-dispatch-claim:' || business_key)
  WHERE status='DISPATCHING';
ALTER TABLE channel_publication DROP CONSTRAINT channel_publication_status_check;
ALTER TABLE channel_publication ADD CONSTRAINT channel_publication_status_check
  CHECK (status IN ('NOT_STARTED','PENDING','UNKNOWN','LIVE','FAILED','BLOCKED'));
COMMIT;
