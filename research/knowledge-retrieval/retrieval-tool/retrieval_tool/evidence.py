"""Evidence check (rag-retrieval.md §7.9): does a passage actually state what each need asks for?

Layers, most to least trustworthy:
  1. human-confirmed pinned passages (QuestionSchema passage_refs) – passed in by the caller
  2. deterministic rules by need type (this module)
  3. optional model judge (e.g. the Week 5 Jev design) – injected, off by default
  4. nothing applicable → at most `partially_covered` + `sufficiency_uncertain`

"Found similar text" is not "covered". Search scores are never used here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from .backends import terms

# need types whose rule may mark a need `covered` (rule reliability medium or better)
RULE_CAN_COVER = {"formula_statement", "definition", "theorem_statement", "worked_example", "exercise",
                  "notation_convention"}
GENERIC_WORDS = {"definition", "define", "formula", "theorem", "rule", "method", "guidance", "worked", "exercise",
                 "notation", "convention", "explanation", "prerequisite", "need", "show", "state", "how", "why",
                 "choose", "course", "material", "concept", "idea", "step", "statement", "explain", "illustrate",
                 "compare", "contrast", "relate", "related", "relation", "relationship", "describe", "identify", "list",
                 "role", "mean", "meaning", "introduce", "introduced", "appear", "cover", "covered", "one", "two"}
DEFINING = re.compile(r"\b(is defined (as|by)|we say|is called|definition|denoted|means that|refers to)\b"
                      r"|\\begin\{definition\}|:=", re.I)
THEOREM = re.compile(r"\\begin\{(theorem|proposition|lemma|corollary)\}|\btheorem\b|\bstates that\b", re.I)
EXAMPLE = re.compile(r"\\begin\{example\}|\bexamples?\b|\be\.g\.|\bworked\b|\bfor instance\b|\bapplications?\b", re.I)
EXERCISE = re.compile(r"\\begin\{(exercise|problem)\}|\bexercises?\b|\bproblems?\b|\bpractice\b", re.I)
NOTATION = re.compile(r"\bdenot|\bnotation\b|\bwritten as\b|\bwe write\b|\bsymbol\b", re.I)
MATH = re.compile(r"=|\\frac|\\int|\\sum|\\lim|\^|'|\$")
FORMULA_ANCHOR = re.compile(r"[=^'/+*∫√]|\\[a-zA-Z]+|\d|[a-z]\(|−|-\s*\w")   # looks like a formula, not a term


def normalize_math(text: str) -> str:
    """Notation normalization for formula anchors (course-context.md Q9): ∫↔\\int, ²↔^2, \\cos↔cos, spacing."""
    table = {"∫": "int", "−": "-", "–": "-", "′": "'", "²": "^2", "³": "^3", "·": "*", "×": "*", "⋅": "*",
             "√": "sqrt", "π": "pi", "θ": "theta", "∞": "infty", "≤": "<=", "≥": ">="}
    for a, b in table.items():
        text = text.replace(a, b)
    text = re.sub(r"\\(left|right|displaystyle|,|;|!|quad)", "", text)
    text = re.sub(r"\\([a-zA-Z]+)", r"\1", text)      # \cos -> cos, \int -> int
    text = re.sub(r"[\s{}$]", "", text.lower())
    text = text.replace("\\", "")
    return text


@dataclass
class NeedResult:
    need_id: str
    coverage: str          # covered / partially_covered / not_covered
    passage_ids: list[str]
    method: str            # pinned / rule:<need_type> / judge / none
    detail: str = ""


def target_terms(need: dict[str, Any], concept_names: list[str] | None = None) -> list[str]:
    source = need.get("anchor") or need.get("description", "")
    found = [t for t in terms(source) if t not in GENERIC_WORDS]
    if not found and concept_names:
        found = [t for name in concept_names for t in terms(name) if t not in GENERIC_WORDS]
    return list(dict.fromkeys(found))[:6]


def _mentions(name: str, text_terms: set[str]) -> bool:
    """Most content terms (>= 60%) of `name` (a concept or a term anchor) occur in the passage."""
    wanted = list(dict.fromkeys(t for t in terms(name) if t not in GENERIC_WORDS))
    return bool(wanted) and sum(t in text_terms for t in wanted) / len(wanted) >= 0.6


def is_formula(anchor: str | None) -> bool:
    return bool(anchor) and bool(FORMULA_ANCHOR.search(anchor))


def rule_check(need: dict[str, Any], passage_text: str, concept_names: list[str] | None = None) -> tuple[str, str]:
    """Layer 2. Returns (coverage, detail) for one need against one passage.

    Gates, in order: (a) when the turn's concepts are known, the passage must mention one of them;
    (b) a given anchor must occur (a formula anchor after notation normalization); (c) otherwise at least
    60% of the need's content terms must occur. Only then does the need-type marker decide covered vs partial.
    """
    need_type = need["need_type"]
    text_terms = set(terms(passage_text))
    if concept_names and not any(_mentions(name, text_terms) for name in concept_names):
        return "not_covered", f"none of the turn's concepts {concept_names} is mentioned"
    anchor = need.get("anchor")
    formula = is_formula(anchor)
    if anchor:
        anchor_hit = (anchor.lower() in passage_text.lower()
                      or (formula and normalize_math(anchor) in normalize_math(passage_text))
                      or (not formula and _mentions(anchor, text_terms)))
        if not anchor_hit:
            return "not_covered", f"anchor {anchor!r} absent"
        how = "anchor present"
    else:
        wanted = target_terms(need, concept_names)
        share = sum(t in text_terms for t in wanted) / len(wanted) if wanted else 0.0
        if share < 0.6:
            return "not_covered", f"target terms {wanted} share={share:.2f}"
        how = f"target terms share={share:.2f}"
    if need_type == "formula_statement":
        if formula and normalize_math(anchor) in normalize_math(passage_text):
            return "covered", "formula anchor present (normalized)"
        return "partially_covered", f"{how}; the formula itself is not confirmed"
    pattern = {"definition": DEFINING, "theorem_statement": THEOREM, "worked_example": EXAMPLE,
               "exercise": EXERCISE, "notation_convention": NOTATION}.get(need_type)
    if pattern is not None:
        if need_type == "notation_convention" and not anchor:
            return "partially_covered", f"{how}; no symbol given to check"
        if pattern.search(passage_text):
            return "covered", f"{how} + {need_type} marker"
        return "partially_covered", f"{how}; no {need_type} marker"
    # method_guidance, prerequisite_explanation, course_policy: keyword presence only (low reliability)
    return "partially_covered", f"{how}; low-reliability need type"


def related(need: dict[str, Any], passage_text: str, concept_names: list[str] | None = None) -> bool:
    """Loose test used ONLY by the evidence gate: is the passage about this need at all?

    Much weaker than `rule_check` on purpose: the gate should empty a bundle only when every passage is clearly
    off-topic (e.g. no passage mentions "Laplace transform"), never when the passages are merely incomplete.
    """
    text_terms = set(terms(passage_text))
    if concept_names:
        return any(_mentions(name, text_terms) for name in concept_names)
    anchor = need.get("anchor")
    if anchor:
        return (anchor.lower() in passage_text.lower()
                or (is_formula(anchor) and normalize_math(anchor) in normalize_math(passage_text))
                or any(t in text_terms for t in terms(anchor) if t not in GENERIC_WORDS))
    wanted = target_terms(need, concept_names)
    return bool(wanted) and sum(t in text_terms for t in wanted) / len(wanted) >= 0.3


class EvidenceJudge(Protocol):
    def score(self, needs: list[dict[str, Any]], passage_texts: list[str]) -> list[dict[str, float]]:
        """For each passage, {need_id: probability that the passage states that need}."""


JUDGE_COVERED_AT = 0.7     # p >= 0.7 → covered; 0.35 <= p < 0.7 → partially_covered; else not_covered
JUDGE_PARTIAL_AT = 0.35


class JevEvidenceJudge:
    """Layer 3 with `JevClient`: one Jev call per passage, one yes/no question per need.

    Six passages → six calls, sent in parallel (`ask_many`). Off by default; run in shadow mode (logged next
    to the rules, no effect) until the labelled check (scripts/eval_evidence_judge.py) shows it is better.
    """

    def __init__(self, client: Any, *, covered_at: float = JUDGE_COVERED_AT, partial_at: float = JUDGE_PARTIAL_AT) -> None:
        self.client, self.covered_at, self.partial_at = client, covered_at, partial_at

    @staticmethod
    def questions(needs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {f"states_{n['need_id']}": {
            "type": "noul",
            "instructions": (f"Does `candidate_passage.text` itself state, in substance, what `evidence_needs.{n['need_id']}` "
                             "asks for?"),
            "criteria": {
                "true": ("The passage states the requested content itself: the formula written out, the definition or "
                         "theorem actually stated, the example actually worked, the list actually given."),
                "false": ("The passage only names the topic, gives a section or module title, a learning objective such as "
                          "'state and apply X', a 'difficult topics' bullet, or content about a different topic."),
            }} for n in needs}

    @staticmethod
    def state(needs: list[dict[str, Any]], text: str) -> dict[str, Any]:
        return {"evidence_needs": {n["need_id"]: {"type": n["need_type"], "description": n["description"],
                                                  "anchor": n.get("anchor", "")} for n in needs},
                "candidate_passage": {"text": text[:6000]}}

    def score(self, needs: list[dict[str, Any]], passage_texts: list[str]) -> list[dict[str, float]]:
        questions = self.questions(needs)
        answers = self.client.ask_many([(self.state(needs, t), questions) for t in passage_texts])
        return [{n["need_id"]: float(a[f"states_{n['need_id']}"]["noul"]) for n in needs} for a in answers]

    def coverage(self, p: float) -> str:
        return "covered" if p >= self.covered_at else "partially_covered" if p >= self.partial_at else "not_covered"


def judge_needs(judge: Any, needs: list[dict[str, Any]], passages: list[dict[str, Any]],
                texts: list[str]) -> list[NeedResult]:
    """Need coverage from the judge alone (best passage per need)."""
    scores = judge.score(needs, texts)
    order = {"not_covered": 0, "partially_covered": 1, "covered": 2}
    results = []
    for need in needs:
        nid = need["need_id"]
        levels = [(judge.coverage(s[nid]), s[nid], p["passage_id"]) for s, p in zip(scores, passages)]
        best = max((lv for lv, _, _ in levels), key=order.get, default="not_covered")
        ids = [pid for lv, _, pid in levels if lv == best and best != "not_covered"]
        top = max((sc for _, sc, _ in levels), default=0.0)
        results.append(NeedResult(nid, best, ids, "judge", f"max p={top:.2f}"))
    return results


def check_needs(needs: list[dict[str, Any]], passages: list[dict[str, Any]], *,
                pinned: dict[str, list[str]] | None = None, judge: Any = None,
                concept_names: list[str] | None = None) -> tuple[list[NeedResult], list[dict[str, Any]]]:
    """Layers 1-2 per need (pinned passages, then rules); best coverage over all passages.
    `judge` is accepted for backward compatibility and ignored: the service runs the judge (shadow / on)."""
    order = {"not_covered": 0, "partially_covered": 1, "covered": 2}
    results: list[NeedResult] = []
    for need in needs:
        nid = need["need_id"]
        pinned_ids = [pid for pid in (pinned or {}).get(nid, []) if any(p["passage_id"] == pid for p in passages)]
        if pinned_ids:
            results.append(NeedResult(nid, "covered", pinned_ids, "pinned", "human-confirmed passage_refs"))
            continue
        best, best_ids, detail = "not_covered", [], ""
        for p in passages:
            coverage, why = rule_check(need, p["passage_text"], concept_names)
            if order[coverage] > order[best]:
                best, best_ids, detail = coverage, [p["passage_id"]], why
            elif coverage == best and coverage != "not_covered":
                best_ids.append(p["passage_id"])
        results.append(NeedResult(nid, best, best_ids, f"rule:{need['need_type']}" if best != "not_covered" else "none", detail))
    return results, []
