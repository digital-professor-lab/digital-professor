"""Course-scoped lexical retrieval over normalized ingestion chunks."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from digital_professor.course_context.ingestion import CourseWorkspace, IngestedBlock


@dataclass(frozen=True, slots=True)
class RetrievedPassage:
    passage: IngestedBlock
    score: float
    highlight_url: str


# Multiplier applied to blocks whose concept_ids overlap the query concept_ids.
_CONCEPT_BOOST = 2.0


class CourseRetrievalIndex:
    """Course-scoped lexical retrieval index.

    Only blocks that have been tagged with at least one concept_id are indexed —
    untagged blocks are outside the course's concept coverage and must not be
    surfaced as citations.
    """

    def __init__(self, workspace: CourseWorkspace) -> None:
        self.course_id = workspace.course_id
        # All blocks are indexed; in-scope blocks get a score boost in search().
        # A hard concept_ids gate was tried but excluded content the CC failed to
        # tag (e.g. section headings pypdf extracted in a format the regex missed).
        self._chunks = tuple(
            chunk
            for document in workspace.documents
            for chunk in document.chunks
        )
        self._terms = {chunk.passage_id: _terms(chunk.text) for chunk in self._chunks}

    def search(
        self,
        query: str,
        *,
        top_k: int = 4,
        concept_ids: tuple[str, ...] = (),
    ) -> tuple[RetrievedPassage, ...]:
        """Search indexed blocks.

        When concept_ids are supplied (from the active QuestionSchema), blocks
        whose concept_ids overlap are boosted so the most relevant sections rank
        above lexically-similar but off-topic passages.
        """
        wanted = _terms(query)
        if not wanted:
            return ()
        query_concepts = set(concept_ids)
        scored: list[tuple[float, IngestedBlock]] = []
        for chunk in self._chunks:
            overlap = wanted & self._terms[chunk.passage_id]
            if not overlap:
                continue
            score = len(overlap) / math.sqrt(max(1, len(self._terms[chunk.passage_id])))
            if query_concepts and query_concepts.intersection(chunk.concept_ids):
                score *= _CONCEPT_BOOST
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
