-- Rollback for 0002_work_execution. Safe against an empty-of-data schema only.

BEGIN;

ALTER TABLE completion_evidence DROP CONSTRAINT IF EXISTS completion_evidence_tenant_id_task_id_fkey;
ALTER TABLE escalation DROP CONSTRAINT IF EXISTS escalation_tenant_id_task_id_fkey;

DROP TABLE IF EXISTS execution_attempt_observation;
DROP TABLE IF EXISTS execution_attempt;
DROP TABLE IF EXISTS execution_task;
DROP TABLE IF EXISTS work_event;
DROP TABLE IF EXISTS escalation;
DROP TABLE IF EXISTS completion_evidence;
DROP TABLE IF EXISTS work_context;
DROP TABLE IF EXISTS work_plan;
DROP TABLE IF EXISTS work;

COMMIT;
