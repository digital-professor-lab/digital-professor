"""Step 1 of Stage A — intake: load the course syllabus as plain text.

Accepts a PDF (extracted with pypdf) or a plain-text / Markdown file. The path
is configurable (default: the Calculus I syllabus), never hardcoded in callers.
"""
from __future__ import annotations

import pathlib


def load_syllabus(path: str | pathlib.Path) -> str:
    """Return the syllabus as plain text. Supports .pdf, .txt, .md."""
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Syllabus not found: {p}")

    suffix = p.suffix.lower()
    if suffix == ".pdf":
        text = _pdf_to_text(p)
    elif suffix in (".txt", ".md", ".markdown", ""):
        text = p.read_text(encoding="utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported syllabus format: {suffix!r} (use .pdf, .txt, or .md)")

    text = _normalize(text)
    if not text.strip():
        raise ValueError(f"No text extracted from {p} (is it a scanned/image-only PDF?)")
    return text


def _pdf_to_text(p: pathlib.Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(p))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n\n".join(pages)


def _normalize(text: str) -> str:
    """Light cleanup: normalize whitespace, drop empty-line runs."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if ln.strip():
            blank = 0
            out.append(ln)
        else:
            blank += 1
            if blank <= 1:
                out.append("")
    return "\n".join(out).strip()
