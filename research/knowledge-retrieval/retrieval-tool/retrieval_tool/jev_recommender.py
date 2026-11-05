"""Jev as the optional-search recommender for `may` turns.

The Tutoring Engine or coordinator applies the agreed grounding policy. The clear cases are fixed in the
table (must / must_not / not_needed). Only `may` turns (probe, diagnose, check_understanding, transfer,
Socratic hint, convention check) leave a real choice, and leaving it to the tutoring model alone has two
risks: the model may skip retrieval and answer from memory, or retrieve on every message. Jev answers one
yes/no question with a probability, which gives a cheap, cacheable, auditable recommendation with a
threshold the team can tune. The caller opts in by passing this recommender to `run_turn`:

    p >= force_at   → recommend search  (tool_choice="required"; enforced like a `must` turn)
    p <  skip_below → recommend no tool this turn
    otherwise       → the tutoring model decides (tool_choice="auto")
    Jev error       → the tutoring model decides, and the event is logged

The client is jev_client.py. The key comes from the environment or a private .env file (JEV_ENV_FILE).
The response cache is written to cache/ in this package folder.

Privacy: the student's message is sent to an external provider, so the recommender only runs when the course
policy sets `external_processing_allowed = True` (rag-retrieval.md §6.5, Q15).
"""

from __future__ import annotations

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


class JevSearchRecommender:
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

    def recommend(self, ctx: Any, goal: str = "") -> dict[str, Any]:
        p = self.probability(ctx, goal)
        choice = "force" if p >= self.force_at else "skip" if p < self.skip_below else "auto"
        return {"recommender": "jev", "p": round(p, 4), "choice": choice,
                "thresholds": {"force_at": self.force_at, "skip_below": self.skip_below}}


def load_jev_client(provider: str | None = None, *, cache_dir: Path | None = None) -> Any:
    """The Jev client. Key and provider come from the environment or a private .env file."""
    from .jev_client import JevClient, resolve_provider
    name = resolve_provider(provider)
    cache_dir = cache_dir or Path(__file__).resolve().parents[1] / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return JevClient(name, cache_path=cache_dir / f"jev_decider_{name}.jsonl")


def default_recommender(provider: str | None = None) -> tuple[JevSearchRecommender | None, str]:
    """The default `may`-turn recommender: Jev when its key is available, otherwise None (the model decides).

    Adopted 2026-10-29 after scripts/eval_tool_decisions.py: on 24 labelled `may` turns DeepSeek alone was
    17/24 (7 unneeded retrievals), Jev + DeepSeek 22/24 with 0 wrong forces / skips and 11% fewer DeepSeek calls.
    """
    try:
        return JevSearchRecommender(load_jev_client(provider)), "jev"
    except Exception as error:   # no key: keep working, the model decides
        return None, f"jev unavailable ({str(error)[:120]}); the model decides may-turns"


def default_evidence_judge(provider: str | None = None) -> Any:
    """Jev evidence judge (layer 3). Used in shadow mode until scripts/eval_evidence_judge.py supports it."""
    from .evidence import JevEvidenceJudge
    return JevEvidenceJudge(load_jev_client(provider))
