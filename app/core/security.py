"""Password hashing and JWT helpers."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import Settings

TOKEN_ISSUER = "rag-support-agent"  # noqa: S105 - not a secret


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: int
    tenant_id: str
    role: str


def create_access_token(settings: Settings, claims: TokenClaims) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(claims.user_id),
        "tid": claims.tenant_id,
        "role": claims.role,
        "iss": TOKEN_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(settings: Settings, token: str) -> TokenClaims | None:
    """Return the verified claims, or None for any invalid/expired/tampered token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],  # pinned: rejects "none" and alg confusion
            issuer=TOKEN_ISSUER,
            options={"require": ["sub", "tid", "role", "exp", "iss"]},
        )
        return TokenClaims(
            user_id=int(payload["sub"]), tenant_id=payload["tid"], role=payload["role"]
        )
    except (jwt.PyJWTError, ValueError, TypeError):
        return None


def new_invite_code() -> str:
    return secrets.token_urlsafe(24)


def new_tenant_suffix() -> str:
    return secrets.token_hex(3)
