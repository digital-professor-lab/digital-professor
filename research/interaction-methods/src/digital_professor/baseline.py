"""Local, non-LLM recognition baselines for comparison experiments."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from .ingestion import render_document
from .schemas import PageContent, RecognitionResult, RequestMetadata


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def recognize_with_tesseract(
    path: str | Path,
    *,
    dpi: int = 180,
    max_pages: int = 5,
) -> RecognitionResult:
    """Run Tesseract locally on rendered pages without an external model API."""
    if not tesseract_available():
        raise RuntimeError(
            "Tesseract is not installed. On macOS, install it with `brew install tesseract`."
        )

    source = Path(path).expanduser().resolve()
    rendered = render_document(source, dpi=dpi, max_pages=max_pages)
    pages: list[PageContent] = []
    requests: list[RequestMetadata] = []
    for page in rendered:
        started_at = time.perf_counter()
        process = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "6"],
            input=page.image_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        elapsed = time.perf_counter() - started_at
        if process.returncode != 0:
            error = process.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Tesseract failed on page {page.page_number}: {error}")
        text = process.stdout.decode("utf-8", errors="replace").strip()
        uncertainties = [
            "Tesseract is a printed-text baseline and does not reconstruct two-dimensional equations as LaTeX."
        ]
        if not text:
            uncertainties.append("No text was recognized on this page.")
        pages.append(
            PageContent(
                page_number=page.page_number,
                markdown=text or "*[No text recognized by the local baseline]*",
                equations=[],
                uncertainties=uncertainties,
            )
        )
        requests.append(
            RequestMetadata(
                response_id=None,
                model="tesseract",
                elapsed_seconds=elapsed,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                estimated_cost_usd=0.0,
                cost_basis="Local execution; API cost $0",
            )
        )
    return RecognitionResult(
        pages=pages,
        document_summary="Local Tesseract OCR baseline output.",
        source_path=str(source),
        method="tesseract_local",
        model="tesseract",
        requests=requests,
    )
