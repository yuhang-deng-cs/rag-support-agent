"""Grow one workspace's index for load testing: N synthetic chunks with random unit vectors.

    python scripts/seed_bulk.py --tenant acme --chunks 20000

The vectors are random, so they are (almost) never similar enough to a real question to be used
in an answer - they only make the vector index search a realistically sized table.
"""

from __future__ import annotations

import argparse
import asyncio
import time

import numpy as np

from app.core.config import get_settings
from app.db.models import Document, DocumentChunk, DocumentStatus
from app.db.session import Database

BATCH = 1000


async def main(tenant_id: str, chunks: int) -> None:
    settings = get_settings()
    db = Database(settings.database_url)
    await db.create_schema()
    rng = np.random.default_rng(42)
    started = time.perf_counter()

    async with db.tenant_session(tenant_id) as session:
        doc = Document(
            tenant_id=tenant_id,
            filename="synthetic-load-test-corpus.txt",
            content_type="text/plain",
            source_text="(synthetic corpus for load testing)",
            status=DocumentStatus.READY,
            chunk_count=chunks,
        )
        session.add(doc)
        await session.flush()
        document_id = doc.id

    for start in range(0, chunks, BATCH):
        count = min(BATCH, chunks - start)
        vectors = rng.standard_normal((count, settings.embedding_dim)).astype(np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        async with db.tenant_session(tenant_id) as session:
            session.add_all(
                DocumentChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=start + i,
                    content=f"Synthetic passage {start + i} for load testing.",
                    meta={},
                    embedding=vector.tolist(),
                )
                for i, vector in enumerate(vectors)
            )

    await db.dispose()
    print(f"Inserted {chunks} chunks into '{tenant_id}' in {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", default="acme")
    parser.add_argument("--chunks", type=int, default=20_000)
    args = parser.parse_args()
    asyncio.run(main(args.tenant, args.chunks))
