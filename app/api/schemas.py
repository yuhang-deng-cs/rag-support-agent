"""Request/response models.

Request models use `extra="forbid"`: a client that tries to smuggle a `tenant_id` or `role`
into a request gets a 422 instead of having the field silently ignored. The tenant is always
taken from the verified access token, never from the request body.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.db.models import Role

Username = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64, pattern=r"^[\w.-]+$")
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Auth -------------------------------------------------------------------


class SignupRequest(StrictModel):
    workspace_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)
    ]
    username: Username
    email: EmailStr
    password: Password


class JoinRequest(StrictModel):
    invite_code: Annotated[str, StringConstraints(min_length=8, max_length=64)]
    username: Username
    email: EmailStr
    password: Password


class LoginRequest(StrictModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: Role
    tenant_id: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - not a secret
    user: UserOut


class InviteRequest(StrictModel):
    role: Role = Role.MEMBER


class InviteOut(BaseModel):
    code: str
    role: Role
    expires_at: datetime


# --- Documents --------------------------------------------------------------


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime


# --- Chat -------------------------------------------------------------------


class ChatRequest(StrictModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]


# --- Tickets ----------------------------------------------------------------


class TicketCreate(StrictModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    note: str | None
    status: str
    created_by: int | None
    created_at: datetime


class HealthOut(BaseModel):
    status: str
    version: str
    database: str
    row_level_security: str
    embedding_provider: str
    llm_provider: str


class ErrorOut(BaseModel):
    detail: str = Field(examples=["Not found"])


# --- Search -----------------------------------------------------------------


class SearchRequest(StrictModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    top_k: Annotated[int, Field(ge=1, le=20)] | None = None


class SearchHit(BaseModel):
    document_id: int
    filename: str
    chunk_index: int
    heading: str | None
    score: float
    above_threshold: bool  # whether /chat/stream would use this chunk (RETRIEVAL_MIN_SCORE)
    snippet: str


class SearchOut(BaseModel):
    results: list[SearchHit]
    embed_ms: float
    search_ms: float


# --- Audit ------------------------------------------------------------------


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    actor_id: int | None
    actor_username: str | None = None
    target_type: str | None
    target_id: str | None
    detail: dict
    ip: str | None
    request_id: str | None
    created_at: datetime
