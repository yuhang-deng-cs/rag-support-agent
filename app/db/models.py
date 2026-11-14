"""ORM models.

Two kinds of tables:

* **Identity tables** (`tenants`, `users`, `invites`) are global: login and invite redemption
  happen before a tenant is known.
* **Tenant-owned tables** (`documents`, `document_chunks`, `tickets`) carry `tenant_id` and,
  on PostgreSQL, are protected by Row-Level Security policies (see `app/db/rls.py`).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim

TENANT_OWNED_TABLES = ("documents", "document_chunks", "tickets")


class Base(DeclarativeBase):
    pass


class Role(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class TicketStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


def _tenant_fk() -> ForeignKey:
    return ForeignKey("tenants.id", ondelete="CASCADE")


def _user_fk(ondelete: str) -> ForeignKey:
    return ForeignKey("users.id", ondelete=ondelete)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = _now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(_tenant_fk(), index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.MEMBER)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = _now()


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(_tenant_fk(), index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16), default=Role.MEMBER)
    created_by: Mapped[int] = mapped_column(_user_fk("CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(_user_fk("SET NULL"))
    created_at: Mapped[datetime] = _now()


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(_tenant_fk())
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64))
    source_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=DocumentStatus.QUEUED)
    error: Mapped[str | None] = mapped_column(String(500))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[int | None] = mapped_column(_user_fk("SET NULL"))
    created_at: Mapped[datetime] = _now()

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_documents_tenant_created", "tenant_id", "created_at"),
        # Target of the composite FK below.
        UniqueConstraint("id", "tenant_id", name="uq_documents_id_tenant"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        # Composite FK: a chunk can only reference a document of the *same* tenant.
        ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["documents.id", "documents.tenant_id"],
            ondelete="CASCADE",
        ),
        Index("ix_chunks_tenant_document", "tenant_id", "document_id"),
        # Approximate nearest-neighbour index (PostgreSQL only).
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )


class Ticket(Base):
    """A question the agent could not answer, escalated to a human."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(_tenant_fk())
    created_by: Mapped[int | None] = mapped_column(_user_fk("SET NULL"))
    question: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=TicketStatus.OPEN)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_tickets_tenant_status", "tenant_id", "status"),)
