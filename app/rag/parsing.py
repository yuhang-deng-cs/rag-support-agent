"""Turn uploaded files into plain text."""

from __future__ import annotations

import io
from pathlib import PurePath

SUPPORTED_EXTENSIONS = {".txt": "text/plain", ".md": "text/markdown", ".pdf": "application/pdf"}


class UnsupportedFileError(ValueError):
    pass


def content_type_for(filename: str) -> str:
    ext = PurePath(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedFileError(f"Unsupported file type {ext or '(none)'}; allowed: {allowed}")
    return SUPPORTED_EXTENSIONS[ext]


def extract_text(filename: str, data: bytes) -> str:
    content_type = content_type_for(filename)
    if content_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(p.strip() for p in pages if p.strip())
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UnsupportedFileError("Text files must be UTF-8 encoded") from exc
    if not text.strip():
        raise UnsupportedFileError("No extractable text found in file")
    return text
