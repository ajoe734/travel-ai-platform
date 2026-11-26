"""Connection and tenant-scoping helpers shared by every repository module.

The application always connects as ``app_role`` (never the migration/admin
role) so the RLS policies created in db/migrations actually apply (see
0001_tenancy_and_core_case.up.sql: a table owner/superuser bypasses RLS even
with FORCE ROW LEVEL SECURITY, so tenant isolation evidence is only
meaningful through this role).
"""
from __future__ import annotations

import contextlib
from typing import Iterator

import psycopg


def connect(database_url: str) -> psycopg.Connection:
    """Open a connection as app_role, matching the runtime posture in production.

    DATABASE_URL must authenticate as a login role that has been granted
    app_role (see tests/db/conftest.py for how the test fixture wires this
    up); app_role itself is NOLOGIN.
    """
    conn = psycopg.connect(database_url, autocommit=False)
    conn.execute("SET ROLE app_role")
    return conn


@contextlib.contextmanager
def tenant_transaction(conn: psycopg.Connection, tenant_id: str) -> Iterator[psycopg.Connection]:
    """Run one transaction with ``app.tenant_id`` pinned for every RLS policy.

    ``SET LOCAL`` is transaction-scoped, matching SD work-execution-contract.md
    §6.2's "short transaction" boundary: tenant is derived once per command
    transaction from a trusted context, never re-derived mid-transaction.
    """
    with conn.transaction():
        # SET LOCAL's grammar does not accept a bind parameter for the value;
        # set_config(..., is_local=true) is the equivalent parameterized form
        # and has the same transaction-local scope.
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
        yield conn
