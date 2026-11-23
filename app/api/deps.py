"""FastAPI dependencies: service container and authentication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.ratelimit import Limiter
from app.core.security import decode_access_token
from app.db.models import Role, User
from app.db.session import Database
from app.rag.embeddings import Embedder
from app.rag.pipeline import RagPipeline


@dataclass(frozen=True, slots=True)
class Services:
    settings: Settings
    db: Database
    embedder: Embedder
    pipeline: RagPipeline
    limiter: Limiter


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. `tenant_id` comes from the database, never from the client."""

    user_id: int
    username: str
    tenant_id: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]

_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_principal(
    services: ServicesDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None:
        raise _UNAUTHORIZED
    claims = decode_access_token(services.settings, credentials.credentials)
    if claims is None:
        raise _UNAUTHORIZED
    async with services.db.session() as session:
        user = await session.get(User, claims.user_id)
    # Re-check against the database so deactivated users and stale role/tenant claims fail.
    if user is None or not user.is_active or user.tenant_id != claims.tenant_id:
        raise _UNAUTHORIZED
    return Principal(user.id, user.username, user.tenant_id, Role(user.role))


CurrentUser = Annotated[Principal, Depends(get_principal)]


async def require_admin(principal: CurrentUser) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return principal


AdminUser = Annotated[Principal, Depends(require_admin)]
