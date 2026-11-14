"""Extractive context pruning.

Retrieved chunks often contain only one or two sentences that matter. Before calling the LLM
we keep, per chunk, the sentences that share terms with the question (plus their immediate
neighbours for coherence) and drop the rest. This is a cheap, deterministic heuristic - not a
learned compressor - and `scripts/eval.py` measures how much it saves and whether the
answer-bearing text survives.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rag.text import estimate_tokens, split_sentences, terms


@dataclass(frozen=True, slots=True)
class PruneStats:
    original_tokens: int
    pruned_tokens: int

    @property
    def saved_ratio(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return 1 - self.pruned_tokens / self.original_tokens


def prune_passage(question: str, passage: str, max_anchors: int = 3) -> str:
    """Keep the `max_anchors` sentences sharing most terms with the question, plus neighbours."""
    query_terms = set(terms(question))
    sentences = split_sentences(passage)
    if len(sentences) <= 2 or not query_terms:
        return passage

    scores = [len(query_terms & set(terms(s))) for s in sentences]
    if max(scores) == 0:
        return passage  # nothing to anchor on: keep everything rather than guess

    ranked = sorted(range(len(sentences)), key=lambda i: (-scores[i], i))
    anchors = [i for i in ranked[:max_anchors] if scores[i] > 0]
    keep = {j for i in anchors for j in (i - 1, i, i + 1) if 0 <= j < len(sentences)}
    return " ".join(sentences[i] for i in sorted(keep))


def prune_passages(
    question: str, passages: list[str], max_anchors: int = 3
) -> tuple[list[str], PruneStats]:
    pruned = [prune_passage(question, p, max_anchors) for p in passages]
    stats = PruneStats(
        original_tokens=sum(estimate_tokens(p) for p in passages),
        pruned_tokens=sum(estimate_tokens(p) for p in pruned),
    )
    return pruned, stats
