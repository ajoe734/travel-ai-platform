# ENG-02 Database Layer

Executable Postgres migrations, a thin repository layer, and the ENG-02
acceptance suite for backlog ENG-02 (`docs/collaboration/backlog.md#eng-02`).
Source contracts: `specs/domain/*`, `docs/sd/work-execution-contract.md`,
`docs/sd/authorization-and-approval.md`, `docs/sd/credit-and-refund.md`,
`docs/sd/connector-result-and-reconciliation.md`.

## Layout

- `migrations/NNNN_name.{up,down}.sql` + matching `.md` — one migration per
  entry, tracked in a `schema_migrations` table. Each `.md` documents its
  rollback and forward-fix story (see each file for the exact boundary
  between "safe to roll back" and "needs a forward-fix migration instead").
- `migrate.py` — dependency-light runner (`upgrade` / `downgrade` / `status`).
- `repository/` — one module per aggregate family; every function takes an
  already-open `psycopg.Connection` positioned inside
  `repository.db.tenant_transaction(conn, tenant_id)` so callers compose
  multiple repository calls into one short command transaction.
- `seeds/load_fixtures.py` — non-production (`environment='TEST'`) seed data.
- `../tests/db/` — the acceptance suite (see below).

## Running against a real Postgres

```bash
pip install -r db/requirements.txt
export DATABASE_URL=postgresql://admin_role:...@host:5432/eng02

python3 db/migrate.py upgrade          # apply every migration
python3 db/migrate.py status           # list applied/pending
python3 db/migrate.py downgrade --to 0 # full teardown, for the empty-db rebuild check
python3 db/migrate.py upgrade          # rebuild

DATABASE_URL=$DATABASE_URL python3 db/seeds/load_fixtures.py

ENG02_ADMIN_DATABASE_URL=$DATABASE_URL pytest tests/db -v
```

`DATABASE_URL` for `migrate.py` must be an admin-privileged role (it runs
`CREATE ROLE` / `CREATE EXTENSION` / `ALTER TABLE ... FORCE ROW LEVEL
SECURITY`). It is never the same role the application connects as: every
migration grants the minimum needed privileges to `app_role` (`NOLOGIN`),
and `repository/db.py:connect()` always `SET ROLE app_role` after
authenticating, so the RLS policies created in `migrations/0001` actually
apply (a table owner/superuser bypasses RLS even under `FORCE ROW LEVEL
SECURITY`; tenant-isolation evidence is only meaningful through `app_role`).

`tests/db/conftest.py` runs `migrate.py upgrade` once per test session
against `ENG02_ADMIN_DATABASE_URL` (falls back to `DATABASE_URL`), then
creates a throwaway `LOGIN` role granted `app_role` for the tests to connect
as. Point it at an empty, disposable database — the suite creates tenants,
cases, works and payments but never cleans them up between tests (each test
uses fresh UUIDs, so this is safe but not idempotent against a shared DB you
care about).

## 本機無法執行的部分

This repository's current sandbox VM has **no outbound network** (so
`psycopg`/`pytest` from `requirements.txt` cannot be installed) and **no
local Postgres server** (`pg_ctl`/`postgres` are not on `PATH`, and this VM
is additionally restricted from starting Docker Compose infrastructure for
product development). Concretely, in this environment:

- `python3 db/migrate.py upgrade|downgrade|status` cannot run (no `psycopg`).
- `pytest tests/db` cannot run (same reason, plus no database to point at).
- The empty-db upgrade / rebuild / rollback acceptance
  (`docs/collaboration/backlog.md#eng-02`: "空庫升級、重建與規定的回復程序實跑")
  and every concurrency/isolation acceptance case below it cannot be
  observed locally.

What *was* verified locally, statically, without a database:

- `python3 -m py_compile db/migrate.py db/seeds/load_fixtures.py
  db/repository/*.py` — no syntax errors.
- Manual cross-reference of every migration's columns/constraints against
  `specs/domain/*.schema.json` and the relevant `docs/sd/*.md` section (see
  the comment at the top of each migration file and each `migrations/*.md`).
- `specs/domain/error-codes.json` was checked against every `RepositoryError`
  subclass in `repository/errors.py`; `IMMUTABLE_RECORD` was missing from the
  registry and has been added (ENG-02 is the first task to surface a DB
  append-only violation as an API-facing error code; see the registry's own
  `x_origin.note` about appending new codes here).

**`.github/workflows/repository-validation.yml` runs the real thing**: the
`db-migration-lifecycle` job spins up a Postgres service container and runs
the literal upgrade/downgrade/upgrade sequence above against an empty
database; the `db-repository-tests` job runs `pytest tests/db` against a
second fresh Postgres service container. Until that workflow has run (and a
human/reviewer has read its result) on a given commit, treat the acceptance
criteria above as **not yet demonstrated**, not as passing.
