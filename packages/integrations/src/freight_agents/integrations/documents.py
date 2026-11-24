"""Text from documents that arrive with tenders and claims.

PDF text comes from pypdf's layout-free extraction. A scanned PDF has no text layer
and returns an empty string; the caller treats that as "needs a person", because
optical character recognition is out of scope here.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class DocumentError(ValueError):
    pass


def pdf_text(path: Path) -> str:
    try:
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PdfReadError, OSError) as exc:
        raise DocumentError(f"{path.name} is not a readable PDF: {exc}") from exc
