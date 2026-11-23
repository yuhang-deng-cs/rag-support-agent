"""Retrieval only: the chunks the agent would use, with scores and server-side timings.

Useful for debugging relevance, and it is what the load test measures (see loadtest/).
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentUser, ServicesDep
from app.api.schemas import SearchHit, SearchOut, SearchRequest
from app.core.ratelimit import enforce
from app.rag import retrieval

router = APIRouter(tags=["chat"])


@router.post("/search", responses={429: {"description": "Rate limited"}})
async def search(
    body: SearchRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    services: ServicesDep,
) -> SearchOut:
    await enforce(request, f"search:{user.user_id}", services.settings.search_rate_per_minute)
    started = time.perf_counter()
    vector = await services.embedder.embed_query(body.query)
    embedded = time.perf_counter()
    async with services.db.tenant_session(user.tenant_id) as session:
        hits = await retrieval.search(
            session, vector, body.top_k or services.settings.retrieval_top_k
        )
    done = time.perf_counter()

    embed_ms, search_ms = (embedded - started) * 1000, (done - embedded) * 1000
    response.headers["Server-Timing"] = f"embed;dur={embed_ms:.1f}, db;dur={search_ms:.1f}"
    return SearchOut(
        results=[
            SearchHit(
                document_id=h.document_id,
                filename=h.filename,
                chunk_index=h.chunk_index,
                heading=h.heading,
                score=h.score,
                above_threshold=h.score >= services.settings.retrieval_min_score,
                snippet=h.text[:280],
            )
            for h in hits
        ],
        embed_ms=round(embed_ms, 2),
        search_ms=round(search_ms, 2),
    )
