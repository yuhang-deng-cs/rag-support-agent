"""Alembic environment.

* From the app/tests: `upgrade_to_head()` passes an open connection in `config.attributes`.
* From the CLI: `alembic upgrade head` connects with DATABASE_URL (async drivers supported).
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Base

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    from app.core.config import get_settings
    from app.db.session import normalize_database_url

    return normalize_database_url(
        config.get_main_option("sqlalchemy.url") or get_settings().database_url
    )


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite needs table rebuilds to ALTER
        compare_type=True,
    )


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_on(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(_run_on)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif (shared := config.attributes.get("connection")) is not None:
    _run_on(shared)
else:
    asyncio.run(_run_async())
