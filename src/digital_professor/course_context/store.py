"""Read-only Question Schema view used during a tutoring turn.

The full schema remains owned by Course Context. Interaction receives only the
display-safe identifiers; the Tutoring Engine reads this view through the
question store described in ``specs/tutoring-engine.md`` section 2.3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class QuestionContext:
    question_id: str
    course_id: str
    prompt: str
    concept_ids: tuple[str, ...]
    concept_names: tuple[str, ...]
    course_title: str
    sibling_question_ids: tuple[str, ...] = ()


class JsonQuestionStore:
    """Load frozen Question Schemas and expose the Engine's required fields."""

    def __init__(
        self,
        schema_paths: tuple[Path, ...],
        *,
        course_title: str,
        course_context_path: Path | None = None,
    ) -> None:
        self._course_title = course_title
        self._questions: dict[str, QuestionContext] = {}
        concept_names: dict[str, str] = {}
        if course_context_path is not None:
            course_context = json.loads(course_context_path.read_text(encoding="utf-8"))
            concept_names = {
                concept["id"]: concept["name"] for concept in course_context.get("Concept", [])
            }
        for path in schema_paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            source = payload.get("source_reference") or {}
            concept_ids = tuple(payload.get("concept_ids") or ())
            self._questions[payload["question_id"]] = QuestionContext(
                question_id=payload["question_id"],
                course_id=payload["course_id"],
                prompt=payload["prompt"],
                concept_ids=concept_ids,
                concept_names=tuple(
                    concept_names.get(value, _concept_label(value)) for value in concept_ids
                ),
                course_title=course_title,
                sibling_question_ids=tuple(source.get("sibling_question_ids") or ()),
            )

    def register(self, qs: dict) -> str:
        """Register a runtime-built QuestionSchema dict and return its question_id."""
        concept_ids = tuple(qs.get("concept_ids") or ())
        qs_names: list[str] = qs.get("concept_names") or []
        source = qs.get("source_reference") or {}
        qid = qs["question_id"]
        self._questions[qid] = QuestionContext(
            question_id=qid,
            course_id=qs.get("course_id", ""),
            prompt=qs.get("prompt", ""),
            concept_ids=concept_ids,
            concept_names=tuple(
                qs_names[i] if i < len(qs_names) else _concept_label(cid)
                for i, cid in enumerate(concept_ids)
            ),
            course_title=self._course_title,
            sibling_question_ids=tuple(source.get("sibling_question_ids") or ()),
        )
        return qid

    def get(self, question_id: str) -> QuestionContext:
        try:
            return self._questions[question_id]
        except KeyError as error:
            raise LookupError(f"QuestionSchema not found: {question_id}") from error


def _concept_label(concept_id: str) -> str:
    return concept_id.rsplit(".", 1)[-1].replace("-", " ")
