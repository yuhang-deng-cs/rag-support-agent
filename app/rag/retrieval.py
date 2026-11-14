"""Tenant-scoped vector search."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentChunk


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    filename: str
    chunk_index: int
    heading: str | None
    text: str
    score: float


def _session_tenant(session: AsyncSession) -> str:
    tenant_id = session.info.get("tenant_id")
    if not tenant_id:
        raise RuntimeError("search requires a tenant-scoped session (Database.tenant_session)")
    return tenant_id


async def search(
    session: AsyncSession, query_vector: list[float], top_k: int
) -> list[RetrievedChunk]:
    """Return the `top_k` most similar chunks of the session's tenant.

    Isolation is defence-in-depth: the explicit `tenant_id` filter below *and*, on PostgreSQL,
    the RLS policy pinned by `tenant_session` both have to agree.
    """
    tenant_id = _session_tenant(session)
    base = (
        select(DocumentChunk, Document.filename)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(DocumentChunk.tenant_id == tenant_id)
    )

    if session.bind.dialect.name == "postgresql":
        distance = DocumentChunk.embedding.cosine_distance(query_vector)
        rows = (
            await session.execute(base.add_columns(distance).order_by(distance).limit(top_k))
        ).all()
        scored = [(1.0 - float(dist), chunk, filename) for chunk, filename, dist in rows]
    else:
        # SQLite fallback: brute-force cosine similarity in numpy.
        rows = (await session.execute(base)).all()
        if not rows:
            return []
        matrix = np.array([chunk.embedding for chunk, _ in rows], dtype=np.float32)
        query = np.asarray(query_vector, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query) or 1.0)
        sims = matrix @ query / np.where(norms == 0, 1.0, norms)
        order = np.argsort(-sims)[:top_k]
        scored = [(float(sims[i]), rows[i][0], rows[i][1]) for i in order]

    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            chunk_index=chunk.chunk_index,
            heading=(chunk.meta or {}).get("heading"),
            text=chunk.content,
            score=round(score, 4),
        )
        for score, chunk, filename in scored
    ]
