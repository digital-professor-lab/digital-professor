"""Retrieval planning: "what does this turn need from the course, and where should we look?"

Instead of letting the tutoring model invent a free-text search sentence, every retrieval is driven by a
**RetrievalPlan**, a small validated record:

    concepts   which course concepts the turn is about      — chosen from the Course Context list only;
               ONE primary concept decides what counts as support, related ones are recorded only
    main_query the overall search text                      — Week 3 searches with it
    needs      1-4 typed needs, each with its own query     — what evidence the reply needs
    scope      the concepts' modules (recorded; narrowing is not enforced until Ovunc's concept→section map)
    repairs    every correction the code made to the model's proposal

How a plan is made (code first, model second, code last):

    1 concept linking (code)   bank question → its QuestionSchema concepts; otherwise match the turn's text
                               (student message + question + upstream understanding) against concept names,
                               slugs and key terms of the Course Context. Only clear, full-phrase matches are
                               auto-selected; vague text selects nothing.
    2 draft plan (code)        main query + one need per need type the grounding policy expects, with
                               templated queries from the concept names.
    3 refinement (model)       inside the tool call the model may rewrite queries, pick concepts ONLY from the
                               course list (enum), add or drop needs (max 4).
    4 validation + repair      enforce the schema and the lists; unknown concepts dropped, empty or missing
       (code)                  parts filled from the draft, limits applied; each fix recorded in `repairs`.

The same draft is used, without the model, when the system must retrieve on its own (prefetch).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .backends import terms
from .records import NEED_TYPES

PLAN_VERSION = "retrieval-plan@2"   # @2: one primary concept + related ones; explicit not_in_course
LINKING_METHOD = "lexical@1"
MAX_CONCEPTS = 3
MAX_RELATED = 2
NOT_IN_COURSE = "not_in_course"
# found: at least one primary concept · none_found: nothing named or chosen · not_in_course: the model says the
# course does not teach it (recorded only: the scope check and the evidence gate still decide what is returned)
CONCEPT_STATUS = ("found", "none_found", "not_in_course")
MAX_NEEDS = 4
DRAFT_NEEDS = 2              # the draft proposes the policy's first two need types; the model may add more
MAX_QUERY_CHARS = 200
COURSE_CONTEXT_DIR = Path(__file__).resolve().parents[1] / "data" / "course_context"

# Words that say nothing about WHICH concept: course-wide words, question words, formula tokens
LINK_STOP = {"calculu", "course", "material", "note", "say", "said", "actually", "official", "name", "answer", "wrong",
             "mark", "student", "differentiat", "explain", "mean", "sin", "cos", "tan", "sec", "dx", "dy", "du", "ln",
             "lim", "log", "exp", "sqrt", "pi", "inner", "one", "two", "get", "write", "wrote", "use", "used",
             "integral", "check", "state", "applied", "apply"}
AUTO_LINK_MIN = 3.0          # full-phrase match score needed to auto-select a concept
SINGLE_TERM_MIN_IDF = 2.5    # a one-word phrase auto-selects only if the word is distinctive (e.g. "continuity")
SECOND_CONCEPT_RATIO = 0.6   # a second concept is auto-selected only if close to the best one

# Which block types a need prefers once Ovunc's blocks[] exist (used for ranking, never as a hard filter)
PREFERRED_BLOCKS = {
    "definition": ["definition"], "theorem_statement": ["theorem"], "formula_statement": ["definition", "theorem"],
    "worked_example": ["example"], "exercise": ["exercise"], "method_guidance": ["remark", "example"],
    "prerequisite_explanation": ["definition", "remark"], "notation_convention": ["definition", "remark"],
    "course_policy": [],
}
QUERY_TEMPLATES = {
    "definition": "definition of {name}", "theorem_statement": "statement of {name}",
    "formula_statement": "formula for {name}", "worked_example": "worked example using {name}",
    "exercise": "practice exercise on {name}", "method_guidance": "how to apply {name}",
    "prerequisite_explanation": "prerequisites needed for {name}", "notation_convention": "notation used for {name}",
    "course_policy": "course coverage of {name}",
}

# JSON Schema of a RetrievalPlan (draft 2020-12). Documented contract; `validate_plan` enforces it in code.
PLAN_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RetrievalPlan", "type": "object", "additionalProperties": False,
    "required": ["plan_version", "course_id", "concepts", "concept_status", "main_query", "needs", "scope", "origin",
                 "repairs"],
    "properties": {
        "plan_version": {"const": PLAN_VERSION},
        "course_id": {"type": "string", "minLength": 1},
        "concepts": {"type": "array", "maxItems": MAX_CONCEPTS, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["concept_id", "name", "module_id", "source", "role"],
            "properties": {"concept_id": {"type": "string"}, "name": {"type": "string"}, "module_id": {"type": "string"},
                           "source": {"enum": ["question_schema", "linked", "model"]},
                           "role": {"enum": ["primary", "related"]}}}},
        "concept_status": {"enum": list(CONCEPT_STATUS)},
        "main_query": {"type": "string", "minLength": 3, "maxLength": 300},
        "needs": {"type": "array", "minItems": 1, "maxItems": MAX_NEEDS, "items": {
            "type": "object", "additionalProperties": False, "required": ["need_id", "need_type", "query", "preferred_blocks"],
            "properties": {"need_id": {"pattern": "^n[1-4]$"}, "need_type": {"enum": list(NEED_TYPES)},
                           "query": {"type": "string", "minLength": 3, "maxLength": MAX_QUERY_CHARS},
                           "anchor": {"type": "string", "maxLength": 80}, "concept_id": {"type": "string"},
                           "preferred_blocks": {"type": "array", "items": {"type": "string"}}}}},
        "scope": {"type": "object", "required": ["module_ids", "narrowing"], "properties": {
            "module_ids": {"type": "array", "items": {"type": "string"}},
            "narrowing": {"enum": ["not_enforced", "module", "section"]}, "note": {"type": "string"}}},
        "origin": {"enum": ["draft", "model"]},
        "repairs": {"type": "array", "items": {"type": "object", "required": ["field", "code"]}},
        "linking": {"type": "object"},
    },
}


# ---------------------------------------------------------------------------
# Course concepts (controlled vocabulary from the Course Context)
# ---------------------------------------------------------------------------
def _link_terms(text: str) -> set[str]:
    return {t for t in terms(text) if not t.isdigit() and len(t) >= 3 and t not in LINK_STOP}


def _head(key_definition: str) -> str:
    """The name part of a key definition: 'Chain rule: ...' → 'Chain rule'; 'Leibniz form dy/dx = ...' → 'Leibniz form dy/dx'."""
    head = str(key_definition).split(":")[0]
    return re.split(r"\s\(|\sas\s|\s=\s", head)[0].strip()


@dataclass
class Concept:
    concept_id: str
    name: str
    module_id: str
    module_title: str
    phrases: list[str] = field(default_factory=list)


@dataclass
class ConceptCatalog:
    course_id: str
    course_title: str
    concepts: dict[str, Concept]
    source: str
    _idf: dict[str, float] = field(default_factory=dict, repr=False)

    @classmethod
    def from_course_context(cls, data: dict[str, Any], source: str = "") -> "ConceptCatalog":
        modules = {m["id"]: m.get("title", m["id"]) for m in data.get("Module", [])}
        concepts = {}
        for c in data.get("Concept", []):
            slug = c["id"].split(".")[-1].replace("-", " ")
            phrases = [c["name"], slug] + [_head(k) for k in c.get("key_definitions", [])]
            concepts[c["id"]] = Concept(c["id"], c["name"], c.get("module_id", ""), modules.get(c.get("module_id", ""), ""),
                                        [p for p in dict.fromkeys(phrases) if _link_terms(p)])
        catalog = cls(data["Course"]["id"], data["Course"].get("title", data["Course"]["id"]), concepts, source)
        df: Counter[str] = Counter()
        for concept in concepts.values():
            df.update({t for p in concept.phrases for t in _link_terms(p)})
        catalog._idf = {t: math.log(1 + len(concepts) / n) for t, n in df.items()}
        return catalog

    @classmethod
    def for_course(cls, course_id: str, folder: Path = COURSE_CONTEXT_DIR) -> "ConceptCatalog | None":
        path = Path(folder) / f"{course_id}.course-context.json"
        if not path.exists():
            return None
        return cls.from_course_context(json.loads(path.read_text(encoding="utf-8")), source=path.name)

    def link(self, text: str, limit: int = 8) -> list[dict[str, Any]]:
        """Rank concepts by how clearly the text names them. Each hit: concept_id, score, matched phrase, full."""
        text_terms = _link_terms(text)
        hits = []
        for concept in self.concepts.values():
            best: tuple[float, str, bool] = (0.0, "", False)
            for phrase in concept.phrases:
                phrase_terms = _link_terms(phrase)
                matched = phrase_terms & text_terms
                if not matched or len(matched) / len(phrase_terms) < 0.5:
                    continue
                full = phrase_terms <= text_terms
                score = sum(self._idf.get(t, 0.0) for t in matched) * (1.5 if full else 1.0)
                if len(phrase_terms) == 1 and full and self._idf.get(next(iter(phrase_terms)), 0.0) < SINGLE_TERM_MIN_IDF:
                    full = False   # a single common word ("derivative") is not a clear mention
                if score > best[0]:
                    best = (round(score, 3), phrase, full)
            if best[0] > 0:
                hits.append({"concept_id": concept.concept_id, "score": best[0], "matched": best[1], "full": best[2]})
        hits.sort(key=lambda h: (-h["score"], h["concept_id"]))
        return hits[:limit]

    def auto_select(self, hits: list[dict[str, Any]]) -> list[str]:
        clear = [h for h in hits if h["full"] and h["score"] >= AUTO_LINK_MIN]
        if not clear:
            return []
        top = clear[0]["score"]
        return [h["concept_id"] for h in clear if h["score"] >= SECOND_CONCEPT_RATIO * top][:2]

    def short_name(self, concept_id: str) -> str:
        """Search-friendly concept name: 'The chain rule' → 'chain rule'."""
        if concept_id not in self.concepts:
            return concept_id
        name = self.concepts[concept_id].name
        return re.sub(r"^(the|a|an)\s+", "", name, flags=re.I)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------
class RetrievalPlanner:
    def __init__(self, catalogs: dict[str, ConceptCatalog] | None = None) -> None:
        self.catalogs = catalogs or {}

    @classmethod
    def from_folder(cls, course_ids: list[str], folder: Path = COURSE_CONTEXT_DIR) -> "RetrievalPlanner":
        catalogs = {}
        for course_id in course_ids:
            catalog = ConceptCatalog.for_course(course_id, folder)
            if catalog is not None:
                catalogs[course_id] = catalog
        return cls(catalogs)

    def catalog(self, course_id: str) -> ConceptCatalog | None:
        return self.catalogs.get(course_id)

    def concept_menu(self, course_id: str, hits: list[dict[str, Any]] | None = None, limit: int = 40) -> list[str]:
        """Concept IDs the model may choose from: the whole course list when small, else linked hits first."""
        catalog = self.catalog(course_id)
        if catalog is None:
            return []
        ids = list(catalog.concepts)
        if len(ids) <= limit:
            return ids
        first = [h["concept_id"] for h in (hits or [])]
        return list(dict.fromkeys(first + ids))[:limit]

    # -- stage 1 + 2 ---------------------------------------------------------
    def draft(self, ctx: Any, decision: Any) -> dict[str, Any]:
        catalog = self.catalog(ctx.course_id)
        text = " ".join(x for x in (ctx.student_message, ctx.question_prompt, ctx.intent_summary) if x)
        hits = catalog.link(text) if catalog else []
        concepts: list[dict[str, Any]] = []
        if catalog:
            for cid in ctx.concept_ids or []:
                if cid in catalog.concepts:
                    concepts.append(self._concept(catalog, cid, "question_schema", "primary"))
            if not concepts:
                concepts = [self._concept(catalog, cid, "linked", "primary" if i == 0 else "related")
                            for i, cid in enumerate(catalog.auto_select(hits))]
        primary = [c for c in concepts if c["role"] == "primary"]
        names = [c["name"] for c in primary] or list(ctx.concept_names or [])
        short = [catalog.short_name(c["concept_id"]) for c in primary] if catalog and primary else names
        topic = ", ".join(short)
        if topic and ctx.intent_summary:
            main_query = f"{topic}: {ctx.intent_summary}"
        else:
            main_query = topic or ctx.intent_summary or ctx.question_prompt or ""
        needs = []
        if short:
            for i, need_type in enumerate(list(getattr(decision, "need_types", ()))[:DRAFT_NEEDS], start=1):
                need = {"need_id": f"n{i}", "need_type": need_type,
                        "query": QUERY_TEMPLATES[need_type].format(name=" and ".join(short))[:MAX_QUERY_CHARS],
                        "preferred_blocks": PREFERRED_BLOCKS[need_type]}
                if need_type in ("definition", "theorem_statement") and len(short) == 1:
                    need["anchor"] = short[0]
                if primary:
                    need["concept_id"] = primary[0]["concept_id"]
                needs.append(need)
        return {"plan_version": PLAN_VERSION, "course_id": ctx.course_id, "concepts": concepts,
                "concept_status": "found" if primary else "none_found",
                "main_query": " ".join(main_query.split())[:300], "needs": needs, "scope": self._scope(concepts),
                "origin": "draft", "repairs": [],
                "linking": {"method": LINKING_METHOD, "candidates": hits[:5],
                            "course_context": catalog.source if catalog else None}}

    # -- stage 4 -------------------------------------------------------------
    def finalize(self, args: dict[str, Any], draft: dict[str, Any], ctx: Any) -> dict[str, Any]:
        """Model proposal (tool arguments) + draft → validated plan. Never raises on bad content; repairs it."""
        catalog = self.catalog(ctx.course_id)
        repairs: list[dict[str, str]] = []

        def repair(field_name: str, code: str, detail: str = "") -> None:
            repairs.append({"field": field_name, "code": code, **({"detail": detail[:160]} if detail else {})})

        # concepts: QuestionSchema concepts are fixed (primary); the model picks ONE primary concept and optional
        # related ones, from the course list only. A model "not_in_course" overrides code linking, never QuestionSchema.
        concepts = [c for c in draft["concepts"] if c["source"] == "question_schema"]
        primary_arg, related_arg = args.get("concept_id"), args.get("related_concept_ids")
        legacy = args.get("concept_ids")                       # retrieval-plan@1 callers: first = primary
        if primary_arg is None and isinstance(legacy, list) and legacy:
            primary_arg, related_arg = legacy[0], list(legacy[1:]) + list(related_arg or [])
        if related_arg is not None and not isinstance(related_arg, list):
            repair("related_concept_ids", "not_a_list")
            related_arg = None
        said_not_in_course = primary_arg == NOT_IN_COURSE

        def known_concept(field_name: str, cid: Any) -> bool:
            if catalog is not None and cid in catalog.concepts:
                return True
            repair(field_name, "unknown_concept_dropped", str(cid))
            return False

        has = lambda cid: any(c["concept_id"] == cid for c in concepts)  # noqa: E731
        if primary_arg is not None and not said_not_in_course and known_concept("concept_id", primary_arg) \
                and not has(primary_arg):
            # with a QuestionSchema concept the model's choice becomes related; otherwise it is the primary
            role = "related" if concepts else "primary"
            if role == "related":
                repair("concept_id", "question_schema_kept_primary", str(primary_arg))
            concepts.append(self._concept(catalog, primary_arg, "model", role))
        for cid in related_arg or []:
            if cid == NOT_IN_COURSE or not known_concept("related_concept_ids", cid) or has(cid):
                continue
            if sum(c["role"] == "related" for c in concepts) >= MAX_RELATED:
                repair("related_concept_ids", "truncated", f"kept {MAX_RELATED}")
                break
            concepts.append(self._concept(catalog, cid, "model", "related"))
        if said_not_in_course and concepts and concepts[0]["source"] == "question_schema":
            repair("concept_id", "not_in_course_ignored", "the bank question's concepts are kept")
            said_not_in_course = False
        if not said_not_in_course and not any(c["role"] == "primary" for c in concepts):
            linked = [dict(c) for c in draft["concepts"]]
            if linked:
                if primary_arg is not None:
                    repair("concept_id", "concepts_from_draft")
                # draft concepts become primary/related as drafted; model related ones stay related
                concepts = linked + [c for c in concepts if not any(c["concept_id"] == l["concept_id"] for l in linked)]
            elif concepts:   # only related concepts proposed: promote the first
                concepts[0]["role"] = "primary"
                repair("related_concept_ids", "first_related_promoted_to_primary")
        if len(concepts) > MAX_CONCEPTS:
            repair("concepts", "truncated", f"kept {MAX_CONCEPTS}")
            concepts = concepts[:MAX_CONCEPTS]
        primaries = [c["concept_id"] for c in concepts if c["role"] == "primary"]
        status = "not_in_course" if said_not_in_course else ("found" if primaries else "none_found")
        known = {c["concept_id"] for c in concepts}

        main_query = " ".join(str(args.get("query") or "").split())
        if len(main_query) < 3:
            main_query = draft["main_query"]
            repair("query", "main_query_from_draft")
        elif len(main_query) > 300:
            main_query = main_query[:300]
            repair("query", "truncated")

        needs = []
        raw_needs = args.get("evidence_needs") if isinstance(args.get("evidence_needs"), list) else []
        for i, raw in enumerate(raw_needs):
            if not isinstance(raw, dict) or raw.get("need_type") not in NEED_TYPES:
                repair(f"evidence_needs[{i}]", "invalid_need_dropped")
                continue
            query = " ".join(str(raw.get("description") or raw.get("query") or "").split())
            if len(query) < 3:
                repair(f"evidence_needs[{i}].description", "empty_need_dropped")
                continue
            if len(query) > MAX_QUERY_CHARS:
                query = query[:MAX_QUERY_CHARS]
                repair(f"evidence_needs[{i}].description", "truncated")
            if any(n["query"].lower() == query.lower() for n in needs):
                repair(f"evidence_needs[{i}]", "duplicate_dropped")
                continue
            need = {"need_type": raw["need_type"], "query": query, "preferred_blocks": PREFERRED_BLOCKS[raw["need_type"]]}
            anchor = raw.get("anchor")
            if isinstance(anchor, str) and anchor.strip():
                need["anchor"] = anchor.strip()[:80]
            concept_id = raw.get("concept_id")
            if concept_id is not None:
                if concept_id in known:
                    need["concept_id"] = concept_id
                else:
                    repair(f"evidence_needs[{i}].concept_id", "not_a_plan_concept_dropped", str(concept_id))
            if "concept_id" not in need and len(primaries) == 1:
                need["concept_id"] = primaries[0]
            needs.append(need)
        if not needs:
            needs = [dict(n) for n in draft["needs"]]
            repair("evidence_needs", "needs_from_draft")
        if len(needs) > MAX_NEEDS:
            needs = needs[:MAX_NEEDS]
            repair("evidence_needs", "truncated", f"kept {MAX_NEEDS}")
        for i, need in enumerate(needs, start=1):
            need["need_id"] = f"n{i}"
        plan = {"plan_version": PLAN_VERSION, "course_id": ctx.course_id, "concepts": concepts,
                "concept_status": status, "main_query": main_query,
                "needs": [{k: n[k] for k in ("need_id", "need_type", "query", "anchor", "concept_id", "preferred_blocks") if k in n}
                          for n in needs],
                "scope": self._scope(concepts), "origin": "model", "repairs": repairs, "linking": draft.get("linking", {})}
        return plan

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _concept(catalog: ConceptCatalog, concept_id: str, source: str, role: str = "primary") -> dict[str, Any]:
        c = catalog.concepts[concept_id]
        return {"concept_id": c.concept_id, "name": c.name, "module_id": c.module_id, "source": source, "role": role}

    @staticmethod
    def _scope(concepts: list[dict[str, Any]]) -> dict[str, Any]:
        return {"module_ids": sorted({c["module_id"] for c in concepts if c.get("module_id")}),
                "narrowing": "not_enforced",
                "note": "Recorded only: the Week 3 index has no concept→section map yet, so search covers the whole "
                        "course and ranking does the locating. Narrowing and widening start once Ovunc's ingestion "
                        "JSON maps concepts to sections."}


def plan_is_usable(plan: dict[str, Any]) -> bool:
    return bool(plan.get("needs")) and len(plan.get("main_query", "")) >= 3


def validate_plan(plan: dict[str, Any]) -> list[str]:
    """Code check of PLAN_SCHEMA (no third-party validator needed). Returns a list of problems."""
    problems = []
    props = PLAN_SCHEMA["properties"]
    for key in PLAN_SCHEMA["required"]:
        if key not in plan:
            problems.append(f"missing {key}")
    for key in plan:
        if key not in props:
            problems.append(f"unknown field {key}")
    if plan.get("plan_version") != PLAN_VERSION:
        problems.append("plan_version")
    if not 3 <= len(plan.get("main_query", "")) <= 300:
        problems.append("main_query length")
    concepts = plan.get("concepts", [])
    if len(concepts) > MAX_CONCEPTS:
        problems.append("too many concepts")
    for c in concepts:
        if c.get("source") not in ("question_schema", "linked", "model"):
            problems.append(f"concept source {c.get('source')}")
        if c.get("role") not in ("primary", "related"):
            problems.append(f"concept role {c.get('role')}")
    has_primary = any(c.get("role") == "primary" for c in concepts)
    if plan.get("concept_status") not in CONCEPT_STATUS:
        problems.append("concept_status")
    elif (plan["concept_status"] == "found") != has_primary:
        problems.append("concept_status does not match the primary concepts")
    needs = plan.get("needs", [])
    if not 1 <= len(needs) <= MAX_NEEDS:
        problems.append("needs count")
    for i, n in enumerate(needs, start=1):
        if n.get("need_id") != f"n{i}":
            problems.append(f"need_id {n.get('need_id')}")
        if n.get("need_type") not in NEED_TYPES:
            problems.append(f"need_type {n.get('need_type')}")
        if not 3 <= len(n.get("query", "")) <= MAX_QUERY_CHARS:
            problems.append(f"need {i} query length")
        if "concept_id" in n and n["concept_id"] not in {c["concept_id"] for c in concepts}:
            problems.append(f"need {i} concept not in plan")
    if plan.get("origin") not in ("draft", "model"):
        problems.append("origin")
    if plan.get("scope", {}).get("narrowing") not in ("not_enforced", "module", "section"):
        problems.append("scope.narrowing")
    return problems


def plan_to_request(plan: dict[str, Any], ctx: Any, *, purpose: str, contains_student_wording: bool = False,
                    top_k: int | None = None, producer: str = "tutoring-engine") -> dict[str, Any]:
    """A validated plan → canonical RetrievalRequest (needs carry the plan's per-need queries)."""
    from .tool_schema import build_request
    args = {"query": plan["main_query"], "purpose": purpose,
            "evidence_needs": [{"need_type": n["need_type"], "description": n["query"],
                                **({"anchor": n["anchor"]} if n.get("anchor") else {})} for n in plan["needs"]],
            "contains_student_wording": contains_student_wording}
    # only PRIMARY concepts go into the request (they decide what counts as support); related ones stay in the plan
    primary = [c for c in plan["concepts"] if c.get("role", "primary") == "primary"]
    if plan.get("concept_status") == "not_in_course":
        planned_ctx = replace(ctx, concept_ids=[], concept_names=[])
    else:
        planned_ctx = replace(ctx, concept_ids=[c["concept_id"] for c in primary] or list(ctx.concept_ids),
                              concept_names=[c["name"] for c in primary] or list(ctx.concept_names))
    request = build_request(args, planned_ctx, top_k=top_k, producer=producer)
    request["retrieval_plan"] = plan
    return request
