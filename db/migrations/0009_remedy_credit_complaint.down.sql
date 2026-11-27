-- Rollback is only safe before any ENG-07 operational records exist. Once
-- refunds/Credit have been issued, use a forward-fix migration to preserve
-- the immutable evidence and ledger history.
BEGIN;
DROP TABLE IF EXISTS remedy_notification;
DROP TABLE IF EXISTS credit_usage_reservation;
DROP TABLE IF EXISTS credit_ledger_entry;
DROP TABLE IF EXISTS credit_grant;
DROP TABLE IF EXISTS credit_account;
ALTER TABLE IF EXISTS refund DROP CONSTRAINT IF EXISTS refund_remedy_action_fkey;
ALTER TABLE IF EXISTS refund DROP COLUMN IF EXISTS remedy_action_id;
DROP TABLE IF EXISTS remedy_action;
DROP TABLE IF EXISTS remedy_preview;
COMMIT;
