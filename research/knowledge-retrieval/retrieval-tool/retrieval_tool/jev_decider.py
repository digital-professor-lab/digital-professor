"""Jev as the retrieval decider for `may` turns.

The grounding policy fixes the clear cases in code (must / must_not / not_needed). Only for `may` turns
(probe, diagnose, check_understanding, transfer, Socratic hint, convention check) is there a real
decision, and leaving it to the tutoring model alone has two risks: the model may skip retrieval and
answer from memory, or retrieve on every message. Jev answers one yes/no question with a probability,
which gives a cheap, cacheable, auditable decision with a threshold the team can tune:

    p >= force_at   → force retrieval   (tool_choice="required"; enforced like a `must` turn)
    p <  skip_below → no tool this turn
    otherwise       → the tutoring model decides (tool_choice="auto")
    Jev error       → the tutoring model decides, and the event is logged

Week 5's `JevClient` is reused unchanged (week5 jev/jev_retrieval/client.py; key in week5 jev/.env).
Its response cache is written to week8/cache/, never into the week5 folder.

Privacy: the student's message is sent to an external provider, so the decider only runs when the course
policy sets `external_processing_allowed = True` (rag-retrieval.md §6.5, Q15).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

QUESTIONS: dict[str, dict[str, Any]] = {
    "needs_course_material": {
        "type": "noul",
        "instructions": ("Will a good tutor reply to `student_message`, for the tutoring action `tutoring_action`, "
                         "need to state course-specific content (a definition, formula, theorem, rule, method, "
                         "notation convention, or worked example as this course presents it)?"),
        "criteria": {
            "true": ("The reply must state or quote a definition, formula, theorem, rule, method, notation or example "
                     "as taught in this course, or the student asks what the course, textbook or notes say, or asks "
                     "for a course-style example or exercise."),
            "false": ("The reply can be a question back to the student, a request for their working, encouragement, "
                      "a clarification, or a hint that does not state course content; or the student's message makes "
                      "no content request (for example 'got it', 'let me think', 'one more like this')."),
        },
    },
}
FORCE_AT = 0.7      # same block threshold as the Week 5 gate; to be tuned on the decision set
SKIP_BELOW = 0.3


class JevRetrievalDecider:
    def __init__(self, client: Any, *, force_at: float = FORCE_AT, skip_below: float = SKIP_BELOW) -> None:
        if not 0.0 <= skip_below <= force_at <= 1.0:
            raise ValueError("need 0 <= skip_below <= force_at <= 1")
        self.client, self.force_at, self.skip_below = client, force_at, skip_below

    @staticmethod
    def state(ctx: Any, goal: str = "") -> dict[str, Any]:
        return {"tutoring_action": ctx.action_type, "pedagogical_goal": goal or "",
                "student_message": ctx.student_message or "",
                "upstream_understanding": ctx.intent_summary or "",
                "current_question": ctx.question_prompt or ""}

    def probability(self, ctx: Any, goal: str = "") -> float:
        answers = self.client.ask(self.state(ctx, goal), QUESTIONS)
        return float(answers["needs_course_material"]["noul"])

    def decide(self, ctx: Any, goal: str = "") -> dict[str, Any]:
        p = self.probability(ctx, goal)
        choice = "force" if p >= self.force_at else "skip" if p < self.skip_below else "auto"
        return {"decider": "jev", "p": round(p, 4), "choice": choice,
                "thresholds": {"force_at": self.force_at, "skip_below": self.skip_below}}


def week5_folder() -> Path | None:
    import os
    week8 = Path(__file__).resolve().parents[1]
    path = Path(os.environ.get("WEEK5_JEV", week8.parent / "week5 jev"))
    return path if (path / "jev_retrieval" / "client.py").exists() else None


def load_week5_jev_client(provider: str | None = None, *, cache_dir: Path | None = None) -> Any:
    """Week 5's JevClient (unchanged). Key and provider come from the environment or week5 jev/.env."""
    folder = week5_folder()
    if folder is None:
        raise RuntimeError("week5 jev folder not found next to week8; set WEEK5_JEV")
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    from jev_retrieval.client import JevClient, resolve_provider  # type: ignore
    name = resolve_provider(provider)
    cache_dir = cache_dir or Path(__file__).resolve().parents[1] / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return JevClient(name, cache_path=cache_dir / f"jev_decider_{name}.jsonl")


def default_decider(provider: str | None = None) -> tuple[JevRetrievalDecider | None, str]:
    """The default `may`-turn decider: Jev when its key is available, otherwise None (the model decides).

    Adopted 2026-10-29 after scripts/eval_tool_decisions.py: on 24 labelled `may` turns DeepSeek alone was
    17/24 (7 unneeded retrievals), Jev + DeepSeek 22/24 with 0 wrong forces / skips and 11% fewer DeepSeek calls.
    """
    try:
        return JevRetrievalDecider(load_week5_jev_client(provider)), "jev"
    except Exception as error:   # no key / no week5 folder: keep working, the model decides
        return None, f"jev unavailable ({str(error)[:120]}); the model decides may-turns"


def default_evidence_judge(provider: str | None = None) -> Any:
    """Jev evidence judge (layer 3). Used in shadow mode until scripts/eval_evidence_judge.py supports it."""
    from .evidence import JevEvidenceJudge
    return JevEvidenceJudge(load_week5_jev_client(provider))
