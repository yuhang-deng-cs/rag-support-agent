"""Document ingestion: chunk -> embed -> store, with status tracking on the document row."""

from __future__ import annotations

import logging

from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.models import Document, DocumentChunk, DocumentStatus
from app.db.session import Database
from app.rag.chunking import chunk_text
from app.rag.embeddings import Embedder

logger = logging.getLogger(__name__)


async def _load(session, document_id: int) -> Document:
    # The tenant filter is redundant with RLS on PostgreSQL but required on SQLite.
    doc = await session.scalar(
        select(Document).where(
            Document.id == document_id, Document.tenant_id == session.info["tenant_id"]
        )
    )
    if doc is None:
        raise LookupError(f"document {document_id} not found in tenant")
    return doc


async def ingest_document(
    db: Database, embedder: Embedder, settings: Settings, tenant_id: str, document_id: int
) -> int:
    """Process one queued document. Returns the number of chunks stored."""
    async with db.tenant_session(tenant_id) as session:
        doc = await _load(session, document_id)
        doc.status = DocumentStatus.PROCESSING
        source_text = doc.source_text

    try:
        chunks = chunk_text(source_text, settings.chunk_size, settings.chunk_overlap)
        vectors = await embedder.embed_documents([c.text for c in chunks])
        async with db.tenant_session(tenant_id) as session:
            doc = await _load(session, document_id)
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            session.add_all(
                DocumentChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=c.index,
                    content=c.text,
                    meta={"heading": c.heading} if c.heading else {},
                    embedding=v,
                )
                for c, v in zip(chunks, vectors, strict=True)
            )
            doc.status = DocumentStatus.READY
            doc.chunk_count = len(chunks)
            doc.error = None
    except Exception as exc:
        logger.exception("ingestion failed for document %s", document_id)
        async with db.tenant_session(tenant_id) as session:
            doc = await _load(session, document_id)
            doc.status = DocumentStatus.FAILED
            doc.error = f"{type(exc).__name__}: {exc}"[:500]
        raise
    logger.info("ingested document %s (%d chunks)", document_id, len(chunks))
    return len(chunks)
