"""Small, dependency-free text utilities shared by chunking, pruning and hashing embeddings.

Handles both space-delimited languages and CJK (which has no spaces) by emitting
character bigrams for CJK runs.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9]+(?:['\-][a-z0-9]+)*")

# Hiragana/Katakana, CJK Extension A, CJK Unified Ideographs, Hangul syllables.
_CJK_RANGES = ((0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7AF))
_CJK_RE = re.compile("[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _CJK_RANGES) + "]+")
# Sentence ends: ".!?" followed by space (but not "1. " list markers), CJK full stops, newlines.
_SENTENCE_RE = re.compile(r"(?<=[^\s\d][.!?])\s+|(?<=[。！？])|\n+")

STOPWORDS = frozenset(
    """
    a an and are as at be but by can could do does for from had has have how i if in into is it
    its me my of on or our please should so than that the their them then there these they this
    to was we what when where which who why will with would you your
    请问 怎么 如何 什么 可以 一下 我们 你们 是否 多少
    """.split()  # noqa: SIM905 - a word list reads better than a 70-item literal
)


def stem(word: str) -> str:
    """Tiny suffix stripper so "refunds", "refunded" and "refunding" match "refund"."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) - len(suffix) >= 3 and word.endswith(suffix) and not word.endswith("ss"):
            return word[: -len(suffix)]
    # "cause" -> "caus" so it meets "caused" -> "caus" and "causes" -> "caus".
    if len(word) > 4 and word.endswith("e"):
        return word[:-1]
    return word


def terms(text: str) -> list[str]:
    """Lower-cased content terms: stemmed words (minus stopwords) plus CJK character bigrams."""
    lowered = text.lower()
    out = [stem(w) for w in _WORD_RE.findall(lowered) if w not in STOPWORDS and len(w) > 1]
    for run in _CJK_RE.findall(lowered):
        if len(run) == 1:
            out.append(run)
        out.extend(run[i : i + 2] for i in range(len(run) - 1))
    return [t for t in out if t not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text) if s and s.strip()]


def estimate_tokens(text: str) -> int:
    """Cheap tokenizer-free estimate: ~4 chars/token for Latin text, ~1 token per CJK char."""
    cjk = sum(len(run) for run in _CJK_RE.findall(text))
    return max(0, round(cjk + (len(text) - cjk) / 4))
