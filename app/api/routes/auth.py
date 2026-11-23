"""Sign-up (new workspace), invite-based join, login and invites."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser, ServicesDep
from app.api.schemas import (
    InviteOut,
    InviteRequest,
    JoinRequest,
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from app.audit import record
from app.core.config import Settings
from app.core.ratelimit import client_ip, enforce
from app.core.security import (
    TokenClaims,
    create_access_token,
    hash_password,
    new_invite_code,
    new_tenant_suffix,
    verify_password,
)
from app.db.models import Invite, Role, Tenant, User

router = APIRouter(tags=["auth"])

# Compared against when the username does not exist, so response time doesn't reveal it.
_DUMMY_HASH = hash_password("timing-equalizer")


def _issue(settings: Settings, user: User) -> TokenResponse:
    token = create_access_token(settings, TokenClaims(user.id, user.tenant_id, user.role))
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return slug or "workspace"


async def _ensure_identity_free(session: AsyncSession, username: str, email: str) -> None:
    taken = await session.scalar(
        select(User.id).where(or_(User.username == username, User.email == email))
    )
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already registered")


@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, request: Request, services: ServicesDep) -> TokenResponse:
    """Create a new workspace (tenant). The caller becomes its first admin."""
    if not services.settings.allow_public_signup:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Public sign-up is disabled")
    try:
        async with services.db.session() as session:
            await _ensure_identity_free(session, body.username, body.email)
            tenant = Tenant(
                id=f"{_slugify(body.workspace_name)}-{new_tenant_suffix()}",
                name=body.workspace_name,
            )
            session.add(tenant)
            user = User(
                tenant_id=tenant.id,
                username=body.username,
                email=body.email,
                hashed_password=hash_password(body.password),
                role=Role.ADMIN,
            )
            session.add(user)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Username or email already registered"
        ) from exc
    await record(
        services.db,
        tenant_id=user.tenant_id,
        action="workspace.created",
        request=request,
        actor_id=user.id,
        target_type="tenant",
        target_id=user.tenant_id,
    )
    return _issue(services.settings, user)


@router.post("/auth/join", status_code=status.HTTP_201_CREATED)
async def join(body: JoinRequest, request: Request, services: ServicesDep) -> TokenResponse:
    """Join an existing workspace with a single-use invite code. Role comes from the invite."""
    try:
        async with services.db.session() as session:
            invite = await session.scalar(
                select(Invite).where(Invite.code == body.invite_code).with_for_update()
            )
            now = datetime.now(UTC)
            if invite is None or invite.used_by is not None or _aware(invite.expires_at) < now:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired invite")
            await _ensure_identity_free(session, body.username, body.email)
            user = User(
                tenant_id=invite.tenant_id,
                username=body.username,
                email=body.email,
                hashed_password=hash_password(body.password),
                role=invite.role,
            )
            session.add(user)
            await session.flush()
            invite.used_by = user.id
            invite_id = invite.id
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Username or email already registered"
        ) from exc
    await record(
        services.db,
        tenant_id=user.tenant_id,
        action="member.joined",
        request=request,
        actor_id=user.id,
        target_type="invite",
        target_id=invite_id,
        detail={"role": user.role},
    )
    return _issue(services.settings, user)


@router.post("/auth/login", responses={429: {"description": "Too many login attempts"}})
async def login(body: LoginRequest, request: Request, services: ServicesDep) -> TokenResponse:
    # Per IP + username: slows password guessing without letting one client lock out a victim
    # from every network.
    await enforce(
        request,
        f"login:{client_ip(request)}:{body.username.lower()}",
        services.settings.login_rate_per_minute,
    )
    async with services.db.session() as session:
        user = await session.scalar(select(User).where(User.username == body.username))
    valid = verify_password(body.password, user.hashed_password if user else _DUMMY_HASH)
    if user is None or not valid or not user.is_active:
        if user is not None:  # unknown usernames have no workspace to log into
            await record(
                services.db,
                tenant_id=user.tenant_id,
                action="auth.login_failed",
                request=request,
                actor_id=user.id,
                detail={"reason": "inactive" if valid else "bad_password"},
            )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")
    await record(
        services.db,
        tenant_id=user.tenant_id,
        action="auth.login",
        request=request,
        actor_id=user.id,
    )
    return _issue(services.settings, user)


@router.get("/auth/me")
async def me(principal: CurrentUser, services: ServicesDep) -> UserOut:
    async with services.db.session() as session:
        user = await session.get(User, principal.user_id)
    return UserOut.model_validate(user)


@router.post("/invites", status_code=status.HTTP_201_CREATED, tags=["admin"])
async def create_invite(
    body: InviteRequest, request: Request, admin: AdminUser, services: ServicesDep
) -> InviteOut:
    """Create a single-use invite into the admin's own workspace."""
    expires = datetime.now(UTC) + timedelta(hours=services.settings.invite_ttl_hours)
    invite = Invite(
        tenant_id=admin.tenant_id,
        code=new_invite_code(),
        role=body.role,
        created_by=admin.user_id,
        expires_at=expires,
    )
    async with services.db.session() as session:
        session.add(invite)
        await session.flush()
        invite_id = invite.id
    await record(  # never log the code itself: it is a credential until redeemed
        services.db,
        tenant_id=admin.tenant_id,
        action="invite.created",
        request=request,
        actor_id=admin.user_id,
        target_type="invite",
        target_id=invite_id,
        detail={"role": invite.role},
    )
    return InviteOut(code=invite.code, role=Role(invite.role), expires_at=expires)


def _aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
