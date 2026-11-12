"""Course-scoped lexical retrieval over normalized ingestion chunks."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from digital_professor.course_context.ingestion import CourseWorkspace, SourceChunk


@dataclass(frozen=True, slots=True)
class RetrievedPassage:
    passage: SourceChunk
    score: float
    highlight_url: str


class CourseRetrievalIndex:
    """Small replaceable index for the demo; preserves source locations."""

    def __init__(self, workspace: CourseWorkspace) -> None:
        self.course_id = workspace.course_id
        self._chunks = tuple(
            chunk for document in workspace.documents for chunk in document.chunks
        )
        self._terms = {chunk.passage_id: _terms(chunk.text) for chunk in self._chunks}

    def search(self, query: str, *, top_k: int = 4) -> tuple[RetrievedPassage, ...]:
        wanted = _terms(query)
        if not wanted:
            return ()
        scored: list[tuple[float, SourceChunk]] = []
        for chunk in self._chunks:
            overlap = wanted & self._terms[chunk.passage_id]
            if not overlap:
                continue
            score = len(overlap) / math.sqrt(max(1, len(self._terms[chunk.passage_id])))
            scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].passage_id))
        return tuple(
            RetrievedPassage(
                passage=chunk,
                score=round(score, 4),
                highlight_url=(
                    f"/api/courses/{self.course_id}/sources/{chunk.document_id}"
                    f"?page={chunk.page_number}&line_start={chunk.line_start}"
                    f"&line_end={chunk.line_end}"
                ),
            )
            for score, chunk in scored[:top_k]
        )


def _terms(text: str) -> set[str]:
    stop = {
        "about", "after", "again", "could", "from", "have", "into", "please",
        "should", "that", "their", "there", "these", "this", "what", "when",
        "where", "which", "with", "would", "your",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in stop
    }
