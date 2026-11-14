"""Row-Level Security: the database itself refuses cross-tenant access.

These tests deliberately bypass the application's `WHERE tenant_id = ...` filters with raw SQL,
to prove that isolation still holds if application code has a bug.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.conftest import ACME_BILLING, UMBRA_SECRET, signup, upload

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres_client(client, settings):
    if settings.is_sqlite:
        pytest.skip("RLS is PostgreSQL-only")
    return client


@pytest.fixture
def seeded(postgres_client):
    client = postgres_client
    acme, umbra = signup(client, "Acme"), signup(client, "Umbra")
    upload(client, acme, "billing.md", ACME_BILLING)
    umbra_doc = upload(client, umbra, "incident.md", UMBRA_SECRET)
    return client, client.app.state.services.db, acme, umbra, umbra_doc


def test_rls_is_reported_as_enforced(postgres_client):
    health = postgres_client.get("/api/v1/health").json()
    assert health["row_level_security"] == "enforced"


@pytest.mark.parametrize("table", ["documents", "document_chunks", "tickets"])
def test_unfiltered_select_only_sees_own_tenant(seeded, table):
    client, db, acme, umbra, _ = seeded
    client.post("/api/v1/tickets", json={"question": "q"}, headers=umbra.headers)

    async def tenants_visible_to(tenant_id: str) -> set[str]:
        async with db.tenant_session(tenant_id) as session:
            rows = await session.execute(text(f"SELECT tenant_id FROM {table}"))  # noqa: S608
            return {r[0] for r in rows}

    assert client.portal.call(tenants_visible_to, acme.tenant_id) <= {acme.tenant_id}
    assert umbra.tenant_id in client.portal.call(tenants_visible_to, umbra.tenant_id)


def test_no_tenant_context_means_no_rows(seeded):
    """Fail closed: a session that never set app.tenant_id sees nothing."""
    client, db, *_ = seeded

    async def count() -> int:
        async with db.session() as session:
            return (
                await session.execute(text("SELECT count(*) FROM document_chunks"))
            ).scalar_one()

    assert client.portal.call(count) == 0


def test_cannot_write_rows_for_another_tenant(seeded):
    client, db, acme, umbra, _ = seeded

    async def insert_foreign_ticket() -> None:
        async with db.tenant_session(acme.tenant_id) as session:
            await session.execute(
                text("INSERT INTO tickets (tenant_id, question, status) VALUES (:t, 'x', 'open')"),
                {"t": umbra.tenant_id},
            )

    with pytest.raises(DBAPIError, match="row-level security"):
        client.portal.call(insert_foreign_ticket)


def test_cannot_update_another_tenants_rows(seeded):
    client, db, acme, _, umbra_doc = seeded

    async def hijack() -> int:
        async with db.tenant_session(acme.tenant_id) as session:
            result = await session.execute(
                text("UPDATE documents SET filename = 'pwned' WHERE id = :id"),
                {"id": umbra_doc["id"]},
            )
            return result.rowcount

    assert client.portal.call(hijack) == 0
