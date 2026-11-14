"""Question answering: retrieve -> guardrail -> prune -> generate, as a stream of events."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.db.session import Database
from app.rag import retrieval
from app.rag.embeddings import Embedder
from app.rag.llm import AnswerGenerator
from app.rag.pruning import prune_passages

logger = logging.getLogger(__name__)

NO_ANSWER = (
    "I couldn't find this in your organisation's knowledge base. "
    "You can escalate the question to a human agent."
)


@dataclass(frozen=True, slots=True)
class Event:
    name: str  # "sources" | "context" | "token" | "done" | "error"
    data: dict[str, Any]


class RagPipeline:
    def __init__(
        self, db: Database, embedder: Embedder, generator: AnswerGenerator, settings: Settings
    ) -> None:
        self._db = db
        self._embedder = embedder
        self._generator = generator
        self._settings = settings

    async def retrieve(self, tenant_id: str, question: str) -> list[retrieval.RetrievedChunk]:
        vector = await self._embedder.embed_query(question)
        async with self._db.tenant_session(tenant_id) as session:
            hits = await retrieval.search(session, vector, self._settings.retrieval_top_k)
        return [h for h in hits if h.score >= self._settings.retrieval_min_score]

    async def answer(self, tenant_id: str, question: str) -> AsyncIterator[Event]:
        try:
            async for event in self._answer(tenant_id, question):
                yield event
        except Exception:
            logger.exception("answer generation failed")
            yield Event("error", {"message": "The assistant failed to generate an answer."})

    async def _answer(self, tenant_id: str, question: str) -> AsyncIterator[Event]:
        sources = await self.retrieve(tenant_id, question)
        yield Event(
            "sources",
            {
                "sources": [
                    {
                        "id": i,
                        "document_id": s.document_id,
                        "filename": s.filename,
                        "heading": s.heading,
                        "chunk_index": s.chunk_index,
                        "score": s.score,
                        "snippet": s.text[:280],
                    }
                    for i, s in enumerate(sources, start=1)
                ]
            },
        )

        # Guardrail: with no sufficiently similar evidence, abstain instead of letting the
        # model improvise an answer.
        if not sources:
            yield Event("token", {"text": NO_ANSWER})
            yield Event("done", {"answerable": False})
            return

        if self._settings.context_pruning:
            pruned, stats = prune_passages(question, [s.text for s in sources])
            sources = [dataclasses.replace(s, text=t) for s, t in zip(sources, pruned, strict=True)]
            yield Event(
                "context",
                {
                    "original_tokens": stats.original_tokens,
                    "pruned_tokens": stats.pruned_tokens,
                    "saved_ratio": round(stats.saved_ratio, 3),
                },
            )

        async for text in self._generator.stream(question, sources):
            yield Event("token", {"text": text})
        yield Event("done", {"answerable": True, "generator": self._generator.name})
