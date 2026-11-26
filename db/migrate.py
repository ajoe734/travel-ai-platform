#!/usr/bin/env python3
"""ENG-02 migration runner.

Deliberately dependency-light (no Alembic/Django): a numbered pair of
``NNNN_name.up.sql`` / ``NNNN_name.down.sql`` files per migrations/ entry,
tracked in a ``schema_migrations`` table. Each ``.sql`` file owns its own
``BEGIN``/``COMMIT`` so this runner connects with autocommit=True and never
nests transactions around a script.

Usage:
    python3 db/migrate.py upgrade [--to 0003]
    python3 db/migrate.py downgrade --to 0001
    python3 db/migrate.py downgrade --to 0        # full teardown
    python3 db/migrate.py status

DATABASE_URL (or --database-url) must point at an admin role that can
CREATE ROLE/CREATE EXTENSION/ALTER TABLE ... FORCE ROW LEVEL SECURITY; this
is never the same role the application (app_role) connects as.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys

import psycopg

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent / "migrations"
VERSION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.(up|down)\.sql$")


class Migration:
    def __init__(self, version: str, name: str, up_path: pathlib.Path, down_path: pathlib.Path):
        self.version = version
        self.name = name
        self.up_path = up_path
        self.down_path = down_path

    def __repr__(self) -> str:
        return f"{self.version}_{self.name}"


def discover_migrations() -> list[Migration]:
    found: dict[str, dict[str, pathlib.Path]] = {}
    for path in MIGRATIONS_DIR.glob("*.sql"):
        m = VERSION_RE.match(path.name)
        if not m:
            raise SystemExit(f"Migration file does not match NNNN_name.(up|down).sql: {path.name}")
        version, name, direction = m.groups()
        found.setdefault(version, {"name": name})[direction] = path
        if found[version]["name"] != name:
            raise SystemExit(f"version {version} has mismatched names across up/down files")
    migrations = []
    for version in sorted(found):
        entry = found[version]
        if "up" not in entry or "down" not in entry:
            raise SystemExit(f"version {version} is missing its up or down file")
        migrations.append(Migration(version, entry["name"], entry["up"], entry["down"]))
    return migrations


def ensure_tracking_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     text PRIMARY KEY,
            name        text NOT NULL,
            applied_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def applied_versions(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def upgrade(conn: psycopg.Connection, migrations: list[Migration], to: str | None) -> list[str]:
    ensure_tracking_table(conn)
    done = applied_versions(conn)
    ran = []
    for migration in migrations:
        if to is not None and migration.version > to:
            break
        if migration.version in done:
            continue
        sql = migration.up_path.read_text()
        conn.execute(sql)
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
            (migration.version, migration.name),
        )
        ran.append(migration.version)
    return ran


def downgrade(conn: psycopg.Connection, migrations: list[Migration], to: str) -> list[str]:
    ensure_tracking_table(conn)
    done = applied_versions(conn)
    ran = []
    for migration in reversed(migrations):
        if migration.version <= to:
            break
        if migration.version not in done:
            continue
        sql = migration.down_path.read_text()
        conn.execute(sql)
        conn.execute("DELETE FROM schema_migrations WHERE version = %s", (migration.version,))
        ran.append(migration.version)
    return ran


def status(conn: psycopg.Connection, migrations: list[Migration]) -> None:
    ensure_tracking_table(conn)
    done = applied_versions(conn)
    for migration in migrations:
        marker = "applied" if migration.version in done else "pending"
        print(f"{migration.version}_{migration.name}: {marker}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    sub = parser.add_subparsers(dest="command", required=True)

    up_parser = sub.add_parser("upgrade")
    up_parser.add_argument("--to", default=None, help="Stop after this version (inclusive).")

    down_parser = sub.add_parser("downgrade")
    down_parser.add_argument("--to", required=True, help="Target version to downgrade to (exclusive), or 0 for a full teardown.")

    sub.add_parser("status")

    args = parser.parse_args()

    if not args.database_url:
        print("DATABASE_URL is not set and --database-url was not given.", file=sys.stderr)
        return 2

    migrations = discover_migrations()

    with psycopg.connect(args.database_url, autocommit=True) as conn:
        if args.command == "upgrade":
            ran = upgrade(conn, migrations, args.to)
            print(f"Applied: {ran}" if ran else "Already up to date.")
        elif args.command == "downgrade":
            to = "0000" if args.to == "0" else args.to
            ran = downgrade(conn, migrations, to)
            print(f"Rolled back: {ran}" if ran else "Nothing to roll back.")
        elif args.command == "status":
            status(conn, migrations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
