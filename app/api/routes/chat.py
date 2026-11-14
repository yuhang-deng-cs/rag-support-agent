"""Streaming question answering over Server-Sent Events."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, ServicesDep
from app.api.schemas import ChatRequest
from app.rag.pipeline import Event

router = APIRouter(tags=["chat"])


def format_sse(event: Event) -> str:
    return f"event: {event.name}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat_stream(body: ChatRequest, user: CurrentUser, services: ServicesDep):
    """Answer a question from the caller's own knowledge base.

    Emits SSE events: `sources` -> `context` (pruning stats) -> `token`* -> `done`
    (or `error`). The tenant is taken from the access token only.
    """

    async def events() -> AsyncIterator[str]:
        async for event in services.pipeline.answer(user.tenant_id, body.question):
            yield format_sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
