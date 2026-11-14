"""Optional Celery worker for ingestion (INGESTION_BACKEND=celery).

Run with:  celery -A app.ingestion.celery_app worker --loglevel=info
"""

from __future__ import annotations

import asyncio

from celery import Celery

from app.core.config import get_settings
from app.db.session import Database
from app.ingestion.service import ingest_document
from app.rag.embeddings import build_embedder

settings = get_settings()
celery_app = Celery("rag_support_agent", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1)

_embedder = None


def _get_embedder():
    global _embedder  # loaded once per worker process (model load is expensive)
    if _embedder is None:
        _embedder = build_embedder(settings)
    return _embedder


async def _run(tenant_id: str, document_id: int) -> int:
    # Each task gets its own event loop, so use a fresh NullPool engine bound to it.
    db = Database(settings.database_url, null_pool=True)
    try:
        return await ingest_document(db, _get_embedder(), settings, tenant_id, document_id)
    finally:
        await db.dispose()


@celery_app.task(name="ingest_document", autoretry_for=(ConnectionError,), max_retries=3)
def ingest_document_task(tenant_id: str, document_id: int) -> int:
    return asyncio.run(_run(tenant_id, document_id))
