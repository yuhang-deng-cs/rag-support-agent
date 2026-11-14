"""Database engine and session management."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import Base
from app.db.rls import TENANT_SETTING, RlsStatus, apply_rls_policies, rls_status

logger = logging.getLogger(__name__)


def normalize_database_url(url: str) -> str:
    """Accept plain `postgresql://` URLs and use the asyncpg driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


class Database:
    def __init__(self, url: str, *, null_pool: bool = False) -> None:
        kwargs = {"poolclass": NullPool} if null_pool else {}
        self.engine = create_async_engine(normalize_database_url(url), **kwargs)
        self._sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.rls: RlsStatus = "unsupported"

    @property
    def is_postgres(self) -> bool:
        return self.engine.dialect.name == "postgresql"

    async def create_schema(self) -> None:
        async with self.engine.begin() as conn:
            if self.is_postgres:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
            if self.is_postgres:
                await apply_rls_policies(conn)
            self.rls = await rls_status(conn)

        if self.rls == "bypassed":
            logger.warning(
                "Connected as a superuser/BYPASSRLS role: Row-Level Security is NOT enforced. "
                "Connect as an ordinary role (see infra/postgres/init.sql)."
            )
        elif self.rls == "unsupported":
            logger.info("SQLite backend: tenant isolation is enforced by the application only.")

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Unscoped session for identity tables (tenants, users, invites). Commits on exit."""
        async with self._sessionmaker() as session, session.begin():
            yield session

    @asynccontextmanager
    async def tenant_session(self, tenant_id: str) -> AsyncIterator[AsyncSession]:
        """Session bound to one tenant for its whole transaction. Commits on exit.

        On PostgreSQL the tenant is pinned with a transaction-local setting that the RLS
        policies check, so rows of other tenants are invisible at the database level.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")
        async with self._sessionmaker() as session, session.begin():
            if self.is_postgres:
                await session.execute(
                    text("SELECT set_config(:key, :tenant, true)"),
                    {"key": TENANT_SETTING, "tenant": tenant_id},
                )
            session.info["tenant_id"] = tenant_id
            yield session
