"""PostgreSQL Row-Level Security for tenant-owned tables.

Every tenant-scoped transaction runs `set_config('app.tenant_id', <tenant>, true)` first
(see `Database.tenant_session`). The policies below make PostgreSQL itself refuse to read or
write rows of any other tenant - even if application code forgets a `WHERE tenant_id = ...`.

If the setting is missing, `current_setting(..., true)` returns NULL and the policy matches
nothing: the system fails closed.

`FORCE ROW LEVEL SECURITY` applies the policies to the table owner too. Superusers and roles
with BYPASSRLS still bypass RLS, so the app must connect as an ordinary role
(see `infra/postgres/init.sql`). `rls_status()` reports which case applies.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.models import TENANT_OWNED_TABLES

TENANT_SETTING = "app.tenant_id"
POLICY_NAME = "tenant_isolation"

RlsStatus = Literal["enforced", "bypassed", "unsupported"]


def _policy_statements(table: str) -> list[str]:
    predicate = f"tenant_id = current_setting('{TENANT_SETTING}', true)"
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table}",
        f"CREATE POLICY {POLICY_NAME} ON {table} USING ({predicate}) WITH CHECK ({predicate})",
    ]


async def apply_rls_policies(conn: AsyncConnection) -> None:
    for table in TENANT_OWNED_TABLES:
        for statement in _policy_statements(table):
            await conn.execute(text(statement))


async def rls_status(conn: AsyncConnection) -> RlsStatus:
    if conn.dialect.name != "postgresql":
        return "unsupported"
    row = (
        await conn.execute(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
    ).one()
    return "bypassed" if row[0] else "enforced"
