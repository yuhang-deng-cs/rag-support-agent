"""Unit tests for the pure RAG building blocks."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.rag.chunking import chunk_text
from app.rag.embeddings import HashingEmbedder
from app.rag.parsing import UnsupportedFileError, extract_text
from app.rag.pruning import prune_passage, prune_passages
from app.rag.text import estimate_tokens, stem, terms

LONG_DOC = "# Guide\n\n" + "\n\n".join(
    f"## Section {i}\n\n" + " ".join(f"Fact {i}.{j} about topic {i}." for j in range(12))
    for i in range(8)
)


class TestChunking:
    def test_respects_size_limit(self):
        chunks = chunk_text(LONG_DOC, chunk_size=300, overlap=50)
        assert len(chunks) > 5
        assert all(len(c.text) <= 300 for c in chunks)

    def test_no_content_is_lost(self):
        chunks = chunk_text(LONG_DOC, chunk_size=300, overlap=50)
        joined = " ".join(c.text for c in chunks)
        for i in range(8):
            for j in range(12):
                assert f"Fact {i}.{j} " in joined + " "

    def test_tracks_headings(self):
        chunks = chunk_text(LONG_DOC, chunk_size=300, overlap=50)
        assert chunks[0].heading == "Guide"
        assert any(c.heading == "Section 3" for c in chunks)

    def test_short_text_is_one_chunk(self):
        assert [c.text for c in chunk_text("  hello world  ")] == ["hello world"]
        assert chunk_text("   ") == []

    def test_rejects_overlap_not_smaller_than_size(self):
        with pytest.raises(ValueError):
            chunk_text("x", chunk_size=100, overlap=100)


class TestText:
    def test_terms_drop_stopwords_and_stem(self):
        assert terms("How long do the refunds take?") == ["long", "refund", "take"]

    def test_terms_handle_cjk_bigrams(self):
        assert terms("退款政策") == ["退款", "款政", "政策"]

    @pytest.mark.parametrize(
        ("word", "expected"),
        [
            ("refunds", "refund"),
            ("refunded", "refund"),
            ("policies", "policy"),
            ("access", "access"),
        ],
    )
    def test_stem(self, word, expected):
        assert stem(word) == expected

    def test_estimate_tokens(self):
        assert estimate_tokens("abcd" * 10) == 10
        assert estimate_tokens("退款政策") == 4


class TestPruning:
    PASSAGE = (
        "Acme was founded in 2019. The office has a nice view. "
        "Refunds are returned within 5 to 10 business days. "
        "Our mascot is a cat. Lunch is served at noon. The parking lot is large."
    )

    def test_keeps_relevant_sentence_and_drops_noise(self):
        pruned = prune_passage("How long do refunds take?", self.PASSAGE, max_anchors=1)
        assert "5 to 10 business days" in pruned
        assert "parking" not in pruned

    def test_keeps_everything_when_nothing_matches(self):
        assert prune_passage("quantum chromodynamics", self.PASSAGE) == self.PASSAGE

    def test_reports_savings(self):
        _, stats = prune_passages("refunds", [self.PASSAGE], max_anchors=1)
        assert stats.pruned_tokens < stats.original_tokens
        assert 0 < stats.saved_ratio < 1


class TestHashingEmbedder:
    async def test_deterministic_and_normalized(self):
        embedder = HashingEmbedder(64)
        a, b = await embedder.embed_documents(["refund policy", "refund policy"])
        assert a == b
        assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)

    async def test_shared_terms_score_higher(self):
        embedder = HashingEmbedder(256)
        q = await embedder.embed_query("refund window")
        near, far = await embedder.embed_documents(["the refund window is 30 days", "SSO via SAML"])
        dot = lambda u, v: sum(x * y for x, y in zip(u, v, strict=True))  # noqa: E731
        assert dot(q, near) > dot(q, far)


class TestParsing:
    def test_text_and_markdown(self):
        assert extract_text("a.md", b"# Hi") == "# Hi"

    @pytest.mark.parametrize(
        ("name", "data"), [("a.exe", b"x"), ("a.txt", b""), ("a.txt", b"\xff\xfe\xfa")]
    )
    def test_rejects_bad_input(self, name, data):
        with pytest.raises(UnsupportedFileError):
            extract_text(name, data)


class TestSettings:
    def test_production_requires_real_secret(self):
        with pytest.raises(ValidationError, match="JWT_SECRET"):
            Settings(_env_file=None, app_env="production")

    def test_production_forbids_demo_seed(self):
        with pytest.raises(ValidationError, match="SEED_DEMO"):
            Settings(_env_file=None, app_env="production", jwt_secret="s" * 40, seed_demo=True)
