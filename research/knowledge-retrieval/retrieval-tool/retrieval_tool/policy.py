"""Grounding policy: for each tutoring action, does this turn retrieve, and how strictly?

This is the "function written in code" half of the design. It runs once per turn in the outer
loop, before the model is called; the model never sees it and cannot bypass it.

Modes
-----
must        Retrieval is guaranteed. The tool is offered with tool_choice="required", so the model
            must write the query on its first step; if the provider cannot force a tool call, the
            system pre-fetches with a structured request instead.
may         The tool is offered with tool_choice="auto"; the model decides.
not_needed  The tool is not offered this turn (nothing course-specific is said).
must_not    The tool is not offered, and any attempted call is rejected (retrieval would add nothing
            or cause harm, e.g. correctness checking belongs to a math tool).

The table follows rag-retrieval.md §2.2 (rules R1-R4). The Engine owner owns the
state → action mapping; this module owns only the retrieval column. [Proposed]
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .records import TUTORING_ACTIONS

POLICY_VERSION = "grounding-policy@0.1"
MODES = ("must", "may", "not_needed", "must_not")


@dataclass(frozen=True)
class PolicyRow:
    mode: str
    purposes: tuple[str, ...] = ()
    need_types: tuple[str, ...] = ()
    exclude_current_problem: bool = False
    engine_only: bool = False
    fallback: str = ""
    note: str = ""


# rag-retrieval.md §2.2, "Retrieval column for the Engine's actions"
GROUNDING_POLICY: dict[str, PolicyRow] = {
    "elicit": PolicyRow("not_needed", note="Start of a question; ask for the student's attempt."),
    "inspect": PolicyRow("must_not", note="R2: only a final answer was given; ask for the work."),
    "probe": PolicyRow("may", ("definition_lookup",), ("definition", "notation_convention"),
                       fallback="Probe without course wording."),
    "diagnose": PolicyRow("may", ("diagnosis_support",), ("definition", "theorem_statement"),
                          engine_only=True, fallback="Diagnose from QuestionSchema cues alone."),
    "hint": PolicyRow("must", ("hint_support",), ("formula_statement", "method_guidance"),
                      exclude_current_problem=True,
                      fallback="Give a Socratic hint without a course citation.",
                      note="R1: must when the hint states a course method or formula; a purely Socratic "
                           "hint may be downgraded with states_course_content=False."),
    "contrast": PolicyRow("must", ("example_lookup", "hint_support"), ("worked_example", "method_guidance"),
                          exclude_current_problem=True,
                          fallback="Contrast the two methods without a course example."),
    "demonstrate": PolicyRow("must", ("example_lookup",), ("worked_example",), exclude_current_problem=True,
                             fallback="Switch to contrast, or an example labelled 'not from course materials' "
                                      "if policy allows."),
    "explain": PolicyRow("must", ("answer_grounding", "prerequisite_review", "definition_lookup"),
                         ("definition", "theorem_statement", "prerequisite_explanation"),
                         fallback="Brief general explanation labelled 'not from course materials' if policy "
                                  "allows; otherwise say no course material covers this point."),
    "retry": PolicyRow("not_needed", note="Refers back to the previous action."),
    "verify": PolicyRow("must_not", note="R2: correctness is a math/verification tool, not retrieval. "
                                         "May be relaxed to a convention check with checks_course_convention=True."),
    "check_understanding": PolicyRow("may", ("practice_generation",), ("worked_example", "exercise"),
                                     exclude_current_problem=True, fallback="Engine-written check question."),
    "transfer": PolicyRow("may", ("practice_generation",), ("exercise", "worked_example"),
                          exclude_current_problem=True, fallback="Engine-written transfer question."),
}

assert set(GROUNDING_POLICY) == set(TUTORING_ACTIONS), "policy must cover every TutoringAction"


@dataclass(frozen=True)
class PolicyDecision:
    action_type: str
    mode: str
    purposes: tuple[str, ...]
    need_types: tuple[str, ...]
    exclude_current_problem: bool
    engine_only: bool
    fallback: str
    reason: str
    policy_version: str = POLICY_VERSION
    max_tool_calls: int = 2

    @property
    def offer_tool(self) -> bool:
        return self.mode in ("must", "may")

    @property
    def tool_choice(self) -> str | None:
        """Value for the LLM API's tool_choice; None means do not send the tool at all."""
        return {"must": "required", "may": "auto"}.get(self.mode)

    def to_dict(self) -> dict[str, Any]:
        return {"action_type": self.action_type, "mode": self.mode, "purposes": list(self.purposes),
                "need_types": list(self.need_types), "tool_choice": self.tool_choice,
                "exclude_current_problem": self.exclude_current_problem, "engine_only": self.engine_only,
                "fallback": self.fallback, "reason": self.reason, "policy_version": self.policy_version}


def decide(action_type: str, *, states_course_content: bool | None = None,
           checks_course_convention: bool = False, course_ready: bool = True) -> PolicyDecision:
    """Decide the retrieval mode for one turn.

    states_course_content     Engine flag for `hint`: False = purely Socratic hint (downgrade must → may).
    checks_course_convention  Engine flag for `verify`: True = a notation-convention check is allowed (may).
    course_ready              False when the course has no published release; the tool is then not offered
                              and the fallback applies (a stop would be returned anyway).
    """
    if action_type not in GROUNDING_POLICY:
        raise ValueError(f"unknown action_type '{action_type}'; expected one of {', '.join(TUTORING_ACTIONS)}")
    row = GROUNDING_POLICY[action_type]
    decision = PolicyDecision(action_type=action_type, mode=row.mode, purposes=row.purposes,
                              need_types=row.need_types, exclude_current_problem=row.exclude_current_problem,
                              engine_only=row.engine_only, fallback=row.fallback,
                              reason=row.note or f"policy table: {row.mode}")
    if action_type == "hint" and states_course_content is False:
        decision = replace(decision, mode="may", reason="Socratic hint without course content: downgraded to may")
    if action_type == "verify" and checks_course_convention:
        decision = replace(decision, mode="may", purposes=("definition_lookup",),
                           need_types=("notation_convention",),
                           reason="Course notation convention check allowed; correctness is still not retrieval")
    if not course_ready and decision.offer_tool:
        decision = replace(decision, mode="not_needed",
                           reason="course_not_ready: no published retrieval release; use the fallback")
    return decision


def policy_table() -> list[dict[str, Any]]:
    """The full table, for documentation and for review by the Engine owner."""
    return [decide(action).to_dict() for action in TUTORING_ACTIONS]
