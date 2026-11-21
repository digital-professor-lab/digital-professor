"""Learner state for one question: the question state and its gaps (``specs/tutoring-engine.md`` §5.6, App. A).

A *gap* is one thing the student still has to show: the method, a prerequisite, a misconception that has
appeared, or mastery. Every change to a gap names the evidence that caused it and why, so the state can
always be traced back to something the student wrote or to a math check.

Nothing here calls a model or does I/O. The Engine works on a copy of the state during a turn and replaces
the committed state only after the reply has been presented (§5.12).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

_ORDER = {"open": 0, "partial": 1, "closed": 2}
# Which gap a diagnosis points at when the judge names none (or names one that is already closed).
_TARGET_KIND = {"D2": ("prerequisite", "method"), "D1": ("method",), "D0": ("method", "prerequisite")}
_ERROR_DIAGNOSES = frozenset({"D1", "D2", "D3", "D4", "D5", "D6", "D7"})
_SLOT = re.compile(r"^(correct_approach|mastery|prerequisite_concepts\[(\d+)\]|common_misconceptions\[(\d+)\])$")


@dataclass(slots=True)
class Gap:
    gap_id: str
    gap_type: str                       # method | prerequisite | misconception | mastery
    target_slot: str                    # the QuestionSchema field this gap comes from
    requirement: str
    status: str = "open"                # open | partial | closed
    evidence_ids: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)   # every status change, with its reason

    def to_dict(self) -> dict[str, Any]:
        return {"gap_id": self.gap_id, "gap_type": self.gap_type, "target_slot": self.target_slot,
                "requirement": self.requirement, "status": self.status,
                "evidence_ids": list(self.evidence_ids), "history": [dict(h) for h in self.history]}


@dataclass(slots=True)
class QuestionState:
    """What the Engine remembers about one question. ``gaps`` is kept with it so both commit together."""

    phase: str = "WORKING"              # WORKING | SOLVED_CHECK | SOLVED | PARKED
    main_solved: bool = False
    solved_by: str | None = None        # tool | model
    help_level: int = 0                 # the most help given so far (policy.HELP_NAMES)
    help_requests: int = 0              # times the student asked for help or for the answer
    error_attempts: int = 0             # attempts that were marked wrong
    shown_work: bool = False            # the student showed steps or reasoning at some point
    stall_count: int = 0                # turns the student saw help and made no progress
    turn_count: int = 0
    guess_count: int = 0
    assisted: bool = False              # the student saw help at level 1 or above on this problem
    has_attempt: bool = False
    solved_check_asked: bool = False
    last_diagnosis: str | None = None
    correct_level: str | None = None    # D8 no work shown | D9 after help | D10 independent, with work
    verdict_source: str = "none"        # tool | model | none
    target_gap: str | None = None       # target_slot of the gap being worked on
    last_move: str | None = None
    last_situation: str | None = None
    last_counts: bool = False           # the last reply was real help, not a fallback
    last_action_id: str | None = None
    state_version: int = 0
    park_reason: str | None = None
    frustrated: bool = False            # the student sounded frustrated at some point on this question
    shown_passages: list[dict[str, Any]] = field(default_factory=list)   # textbook passages attached so far
    gaps: dict[str, Gap] = field(default_factory=dict)

    @property
    def active_solved(self) -> bool:
        return self.main_solved

    def open_gaps(self) -> list[Gap]:
        return [g for g in self.gaps.values() if g.status != "closed"]

    def closed_gaps(self) -> list[Gap]:
        return [g for g in self.gaps.values() if g.status == "closed"]

    def gap_by_slot(self, slot: str | None) -> Gap | None:
        return next((g for g in self.gaps.values() if g.target_slot == slot), None)

    def outcome(self) -> str:
        """A plain label for where the question stands, for people reading the state."""
        if self.park_reason == "safety":
            return "stopped"
        if self.main_solved:
            return "solved"
        return "paused" if self.phase == "PARKED" else "in_progress"


_STEP_DETAIL = re.compile(r"\s+(?:using|with|where|by\s+(?:letting|setting|choosing|taking)|letting|setting|"
                          r"choosing|taking|on|applied\s+to|to\s+(?:find|evaluate|compute|solve))\b|[:;(,]",
                          re.IGNORECASE)


def method_name(technique: str) -> str:
    """The name of the method without the steps of this problem.

    A Question Schema builder may write a technique such as "Integration by parts using u = x and
    dv = cos(x) dx". The part after the name is a key step of the problem. It must not reach the writer
    through a card's goal, so only the name is kept: "Integration by parts".
    """
    name = _STEP_DETAIL.split(" ".join(technique.split()), maxsplit=1)[0].strip(" .")
    return name if len(name) >= 4 else " ".join(technique.split())


def build_gaps(question: Any) -> dict[str, Gap]:
    """The gaps a question starts with: the method, each prerequisite, and mastery (§5.6)."""
    gaps: dict[str, Gap] = {}
    technique = (getattr(question, "correct_approach", None) or {}).get("technique", "")
    if getattr(question, "status", None) == "review_required":
        # A placeholder schema (no lesson plan was built): its technique is a stand-in, not the real method.
        gaps["method"] = Gap("method", "method", "correct_approach",
                             "Choose and apply a suitable method for this problem")
    elif technique:
        gaps["method"] = Gap("method", "method", "correct_approach", f"Demonstrate: {method_name(technique)}")
    for i, prerequisite in enumerate(getattr(question, "prerequisite_concepts", None) or ()):
        name = prerequisite.get("name") or prerequisite.get("concept_id") or f"prerequisite {i}"
        relevance = prerequisite.get("relevance", "")
        gaps[f"prereq_{i}"] = Gap(f"prereq_{i}", "prerequisite", f"prerequisite_concepts[{i}]",
                                  f"Apply {name}" + (f": {relevance}" if relevance else ""))
    objectives = [lo.get("text", "") for lo in getattr(question, "learning_objectives", None) or () if lo.get("text")]
    if gaps or objectives:
        gaps["mastery"] = Gap("mastery", "mastery", "mastery",
                              objectives[0] if objectives else "Solve a related problem without help")
    return gaps


def _new_misconception_gap(state: QuestionState, slot: str, question: Any) -> Gap | None:
    """A gap for a known misconception that has now appeared (§5.6), or None when ``slot`` names none."""
    match = _SLOT.match(slot or "")
    if not match or match.group(3) is None:
        return None
    index = int(match.group(3))
    misconceptions = getattr(question, "common_misconceptions", None) or ()
    if index >= len(misconceptions):
        return None
    item = misconceptions[index]
    text = item.get("description") or item.get("misconception") or item.get("cue") or f"misconception {index}"
    gap = Gap(f"misconception_{index}", "misconception", slot, f"Correct the misconception: {text}")
    state.gaps[gap.gap_id] = gap
    return gap


def _set(gap: Gap, status: str, *, evidence_id: str, reason: str, source: str) -> None:
    if gap.status == status:
        return
    gap.history.append({"from": gap.status, "to": status, "evidence_id": evidence_id, "reason": reason,
                        "source": source})
    gap.status = status
    if evidence_id not in gap.evidence_ids:
        gap.evidence_ids.append(evidence_id)


def _quoted(quote: str, text: str) -> bool:
    flatten = lambda value: " ".join(str(value).lower().split())  # noqa: E731
    quote = flatten(quote)
    return bool(quote) and quote in flatten(text)


def apply_gap_updates(state: QuestionState, updates: Sequence[Mapping[str, Any]], *, question: Any,
                      student_text: str, evidence_id: str, diagnosis: str | None,
                      ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the judge's proposed gap updates (§5.6). Returns ``(accepted, rejected)`` for the log.

    * An update is accepted only when its ``evidence_quote`` appears verbatim in the student's text.
    * A raise is capped at ``partial`` when the student was assisted on this problem.
    * A lower status is contradicting evidence: it reopens the gap only when this turn's diagnosis is an
      error, and the reason is recorded.
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for update in updates:
        slot, status = update.get("target_slot"), update.get("status")
        note = str(update.get("note") or "")[:200]
        record = {"target_slot": slot, "status": status}
        gap = state.gap_by_slot(slot) if isinstance(slot, str) else None
        if gap is None and isinstance(slot, str) and slot.startswith("common_misconceptions["):
            # A misconception becomes a gap only when it appears: on an error, shown in the student's words.
            if diagnosis not in _ERROR_DIAGNOSES:
                rejected.append({**record, "why": "a misconception is recorded only when an error shows it"})
            elif not _quoted(update.get("evidence_quote", ""), student_text):
                rejected.append({**record, "why": "quote is not in the student's text"})
            elif (created := _new_misconception_gap(state, slot, question)) is None:
                rejected.append({**record, "why": "unknown gap or status"})
            else:
                created.history.append({"from": None, "to": "open", "evidence_id": evidence_id,
                                        "reason": note or "the misconception appeared", "source": "model"})
                created.evidence_ids.append(evidence_id)
                accepted.append({**record, "from": None, "to": "open", "created": True})
            continue
        if gap is None or status not in _ORDER:
            rejected.append({**record, "why": "unknown gap or status"})
        elif gap.gap_type == "mastery":
            rejected.append({**record, "why": "mastery changes only by rule (a passed follow-up problem)"})
        elif not _quoted(update.get("evidence_quote", ""), student_text):
            rejected.append({**record, "why": "quote is not in the student's text"})
        elif _ORDER[status] > _ORDER[gap.status]:
            capped = "partial" if state.assisted and status == "closed" else status
            before = gap.status
            _set(gap, capped, evidence_id=evidence_id, reason=note or "shown in the student's work", source="model")
            if gap.status != before:
                accepted.append({**record, "from": before, "to": gap.status,
                                 **({"capped": "assisted"} if capped != status else {})})
        elif _ORDER[status] < _ORDER[gap.status]:
            if diagnosis in _ERROR_DIAGNOSES and note:
                before = gap.status
                _set(gap, status, evidence_id=evidence_id, reason=f"reopened: {note}", source="model")
                accepted.append({**record, "from": before, "to": gap.status, "reopened": True})
            else:
                rejected.append({**record, "why": "a lower status needs an error diagnosis and a reason"})
    return accepted, rejected


def choose_target_gap(state: QuestionState, diagnosis: str | None, proposed: str | None) -> str | None:
    """Which gap the next action works on.

    The judge's choice is used when it names a gap that is still open. Otherwise code picks by diagnosis:
    a missing prerequisite points at the first open prerequisite, a misconception that has appeared comes
    first, and everything else points at the method.
    """
    gap = state.gap_by_slot(proposed)
    if gap is not None and gap.status != "closed":
        return gap.target_slot
    open_gaps = state.open_gaps()
    for kind in ("misconception",) + _TARGET_KIND.get(diagnosis or "", ("method", "prerequisite")):
        for candidate in open_gaps:
            if candidate.gap_type == kind:
                return candidate.target_slot
    return open_gaps[0].target_slot if open_gaps else None


def mark_solved(state: QuestionState, *, evidence_id: str, source: str, understood: bool = True) -> None:
    """Solving the problem moves the method gap: ``partial`` with assistance or with a wrong stated reason,
    ``closed`` without assistance (§5.6)."""
    gap = state.gap_by_slot("correct_approach")
    if gap is None:
        return
    if not understood:
        if gap.status == "open":
            _set(gap, "partial", evidence_id=evidence_id, reason="right answer, wrong reasoning", source=source)
        return
    if state.assisted:
        if gap.status == "open":
            _set(gap, "partial", evidence_id=evidence_id, reason="solved with assistance", source=source)
    else:
        _set(gap, "closed", evidence_id=evidence_id, reason="solved without assistance", source=source)
