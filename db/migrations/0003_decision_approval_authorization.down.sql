-- Rollback for 0003_decision_approval_authorization. Safe against an
-- empty-of-data schema only.

BEGIN;

ALTER TABLE execution_task DROP CONSTRAINT IF EXISTS execution_task_tenant_id_authorization_use_id_fkey;

DROP TABLE IF EXISTS authorization_use;
DROP TABLE IF EXISTS execution_authorization;
DROP TABLE IF EXISTS approval_revocation;
DROP TABLE IF EXISTS customer_consent;
DROP TABLE IF EXISTS approval_record;
DROP TRIGGER IF EXISTS decision_request_guard_mutation ON decision_request;
DROP FUNCTION IF EXISTS decision_request_guard_mutation();
DROP TABLE IF EXISTS decision_request;

COMMIT;
