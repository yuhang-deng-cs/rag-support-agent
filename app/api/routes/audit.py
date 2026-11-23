"""Workspace audit log (admins only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from app.api.deps import AdminUser, ServicesDep
from app.api.schemas import AuditEventOut
from app.db.models import AuditEvent, User

router = APIRouter(tags=["admin"])


@router.get("/audit")
async def list_audit_events(
    admin: AdminUser,
    services: ServicesDep,
    response: Response,
    action: Annotated[
        str | None, Query(max_length=64, description="e.g. auth.login_failed")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEventOut]:
    """Newest first; the total is returned in `X-Total-Count`."""
    query = select(AuditEvent).where(AuditEvent.tenant_id == admin.tenant_id)
    if action:
        query = query.where(AuditEvent.action == action)
    async with services.db.tenant_session(admin.tenant_id) as session:
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await session.execute(
            query.add_columns(User.username)
            .outerjoin(User, User.id == AuditEvent.actor_id)
            .order_by(AuditEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        response.headers["X-Total-Count"] = str(total or 0)
        return [
            AuditEventOut.model_validate(event).model_copy(update={"actor_username": username})
            for event, username in rows
        ]
