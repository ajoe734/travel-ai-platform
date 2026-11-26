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

## CI 退修記錄

| Finding | 原始碼依據與修改位置 | 舊版重現 → 修正版結果 | 命令、退出碼、執行版本與證據位置 | 未驗項與具體限制 |
| --- | --- | --- | --- | --- |
| `db-repository-tests` job failing on candidate `ea11aaf90412295ce550b7db9b06738f9619cbc8`, two consecutive PR #7 runs (job `140008868214`, then `140011365899`) | `db/migrate.py:main()` put `--database-url` only on the top-level `argparse.ArgumentParser`; `argparse` subparsers do not inherit a parent's optional flags when the flag follows the subcommand token. `tests/db/conftest.py:60` invokes `migrate.py upgrade --database-url <url>` (subcommand first), which the old parser rejected with `error: unrecognized arguments: --database-url ...`, failing every test at setup (10/10 ERROR). Fixed by adding a shared `argparse.ArgumentParser(add_help=False)` holding `--database-url` and passing it as `parents=[common]` to the top-level parser and to each of the `upgrade`/`downgrade`/`status` subparsers. | Before: `migrate.py upgrade --database-url pg://x` → `SystemExit(2)`, `unrecognized arguments: --database-url pg://x`. After: same invocation parses to `Namespace(database_url='pg://x', command='upgrade', to=None)`. | Local: standalone `argparse` reproduction of both the old and new parser shapes, run directly in this sandbox (no DB/psycopg involved) — exit 0, printed Namespace confirms `database_url` is populated for `upgrade --database-url ...`, `downgrade --to 0 --database-url ...`, and `status --database-url ...`. `python3 -m py_compile db/migrate.py` — exit 0. Hosted: not yet re-run; CI on the new candidate SHA (not yet committed at time of writing) will exercise the real Postgres path via `db-repository-tests` / `db-migration-lifecycle`. | Cannot execute `pytest tests/db` or `db/migrate.py upgrade` against a real Postgres in this sandbox (no network for `psycopg`, no local Postgres, per 本機無法執行的部分 above) — the argparse fix is proven correct in isolation, but the full fixture chain (role creation, RLS, concurrency/idempotency tests) is only demonstrated by the hosted CI job on the next candidate SHA; read that result before approving. |
| `db-repository-tests` job failing on candidate `a1194d8690223cd51c640f1fcc1cb97d4506aead`, both PR #7 runs (job `140016083240` and `140016111191`), all 10 tests error at setup with `psycopg.errors.IndeterminateDatatype: could not determine data type of parameter $1` | `tests/db/conftest.py:_migrated_schema` (old line 64-75) ran `conn.execute("DO $$ ... CREATE ROLE eng02_test_app_user LOGIN PASSWORD %(password)s; ... $$;", {"password": _APP_USER_PASSWORD})`. Postgres parses the whole `DO $$ ... $$` body as one dollar-quoted string literal *before* handing it to the PL/pgSQL interpreter; a psycopg server-side bind placeholder (`%(password)s` → `$1`) that lands inside that literal is never referenced in an actual typed SQL position at the top-level parse, so Postgres cannot infer `$1`'s type and rejects the whole statement — independent of the role-already-exists guard, so every test that depends on the session-scoped `_migrated_schema` fixture errors at setup. Fixed by composing the password as a client-side-escaped literal with `psycopg.sql.SQL(...).format(password=sql.Literal(_APP_USER_PASSWORD))` instead of a server-side bind parameter, so no `$1` is ever sent to Postgres. | Before: the fixture's `conn.execute(...)` call raises `psycopg.errors.IndeterminateDatatype: could not determine data type of parameter $1` for every one of the 10 acceptance tests (see CI log, job `140016111191`). After: `sql.SQL(...).format(...)` renders the password as an inline quoted literal (e.g. `PASSWORD 'eng02-test-fixture-only'`), identical in effect to the original intent but with no bind-parameter position inside the dollar-quoted body. | Local: `python3 -m py_compile tests/db/conftest.py` — exit 0. `python3 scripts/validate_repository.py` — exit 0 (`Repository checks: passed`). Read CI logs for job `140016111191` (`gh run view 45850739091 --log-failed`) to confirm the exact failure signature before this fix. Hosted: not yet re-run; the next CI run on the new candidate SHA will exercise the real `db-repository-tests` job. | `psycopg` is not installed in this sandbox (no outbound network), so `sql.SQL(...).format(...)` could not be executed or round-tripped against a live connection locally — the fix is derived from Postgres's documented dollar-quoting/parameter-binding semantics and the exact error signature in the CI log, not from a local repro of the passing case. The hosted `db-repository-tests` job on the next candidate SHA is the first actual execution of this code path; read its result before approving. |
