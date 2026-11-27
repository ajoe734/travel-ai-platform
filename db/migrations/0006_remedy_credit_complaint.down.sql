-- Rollback is only safe before any ENG-07 operational records exist. Once
-- refunds/Credit have been issued, use a forward-fix migration to preserve
-- the immutable evidence and ledger history.
BEGIN;
DROP TABLE IF EXISTS remedy_notification;
DROP TABLE IF EXISTS credit_usage_reservation;
DROP TABLE IF EXISTS credit_ledger_entry;
DROP TABLE IF EXISTS credit_grant;
DROP TABLE IF EXISTS credit_account;
DROP TABLE IF EXISTS remedy_action;
DROP TABLE IF EXISTS remedy_preview;
COMMIT;
