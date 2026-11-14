"""Idempotent demo data: two workspaces with separate knowledge bases.

Enabled with SEED_DEMO=true (refused in production). Accounts:

    acme-admin / acme-member   ->  Acme Cloud  (SaaS product docs)
    umbra-admin                ->  Umbra Health (clinic software + an internal postmortem)

All demo accounts use the password `demo-password`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from app.api.deps import Services
from app.core.security import hash_password
from app.db.models import Document, Role, Tenant, User
from app.ingestion.service import ingest_document

logger = logging.getLogger(__name__)

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_docs"
DEMO_PASSWORD = "demo-password"  # noqa: S105 - public demo credential

DEMO_TENANTS = {
    "acme": ("Acme Cloud", [("acme-admin", Role.ADMIN), ("acme-member", Role.MEMBER)]),
    "umbra": ("Umbra Health", [("umbra-admin", Role.ADMIN)]),
}


async def seed_demo(services: Services) -> None:
    db = services.db
    async with db.session() as session:
        if await session.get(Tenant, "acme") is not None:
            return
        password = hash_password(DEMO_PASSWORD)
        for tenant_id, (name, users) in DEMO_TENANTS.items():
            session.add(Tenant(id=tenant_id, name=name))
            for username, role in users:
                session.add(
                    User(
                        tenant_id=tenant_id,
                        username=username,
                        email=f"{username}@example.com",
                        hashed_password=password,
                        role=role,
                    )
                )

    for tenant_id in DEMO_TENANTS:
        for path in sorted((SAMPLE_DIR / tenant_id).glob("*.md")):
            async with db.tenant_session(tenant_id) as session:
                doc = Document(
                    tenant_id=tenant_id,
                    filename=path.name,
                    content_type="text/markdown",
                    source_text=path.read_text(encoding="utf-8"),
                )
                session.add(doc)
                await session.flush()
                doc_id = doc.id
            await ingest_document(db, services.embedder, services.settings, tenant_id, doc_id)

    async with db.session() as session:
        count = len((await session.scalars(select(User.id))).all())
    logger.info("Seeded demo workspaces 'acme' and 'umbra' (%d users)", count)
