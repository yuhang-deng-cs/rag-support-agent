"""Recursive text chunking with overlap.

Splits on the coarsest boundary that fits (headings -> paragraphs -> lines -> sentences ->
words -> characters) and packs pieces greedily up to `chunk_size` characters. The last
`overlap` characters of each chunk are carried into the next one so facts that straddle a
boundary stay retrievable. All split patterns are zero-width, so no text is lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BOUNDARIES = (
    re.compile(r"(?=\n#{1,6} )"),  # before a markdown heading
    re.compile(r"(?<=\n\n)"),  # after a blank line
    re.compile(r"(?<=\n)"),  # after a line break
    re.compile(r"(?<=[.!?] )|(?<=[。！？])"),  # after a sentence
    re.compile(r"(?<= )"),  # after a word
)
_HEADING_RE = re.compile(r"^#{1,6} +(\S.*)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int
    text: str
    heading: str | None


def _split(text: str, size: int, level: int = 0) -> list[str]:
    if len(text) <= size:
        return [text]
    if level == len(_BOUNDARIES):
        return [text[i : i + size] for i in range(0, len(text), size)]
    parts = [p for p in _BOUNDARIES[level].split(text) if p]
    if len(parts) == 1:
        return _split(text, size, level + 1)
    out: list[str] = []
    for part in parts:
        out.extend(_split(part, size, level + 1))
    return out


def _overlap_tail(text: str, overlap: int) -> str:
    """Last ~`overlap` chars of `text`, starting at a word boundary when possible."""
    if overlap == 0:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) // 2 else tail


def _pack(pieces: list[str], chunk_size: int, overlap: int) -> list[str]:
    bodies: list[str] = []
    current = ""
    for piece in pieces:
        if len(current) + len(piece) <= chunk_size:
            current += piece
            continue
        if current.strip():
            bodies.append(current.strip())
        carry = _overlap_tail(current, overlap)
        current = carry + piece if len(carry) + len(piece) <= chunk_size else piece
    if current.strip():
        bodies.append(current.strip())
    return bodies


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 120) -> list[Chunk]:
    """Split `text` into overlapping chunks, each tagged with the heading it falls under."""
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    chunks: list[Chunk] = []
    section: str | None = None  # heading in effect at the end of the previous chunk
    for i, body in enumerate(_pack(_split(text, chunk_size), chunk_size, overlap)):
        headings = [h.strip() for h in _HEADING_RE.findall(body)]
        own = headings[0] if headings and body.startswith("#") else section
        chunks.append(Chunk(index=i, text=body, heading=own))
        if headings:
            section = headings[-1]
    return chunks
