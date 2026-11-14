"""Human escalation: questions the agent could not answer."""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentUser, ServicesDep
from app.api.schemas import TicketCreate, TicketOut
from app.db.models import Ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_ticket(body: TicketCreate, user: CurrentUser, services: ServicesDep) -> TicketOut:
    async with services.db.tenant_session(user.tenant_id) as session:
        ticket = Ticket(
            tenant_id=user.tenant_id,
            created_by=user.user_id,
            question=body.question,
            note=body.note,
        )
        session.add(ticket)
        await session.flush()
        await session.refresh(ticket)
        return TicketOut.model_validate(ticket)


@router.get("")
async def list_tickets(user: CurrentUser, services: ServicesDep) -> list[TicketOut]:
    """Admins see all tickets of their workspace; members see their own."""
    query = select(Ticket).where(Ticket.tenant_id == user.tenant_id)
    if not user.is_admin:
        query = query.where(Ticket.created_by == user.user_id)
    async with services.db.tenant_session(user.tenant_id) as session:
        tickets = await session.scalars(query.order_by(Ticket.id.desc()).limit(200))
        return [TicketOut.model_validate(t) for t in tickets]
