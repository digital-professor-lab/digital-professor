"""Local fixture search: runs the retrieval logic with no Week 3 code, database, encoder or network.

This is a test stand-in. It lets the tests, the smoke check and a new contributor exercise the service, the
planner, the records and a stubbed turn from this folder alone. It ranks passages by simple term overlap,
so its results say nothing about Week 3's search quality and must not be used for benchmarks.

The corpus in data/fixture_corpus/ is a small subset of the Week 3 catalog, written by
scripts/build_fixture_corpus.py from the pinned Week 3 commit.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from .backends import Catalog, terms

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "data" / "fixture_corpus"

_SCOPE_RULES = (
    (re.compile(r"calculus\s+(ii|2|two)\b", re.I), "not_found", "outside_selected_scope", "another_course",
     "The request names another course."),
    (re.compile(r"second\s+semester", re.I), "needs_clarification", "ambiguous_scope", "ambiguous_course_part",
     "The request could mean a part of the sequence this course may not cover."),
    (re.compile(r"\b(instructor|lecture)\b.*\b(say|said)\b|\b(say|said)\b.*\b(instructor|lecture)\b", re.I),
     "not_found", "source_unavailable", "no_lecture_record", "No lecture record is available."),
)


def fixture_assess(text: str) -> dict[str, Any]:
    """A small stand-in for Week 3's scope rules, covering the three outcomes the service must handle."""
    for pattern, decision, category, reason_code, explanation in _SCOPE_RULES:
        if pattern.search(text):
            return {"decision": decision, "category": category, "reason_code": reason_code, "explanation": explanation}
    return {"decision": "retrieve", "category": "within_selected_scope", "reason_code": None,
            "explanation": "No fixture scope rule matched."}


def fixture_scope_checker(text: str, *, course_id: str, source_types: set[str], policy: Any) -> dict[str, Any]:
    return fixture_assess(text)


class LocalFixtureBackend:
    """Deterministic term-overlap search over the fixture catalog. Same report shape as Week 3's search."""

    name = "local_fixture"
    selection = "local_fixture"
    semantic_available = False

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.index = [(row["passage_id"], row["document_id"], set(terms(row.get("readable_text") or row["raw_latex"])))
                      for row in catalog.passages.values()]

    def query_facets(self, question: str) -> list[str]:
        return []

    def run(self, question: str, facets: list[str], *, course_id: str, include_unconfirmed: bool = False,
            include_outside_course: bool = False, top_k: int | None = 6, context_chars: int | None = 12000,
            **options: Any) -> dict[str, Any]:
        scope = fixture_assess(question)
        base = {"question": question, "scope_assessment": scope, "selection_skip_reasons": {},
                "channel_candidate_counts": {"local_fixture": 0}, "results": []}
        if scope["decision"] != "retrieve":
            return {**base, "status": scope["decision"]}
        wanted = set(terms(question))
        needed = max(1, math.ceil(0.6 * len(wanted)))
        documents = {d["document_id"] for d in self.catalog.documents_for(course_id)}
        scored = sorted(((len(wanted & words), passage_id) for passage_id, document, words in self.index
                         if document in documents and len(wanted & words) >= needed),
                        key=lambda hit: (-hit[0], hit[1]))
        results = [{"passage_id": passage_id, "selection_reason": "local_fixture_term_overlap", "signals": ["local_fixture"]}
                   for _, passage_id in scored[:top_k or 6]]
        return {**base, "status": "found" if results else "not_found", "results": results,
                "channel_candidate_counts": {"local_fixture": len(scored)}}

    def close(self) -> None:
        pass
