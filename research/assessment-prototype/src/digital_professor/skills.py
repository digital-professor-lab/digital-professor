"""Configurable instructional behavior loaded independently from task prompts."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class SkillInstructions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tutoring_instructions: str
    explanation_instructions: str
    review_instructions: str

    def tutor_prompt(self) -> str:
        return "\n\n".join(
            (
                self.tutoring_instructions,
                self.explanation_instructions,
                self.review_instructions,
            )
        )


def load_skill_instructions(path: str | Path | None = None) -> SkillInstructions:
    source = Path(path) if path else Path(__file__).with_name("skills.json")
    return SkillInstructions.model_validate(json.loads(source.read_text(encoding="utf-8")))
