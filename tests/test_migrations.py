"""Alembic migrations: they build the same schema as the models, and run both ways."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.db.migrate import alembic_config, upgrade_to_head
from app.db.models import Base
from app.db.session import Database


def run_sync(database_url: str, fn: Callable[[Connection], Any]) -> Any:
    async def go() -> Any:
        db = Database(database_url, null_pool=True)
        try:
            async with db.engine.begin() as conn:
                return await conn.run_sync(fn)
        finally:
            await db.dispose()

    return asyncio.run(go())


def test_migrations_match_the_models(database_url):
    """Fails when a model changes without a migration (run `alembic revision --autogenerate`)."""

    def diff(conn: Connection) -> list:
        upgrade_to_head(conn)

        def include(obj, name, type_, reflected, compare_to) -> bool:
            # the HNSW index only exists on PostgreSQL (ddl_if on the model)
            return not (
                type_ == "index"
                and name == "ix_chunks_embedding_hnsw"
                and conn.dialect.name != "postgresql"
            )

        ctx = MigrationContext.configure(
            conn, opts={"include_object": include, "compare_type": False}
        )
        return compare_metadata(ctx, Base.metadata)

    assert run_sync(database_url, diff) == []


def test_downgrade_to_base_and_upgrade_again(database_url):
    def cycle(conn: Connection) -> tuple[set[str], set[str]]:
        upgrade_to_head(conn)
        command.downgrade(alembic_config(conn), "base")
        after_down = set(inspect(conn).get_table_names()) - {"alembic_version"}
        command.upgrade(alembic_config(conn), "head")
        return after_down, set(inspect(conn).get_table_names())

    after_down, after_up = run_sync(database_url, cycle)
    assert after_down == set()
    assert {"tenants", "documents", "document_chunks", "audit_events"} <= after_up


def test_database_created_before_migrations_is_adopted(tmp_path):
    """Tables but no alembic_version: stamped at the baseline, then only newer revisions run."""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'legacy.db').as_posix()}"

    def legacy_then_upgrade(conn: Connection) -> tuple[str, bool]:
        old_tables = [t for name, t in Base.metadata.tables.items() if name != "audit_events"]
        Base.metadata.create_all(conn, tables=old_tables)
        upgrade_to_head(conn)
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        return version, "audit_events" in inspect(conn).get_table_names()

    assert run_sync(url, legacy_then_upgrade) == ("0002", True)


@pytest.mark.parametrize("revision", ["0001", "0002"])
def test_each_revision_is_reachable(tmp_path, revision):
    url = f"sqlite+aiosqlite:///{(tmp_path / f'r{revision}.db').as_posix()}"

    def upgrade_to(conn: Connection) -> str:
        command.upgrade(alembic_config(conn), revision)
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert run_sync(url, upgrade_to) == revision
