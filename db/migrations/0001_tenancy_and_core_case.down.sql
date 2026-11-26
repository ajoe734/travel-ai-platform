-- Rollback for 0001_tenancy_and_core_case.
-- Safe to run against an empty-of-data schema only (see 0001 .md notes for the
-- forward-fix alternative once production rows exist).

BEGIN;

DROP TABLE IF EXISTS complaint;
DROP TABLE IF EXISTS case_conversation;
DROP TABLE IF EXISTS case_record;
DROP FUNCTION IF EXISTS set_updated_at();
DROP FUNCTION IF EXISTS forbid_update_delete();
DROP TABLE IF EXISTS tenant;
-- app_role is a cluster-level role, not schema-owned state; later migrations
-- (0002+) GRANT to it independently of whether 0001 is currently applied, so
-- it is intentionally left in place rather than dropped here. A full cluster
-- teardown (e.g. a disposable CI Postgres container) removes it anyway.
DROP EXTENSION IF EXISTS pgcrypto;

COMMIT;
