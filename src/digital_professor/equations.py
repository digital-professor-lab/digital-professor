"""Small local helpers for finding already-delimited LaTeX expressions."""

from __future__ import annotations

import re

from .schemas import EquationCandidate


_LATEX_PATTERNS = (
    re.compile(r"\$\$(.+?)\$\$", re.DOTALL),
    re.compile(r"\\\[(.+?)\\\]", re.DOTALL),
    re.compile(r"\\\((.+?)\\\)", re.DOTALL),
    re.compile(r"(?<!\$)\$([^$\n]+?)\$(?!\$)"),
)


def extract_delimited_equations(text: str) -> list[EquationCandidate]:
    """Extract explicit TeX math spans without pretending to OCR plain PDF glyphs."""
    matches: list[tuple[int, str]] = []
    for pattern in _LATEX_PATTERNS:
        matches.extend((match.start(), match.group(1).strip()) for match in pattern.finditer(text))
    matches.sort(key=lambda item: item[0])
    return [
        EquationCandidate(
            latex=latex,
            source_text=latex,
            confidence=1.0,
            ambiguous=False,
            alternatives=[],
        )
        for _, latex in matches
    ]
