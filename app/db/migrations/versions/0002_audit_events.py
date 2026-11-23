"""Audit log: append-only, tenant-isolated record of security-relevant actions.

On PostgreSQL the table gets two RLS policies - SELECT and INSERT for the current tenant - and no
UPDATE or DELETE policy, so with FORCE ROW LEVEL SECURITY the application role can add events but
never rewrite or erase them.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PREDICATE = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_tenant_created", "audit_events", ["tenant_id", "created_at"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY audit_read ON audit_events FOR SELECT USING ({PREDICATE})")
        op.execute(
            f"CREATE POLICY audit_append ON audit_events FOR INSERT WITH CHECK ({PREDICATE})"
        )


def downgrade() -> None:
    op.drop_table("audit_events")
