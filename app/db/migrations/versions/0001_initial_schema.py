"""Initial schema: tenants, users, invites, documents, chunks (pgvector) and tickets, with RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.core.config import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

RLS_TABLES = ("documents", "document_chunks", "tickets")
PREDICATE = "tenant_id = current_setting('app.tenant_id', true)"


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tenants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        _created_at(),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        _created_at(),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "used_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        _created_at(),
    )
    op.create_index("ix_invites_tenant_id", "invites", ["tenant_id"])
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("source_text", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=False),
        sa.Column(
            "uploaded_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        _created_at(),
        # Target of the composite FK from document_chunks.
        sa.UniqueConstraint("id", "tenant_id", name="uq_documents_id_tenant"),
    )
    op.create_index("ix_documents_tenant_created", "documents", ["tenant_id", "created_at"])
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.Integer, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("meta", sa.JSON, nullable=False),
        sa.Column("embedding", Vector(get_settings().embedding_dim), nullable=False),
        # A chunk can only reference a document of the *same* tenant.
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["documents.id", "documents.tenant_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_chunks_tenant_document", "document_chunks", ["tenant_id", "document_id"])
    if postgres:
        op.create_index(
            "ix_chunks_embedding_hnsw",
            "document_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        _created_at(),
    )
    op.create_index("ix_tickets_tenant_status", "tickets", ["tenant_id", "status"])

    if postgres:
        for table in RLS_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} "
                f"USING ({PREDICATE}) WITH CHECK ({PREDICATE})"
            )


def downgrade() -> None:
    for table in ("tickets", "document_chunks", "documents", "invites", "users", "tenants"):
        op.drop_table(table)
