"""Deterministic file extraction and page rendering."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Iterable

import fitz

from .schemas import DocumentIngestion, ExtractedPage, RenderedPage


TEXT_SUFFIXES = {".txt", ".md", ".tex"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def ingest_document(path: str | Path, max_pages: int | None = None) -> DocumentIngestion:
    """Extract embedded text from a PDF or read a UTF-8 text-like file."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    if source.suffix.lower() == ".pdf":
        with fitz.open(source) as document:
            limit = min(len(document), max_pages or len(document))
            pages = [
                ExtractedPage(page_number=index + 1, text=document[index].get_text("text").strip())
                for index in range(limit)
            ]
        media_type = "application/pdf"
    elif source.suffix.lower() in TEXT_SUFFIXES:
        pages = [ExtractedPage(page_number=1, text=source.read_text(encoding="utf-8"))]
        media_type = mimetypes.guess_type(source.name)[0] or "text/plain"
    else:
        raise ValueError(f"Embedded-text ingestion does not support {source.suffix!r}.")

    return DocumentIngestion(source_path=str(source), media_type=media_type, pages=pages)


def _selected_indices(total: int, pages: Iterable[int] | None, max_pages: int) -> list[int]:
    if pages is None:
        return list(range(min(total, max_pages)))
    indices = [page - 1 for page in pages]
    if any(index < 0 or index >= total for index in indices):
        raise IndexError(f"Requested pages must be between 1 and {total}.")
    return indices[:max_pages]


def render_document(
    path: str | Path,
    *,
    dpi: int = 180,
    pages: Iterable[int] | None = None,
    max_pages: int = 5,
) -> list[RenderedPage]:
    """Render selected PDF pages, or load a supported image, for visual recognition."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    suffix = source.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        media_type = mimetypes.guess_type(source.name)[0] or "image/jpeg"
        return [RenderedPage(page_number=1, image_bytes=source.read_bytes(), media_type=media_type)]
    if suffix != ".pdf":
        raise ValueError(f"Visual rendering does not support {suffix!r}.")

    rendered: list[RenderedPage] = []
    with fitz.open(source) as document:
        for index in _selected_indices(len(document), pages, max_pages):
            pixmap = document[index].get_pixmap(dpi=dpi, alpha=False)
            rendered.append(
                RenderedPage(page_number=index + 1, image_bytes=pixmap.tobytes("png"))
            )
    return rendered
