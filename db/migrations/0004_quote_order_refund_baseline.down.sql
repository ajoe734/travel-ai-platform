-- Rollback for 0004_quote_order_refund_baseline. Safe against an
-- empty-of-data schema only.

BEGIN;

DROP TABLE IF EXISTS refund;
DROP TABLE IF EXISTS payment;
ALTER TABLE complaint DROP CONSTRAINT IF EXISTS complaint_tenant_id_order_id_fkey;
DROP TABLE IF EXISTS order_record;
DROP TABLE IF EXISTS quote_snapshot;

COMMIT;
