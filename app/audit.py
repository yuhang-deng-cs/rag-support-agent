"""Audit log writer.

Events are written inside a tenant-scoped session, so on PostgreSQL the RLS INSERT policy checks
that the event belongs to the tenant pinned for the transaction. Where the action already runs in
one (uploads, deletions, tickets) the event commits atomically with it.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import client_ip
from app.db.models import AuditEvent
from app.db.session import Database


def add_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    action: str,
    request: Request | None = None,
    actor_id: int | None = None,
    target_type: str | None = None,
    target_id: int | str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Add an event to an open tenant session (committed with the caller's transaction)."""
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=None if target_id is None else str(target_id),
            detail=detail or {},
            ip=client_ip(request) if request is not None else None,
            request_id=getattr(request.state, "request_id", None) if request is not None else None,
        )
    )


async def record(db: Database, *, tenant_id: str, action: str, **fields: Any) -> None:
    """Write an event in its own tenant-scoped transaction."""
    async with db.tenant_session(tenant_id) as session:
        add_event(session, tenant_id=tenant_id, action=action, **fields)
