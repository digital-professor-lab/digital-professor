"""Turn-time retrieval (T3): RetrievalRequest → GroundingBundle or RetrievalStop.

Flow (rag-retrieval.md §7.1):
  1 validate → 2 preflight (A: readiness/inventory/provenance; B: free-text scope check, only for
  student wording) → 3 query plan → 4-5 candidates and selection by Week 3's production code, unchanged
  → 6 location → 7 evidence check per need (annotates coverage) → status.

Baseline = Week 3. Search and selection are always Week 3's `search_many` code with its thresholds (top_k 6,
40 candidates per channel, 12,000 characters, soft limit 4 per file, Week 3 sub-question rules). Two switches:
  facet_source="evidence_needs"  use the model's typed needs as sub-questions instead of Week 3's regex split (off)
  evidence_gate                  return no_support_found when no returned passage supports any stated need.
                                 On for tutoring turns; RetrievalOptions.week3_parity() turns it off so the bundle
                                 equals Week 3's output passage for passage.

The service never decides *whether* to retrieve (that is the grounding policy) and never judges
the student. It only answers "what do the course materials say about these needs?".
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .backends import PILOT_SCOPE, BackendUnavailable, Catalog, SearchBackend
from .evidence import EvidenceJudge, check_needs, related
from .records import (NEED_TYPES, PURPOSES, check_bundle_invariants, grounding_bundle, passage_identity,
                      retrieval_stop, warning)

LEGACY_SOURCE_LABELS = {"syllabus": "AI-prepared syllabus course map (unverified)",
                        "context": "AI-prepared course context (unverified)",
                        "textbook_reference": "AI-prepared textbook breakdown (unverified)"}


@dataclass
class CoursePolicy:
    """Per-course retrieval policy (rag-retrieval.md §6.5), set at provisioning."""

    course_id: str
    policy_version: str
    retrieval_snapshot_id: str
    published: bool = True
    allow_unverified_sources: str = "none"            # none / development / pilot
    allowed_scopes: tuple[str, ...] = (PILOT_SCOPE,)  # Week 3 scope labels the index may serve
    allow_legacy_locators: bool = False               # dev only: cite LaTeX source lines, no page/highlight
    # Source types that are references, not evidence (rag-retrieval.md §6.4, example a): a syllabus lists topics
    # but does not state them. Their passages are never returned as support; a course with nothing else
    # returns no_support_found + reference_only + no_ingested_sources. The development policy keeps the
    # AI-prepared syllabus citable so the Week 3 alignment stays passage-for-passage.
    reference_only_source_types: tuple[str, ...] = ("syllabus",)
    # Week 3 production defaults (Retriever.search_many)
    default_top_k: int = 6
    max_passage_chars: int = 12000
    max_per_document: int = 4
    document_limit_mode: str = "soft"
    candidate_limit: int = 40
    retired_snapshots: tuple[str, ...] = ()
    # Tutoring-side settings (used by agent_loop; rag-retrieval.md §2.2 fallbacks, §6.5, Q15)
    allow_general_knowledge: bool = False      # may the tutor add a short, labelled explanation the course lacks?
    external_processing_allowed: bool = False  # may student text go to an external model (e.g. Jev)?


def development_policy(course_id: str = "calc1") -> CoursePolicy:
    """The current AI-breakdown corpus, served in development mode only (example h)."""
    return CoursePolicy(course_id=course_id, policy_version=f"{course_id}-retrieval-policy@dev-0.1",
                        retrieval_snapshot_id=f"snap.{course_id}.dev-ai-breakdown.1",
                        allow_unverified_sources="development", allow_legacy_locators=True,
                        reference_only_source_types=(),
                        allow_general_knowledge=True,   # the dev corpus is topic lists only; production default: off
                        # dev data is synthetic, so Jev may see it. For real students this is a team decision (Q15).
                        external_processing_allowed=True)


@dataclass(frozen=True)
class RetrievalOptions:
    """Switches on top of the Week 3 baseline. Defaults reproduce Week 3 exactly."""

    facet_source: str = "week3"      # "week3" (query_facets regex, as Week 3) or "evidence_needs"
    evidence_gate: bool = True       # no passage supports any need → no_support_found (spec §7.9)
    judge_mode: str = "off"          # evidence judge (spec §6.5 off / shadow / on): shadow = logged only

    @classmethod
    def week3_parity(cls) -> "RetrievalOptions":
        """Bundle passages identical to Week 3's output (for the alignment check)."""
        return cls(facet_source="week3", evidence_gate=False)

    def describe(self) -> dict[str, Any]:
        return {"facet_source": self.facet_source, "evidence_gate": self.evidence_gate, "judge_mode": self.judge_mode,
                "week3_retrieval": self.facet_source == "week3",
                "week3_parity": self == RetrievalOptions.week3_parity()}


ScopeChecker = Callable[..., dict[str, Any]]


def default_scope_checker(root: Path) -> ScopeChecker | None:
    """Week 3's explainable regex policy (request_policy.assess_request), reused as policy data."""
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        from digital_professor.retrieval.request_policy import assess_request  # type: ignore
    except ImportError:
        return None

    def check(text: str, *, course_id: str, source_types: set[str], policy: CoursePolicy) -> dict[str, Any]:
        return assess_request(text, include_unconfirmed="second_semester_scope_unconfirmed" in policy.allowed_scopes,
                              include_outside_course=any(s.startswith("outside_pilot") for s in policy.allowed_scopes),
                              source_types=source_types, course_id=course_id).to_dict()
    return check


@dataclass
class TurnRegistry:
    """Bundles issued per (session, turn); used by the T4 citation check and passage resolution."""

    bundles: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, bundle: dict[str, Any]) -> None:
        self.bundles[bundle["grounding_bundle_id"]] = bundle

    def for_turn(self, session_id: str | None, turn_id: str) -> list[dict[str, Any]]:
        return [b for b in self.bundles.values() if b.get("turn_id") == turn_id and b.get("session_id") == session_id]

    def resolve(self, passage_id: str) -> dict[str, Any] | None:
        for b in self.bundles.values():
            for p in b["passages"]:
                if p["passage_id"] == passage_id:
                    return p
        return None


class RetrievalService:
    def __init__(self, backend: SearchBackend, catalog: Catalog, policies: dict[str, CoursePolicy], *,
                 scope_checker: ScopeChecker | None = None, model_scope_checker: ScopeChecker | None = None,
                 judge: EvidenceJudge | None = None, options: RetrievalOptions | None = None,
                 planner: Any = None) -> None:
        self.planner = planner          # RetrievalPlanner: concept list + plan drafting/validation for turns
        self.options = options or RetrievalOptions()
        if self.options.facet_source not in ("week3", "evidence_needs"):
            raise ValueError("facet_source must be 'week3' or 'evidence_needs'")
        if self.options.judge_mode not in ("off", "shadow", "on"):
            raise ValueError("judge_mode must be off, shadow or on")
        self.backend, self.catalog, self.policies = backend, catalog, policies
        self.scope_checker, self.model_scope_checker = scope_checker, model_scope_checker
        self.judge = judge
        self.registry = TurnRegistry()
        self.last_report: dict[str, Any] = {}

    # ------------------------------------------------------------------ public
    def warm_up(self) -> float:
        """Load the query encoders at startup when the backend supports it; returns seconds spent."""
        started = time.perf_counter()
        warm = getattr(self.backend, "warm_up", None)
        if callable(warm):
            warm()
        return round(time.perf_counter() - started, 2)

    def handle(self, request: dict[str, Any], *, pinned: dict[str, list[str]] | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        report: dict[str, Any] = {"retrieval_request_id": request.get("retrieval_request_id"), "timings_ms": {}}
        self.last_report = report
        policy = self.policies.get(request.get("course_id", ""))
        policy_version = policy.policy_version if policy else "none"

        # 1 validate
        errors = self._validate(request)
        if errors:
            return self._finish(retrieval_stop(request=request, stop_reason="invalid_request",
                                               reason_code=errors[0]["code"], retryable=False,
                                               policy_version=policy_version, validation_errors=errors),
                                report, started)
        assert policy is not None

        # 2A preflight: readiness, snapshot, eligible inventory
        if not policy.published:
            return self._finish(retrieval_stop(request=request, stop_reason="course_not_ready", reason_code="course_not_ready",
                                               retryable=True, policy_version=policy_version), report, started)
        pinned_snapshot = request.get("retrieval_snapshot_id")
        if pinned_snapshot and pinned_snapshot != policy.retrieval_snapshot_id:
            code = "version_mismatch"
            return self._finish(retrieval_stop(request=request, stop_reason="version_mismatch", reason_code=code,
                                               retryable=False, policy_version=policy_version), report, started)
        documents = self._eligible_documents(policy)
        report["preflight"] = {"eligible_documents": [d["document_id"] for d in documents], "policy_version": policy_version}
        if not documents:
            return self._finish(self._empty(request, policy, "no_eligible_sources",
                                            "No document is eligible under the course provenance policy "
                                            f"(allow_unverified_sources={policy.allow_unverified_sources})."), report, started)
        citable = [d for d in documents if d.get("source_type") not in policy.reference_only_source_types]
        if not citable:
            # example a: only reference documents (e.g. the syllabus) and no ingested course text
            types = sorted({d.get("source_type", "?") for d in documents})
            bundle = grounding_bundle(
                request=request, retrieval_status="no_support_found", passages=[],
                warnings=[warning("reference_only", f"Only reference documents are available ({', '.join(types)}); "
                                  "they name topics but are not cited as evidence."),
                          warning("no_ingested_sources", "No ingested course text (lecture notes, textbook) "
                                  "is available for this course yet.")],
                snapshot_id=policy.retrieval_snapshot_id)
            return self._finish(bundle, report, started)
        if re.search(r"[぀-ヿ㐀-鿿가-힯]", request["query"]):
            return self._finish(self._empty(request, policy, "query_language_unsupported",
                                            "V1 retrieval is English-only."), report, started)

        # 2B free-text scope check on the student's own words: the turn's student message (scope_check_text)
        # whenever the system supplies it, and the query itself when it copies student wording
        texts = []
        if request.get("scope_check_text"):
            texts.append(("student_message", request["scope_check_text"]))
        if request.get("query_origin") == "student_text":
            texts.append(("query", request["query"]))
        for label, text in texts:
            outcome = self._scope_check(request, policy, documents, report, text=text, label=label)
            if outcome is not None:
                return self._finish(outcome, report, started)

        # 3 query plan: Week 3's own decomposition (query_facets) by default, exactly as Week 3 search_many;
        # with facet_source="evidence_needs", one sub-question per distinct typed need.
        question, facets, facet_source = self._plan(request)
        report["query_plan"] = {"question": question, "facets": facets, "facet_source": facet_source}
        plan = request.get("retrieval_plan")
        if plan:
            from .planner import validate_plan
            report["retrieval_plan"] = {"origin": plan.get("origin"), "concepts": [(c["concept_id"], c.get("role")) for c in plan.get("concepts", [])],
                                        "concept_status": plan.get("concept_status"),
                                        "needs": [n["query"] for n in plan.get("needs", [])], "scope": plan.get("scope"),
                                        "repairs": plan.get("repairs", []), "schema_problems": validate_plan(plan)}

        # 4-5 candidates + selection: Week 3 production code, unchanged (see backends.py)
        t0 = time.perf_counter()
        try:
            week3 = self.backend.run(
                question, facets, course_id=request["course_id"],
                include_unconfirmed="second_semester_scope_unconfirmed" in policy.allowed_scopes,
                include_outside_course=any(s.startswith("outside_pilot") for s in policy.allowed_scopes),
                top_k=request.get("top_k") or policy.default_top_k,
                context_chars=request.get("max_passage_chars") or policy.max_passage_chars,
                max_per_document=policy.max_per_document, document_limit_mode=policy.document_limit_mode,
                candidate_limit=policy.candidate_limit)
        except BackendUnavailable as error:
            bundle = grounding_bundle(request=request, retrieval_status="failed", passages=[],
                                      warnings=[warning(error.code, str(error)[:300], retryable=True)],
                                      snapshot_id=policy.retrieval_snapshot_id)
            return self._finish(bundle, report, started)
        except ValueError as error:  # Week 3 input validation (e.g. unknown course in the index)
            return self._finish(retrieval_stop(request=request, stop_reason="invalid_request", reason_code="invalid_request",
                                               retryable=False, policy_version=policy_version,
                                               validation_errors=[{"field": "query", "code": "invalid_request",
                                                                   "message": str(error)[:300]}]), report, started)
        report["timings_ms"]["week3_search"] = round((time.perf_counter() - t0) * 1000, 1)
        report["week3"] = {k: v for k, v in week3.items() if k not in ("context", "results")}
        report["week3"]["selected"] = [r["passage_id"] for r in week3["results"]]

        # Week 3's own scope rules ran on the query text as well (same behaviour as Week 3)
        if week3["status"] == "needs_clarification":
            sa = week3.get("scope_assessment", {})
            return self._finish(retrieval_stop(request=request, stop_reason="needs_clarification",
                                               reason_code=sa.get("category", "ambiguous_scope"), retryable=True,
                                               policy_version=policy_version,
                                               clarification_prompt_hint=sa.get("explanation")), report, started)
        sa = week3.get("scope_assessment") or {}
        if week3["status"] == "not_found" and sa.get("decision") not in (None, "retrieve"):
            code = "source_class_unavailable" if sa.get("category") == "source_unavailable" else "excluded_scope"
            return self._finish(self._empty(request, policy, code, f"{sa.get('reason_code')}: {sa.get('explanation', '')}"),
                                report, started)

        # 6 location: Week 3 order is kept as the retrieval rank. Reference-only sources (production: the
        # syllabus) are left out; the remaining passages keep Week 3's order.
        kept = [r for r in week3["results"]
                if self.catalog.row(r["passage_id"])["source_type"] not in policy.reference_only_source_types]
        if len(kept) < len(week3["results"]):
            report["reference_only_dropped"] = len(week3["results"]) - len(kept)
        passages = [self._to_passage(result, rank) for rank, result in enumerate(kept, start=1)]

        # 7 evidence check per need. It annotates coverage; it never re-ranks or prunes Week 3's selection.
        # Only with the evidence_gate switch does "no passage supports any need" empty the bundle.
        needs = request["evidence_needs"]
        results, judge_errors = check_needs(needs, passages, pinned=pinned,
                                            concept_names=request.get("concept_names") or [])
        report["evidence_check"] = [r.__dict__ for r in results]
        if self.options.judge_mode != "off" and self.judge is not None and passages:
            results, judge_errors = self._judge(needs, passages, results, report)
        report["options"] = self.options.describe()
        if passages and not any(related(n, p["passage_text"], request.get("concept_names") or [])
                                for n in needs for p in passages):
            report["evidence_check_outcome"] = "every returned passage is off-topic for every stated need"
            if self.options.evidence_gate:
                passages = []
        need_coverage = [{"need_id": r.need_id, "coverage": r.coverage, "passage_ids": r.passage_ids, "method": r.method}
                         for r in results]
        warnings = self._warnings(passages, results, judge_errors, week3.get("selection_skip_reasons") or {})
        if not passages:
            status = "no_support_found"
        elif all(r.coverage == "covered" for r in results):
            status = "supported"
        else:
            status = "partial"
        bundle = grounding_bundle(request=request, retrieval_status=status, passages=passages, warnings=warnings,
                                  need_coverage=need_coverage, snapshot_id=policy.retrieval_snapshot_id,
                                  query_interpretation={"question": question, "facets": facets, "facet_source": facet_source,
                                                        "semantic_channel": self.backend.semantic_available,
                                                        "backend": self.backend.name, "selection": "week3_production",
                                                        "options": self.options.describe(),
                                                        "plan": report.get("retrieval_plan"),
                                                        "channel_candidate_counts": week3.get("channel_candidate_counts")})
        return self._finish(bundle, report, started)

    # ------------------------------------------------------------------ steps
    def _judge(self, needs: list[dict[str, Any]], passages: list[dict[str, Any]], rules: list[Any],
               report: dict[str, Any]) -> tuple[list[Any], list[dict[str, Any]]]:
        """Layer 3. shadow: log the judge's verdict next to the rules; on: the judge decides (pinned still wins)."""
        texts = [self.catalog.passages[p["legacy_locator"]["week3_passage_id"]].get("readable_text") or p["passage_text"]
                 for p in passages]
        t0 = time.perf_counter()
        try:
            from .evidence import judge_needs
            verdicts = judge_needs(self.judge, needs, passages, texts)
        except Exception as error:  # the judge never blocks a turn
            report["judge"] = {"mode": self.options.judge_mode, "error": str(error)[:200]}
            return rules, [{"error": str(error)[:200]}]
        report["timings_ms"]["judge"] = round((time.perf_counter() - t0) * 1000, 1)
        report["judge"] = {"mode": self.options.judge_mode,
                           "verdicts": [v.__dict__ for v in verdicts],
                           "agrees_with_rules": [v.coverage == r.coverage for v, r in zip(verdicts, rules)]}
        if self.options.judge_mode == "shadow":
            return rules, []
        return [r if r.method == "pinned" else v for r, v in zip(rules, verdicts)], []

    def _validate(self, r: dict[str, Any]) -> list[dict[str, str]]:
        errs: list[dict[str, str]] = []

        def e(field_name: str, code: str, message: str) -> None:
            errs.append({"field": field_name, "code": code, "message": message})

        for key in ("retrieval_request_id", "course_id", "question_id", "turn_id", "query", "purpose", "correlation_id"):
            if not r.get(key):
                e(key, "invalid_request", f"{key} is required")
        if r.get("course_id") and r["course_id"] not in self.policies:
            e("course_id", "unknown_course", f"no retrieval policy/index for course '{r['course_id']}'")
        if r.get("purpose") and r["purpose"] not in PURPOSES:
            e("purpose", "invalid_request", "unknown purpose")
        if isinstance(r.get("query"), str) and len(r["query"]) > 2000:
            e("query", "invalid_request", "query longer than 2,000 characters")
        top_k = r.get("top_k", 6)
        if not isinstance(top_k, int) or not 1 <= top_k <= 10:
            e("top_k", "invalid_request", "top_k must be 1..10")
        needs = r.get("evidence_needs")
        if not isinstance(needs, list) or not 1 <= len(needs) <= 4:
            e("evidence_needs", "invalid_request", "1-4 typed evidence_needs are required by this tool")
        else:
            for i, n in enumerate(needs):
                if n.get("need_type") not in NEED_TYPES or not n.get("need_id"):
                    e(f"evidence_needs[{i}]", "invalid_request", "need_id and a known need_type are required")
        if len(r.get("evidence_summary") or "") > 500:
            e("evidence_summary", "evidence_summary_too_broad", "evidence_summary must be ≤ 500 characters")
        return errs

    def _eligible_documents(self, policy: CoursePolicy) -> list[dict[str, Any]]:
        docs = self.catalog.documents_for(policy.course_id)
        if policy.allow_unverified_sources == "none":
            # every document in the current corpus is AI-generated and unreviewed
            docs = [d for d in docs if d.get("review_status") not in ("unverified",)]
        return docs

    def _scope_check(self, request: dict[str, Any], policy: CoursePolicy, documents: list[dict[str, Any]],
                     report: dict[str, Any], *, text: str, label: str) -> dict[str, Any] | None:
        source_types = {d["source_type"] for d in documents}
        decided = None
        if self.scope_checker is not None:
            decided = self.scope_checker(text, course_id=request["course_id"], source_types=source_types, policy=policy)
        checks = report["preflight"].setdefault("scope_check", {})
        checks[label] = {"rules": decided}
        if (decided is None or decided.get("decision") == "retrieve") and self.model_scope_checker is not None:
            try:  # a model check may only make the outcome stricter
                model = self.model_scope_checker(text, course_id=request["course_id"],
                                                 source_types=source_types, policy=policy)
                checks[label]["model"] = model
                if model.get("decision") != "retrieve":
                    decided = model
            except Exception as error:
                checks[label]["model"] = {"gate_fallback": str(error)[:200]}
        if not decided or decided.get("decision") == "retrieve":
            return None
        reason = decided.get("reason_code") or decided.get("category") or "excluded_scope"
        if decided["decision"] == "needs_clarification":
            return retrieval_stop(request=request, stop_reason="needs_clarification",
                                  reason_code=decided.get("category", "ambiguous_scope"), retryable=True,
                                  policy_version=policy.policy_version,
                                  clarification_prompt_hint=decided.get("explanation"))
        code = "source_class_unavailable" if decided.get("category") == "source_unavailable" else "excluded_scope"
        return self._empty(request, policy, code, f"{reason} (in the {label.replace('_', ' ')}): {decided.get('explanation', '')}")

    def _plan(self, request: dict[str, Any]) -> tuple[str, list[str], str]:
        question = " ".join(request["query"].split())
        if self.options.facet_source == "week3":
            week3_facets = self.backend.query_facets(question)
            return question, week3_facets, "week3_query_facets" if week3_facets else "none"
        facets = []
        for need in request["evidence_needs"]:
            text = need["description"]
            if need.get("anchor") and need["anchor"].lower() not in text.lower():
                text = f"{text} {need['anchor']}"
            text = " ".join(text.split())
            if text.lower() != question.lower() and text not in facets:
                facets.append(text)
        if facets:
            return question, facets[:4], "evidence_needs"
        week3_facets = self.backend.query_facets(question)
        return question, week3_facets, "week3_query_facets" if week3_facets else "none"

    def _to_passage(self, result: dict[str, Any], rank: int) -> dict[str, Any]:
        source_passage_id = result["passage_id"]
        row = self.catalog.row(source_passage_id)
        content_version = f"cv-src-{row['document_sha256'][:12]}"
        # Dev corpus: LaTeX source lines are NOT page lines (rag-retrieval.md §5.3). Until Ovunc's ingested
        # pages exist, page/line/highlight stay null and the source lines go to legacy_locator.
        passage = {
            "passage_id": passage_identity(row["document_id"], content_version, None, row["start_line"], row["end_line"]),
            "document_id": row["document_id"],
            "content_version": content_version,
            "page_number": None,
            "line_start": None,
            "line_end": None,
            "passage_text": row["raw_latex"].strip(),
            "highlight_url": None,
            "relevance_score": None,       # fused scores are ranking signals, not calibrated (§7.7)
            "retrieval_rank": rank,
            "role": "primary",
            "visibility": "student_visible",
            "document_role": "ai_course_breakdown",
            "source_provenance": "ai_generated",
            "review_status": row["review_status"],
            "source_label": f"{LEGACY_SOURCE_LABELS.get(row['source_type'], 'AI-prepared material')}"
                            + (f", {row['section_path']}" if row.get("section_path") else ""),
            "legacy_locator": {"file": row["filename"], "source_line_start": row["start_line"],
                               "source_line_end": row["end_line"], "week3_passage_id": source_passage_id,
                               "week3_selection_reason": result.get("selection_reason"),
                               "week3_signals": result.get("signals")},
        }
        if row["known_issues"]:
            passage["known_issues"] = row["known_issues"]
        return passage

    def _warnings(self, passages: list[dict[str, Any]], results: list[Any], judge_errors: list[dict[str, Any]],
                  cuts: dict[str, int]) -> list[dict[str, Any]]:
        out = []
        for p in passages:
            if p["source_provenance"] == "ai_generated":
                out.append(warning("unverified_source", "AI-generated course breakdown; not reviewed course material.",
                                   passage_id=p["passage_id"]))
            if p["page_number"] is None:
                out.append(warning("location_unavailable", "Development corpus: LaTeX source lines only "
                                   "(legacy_locator); no page, line map or highlight link yet.", passage_id=p["passage_id"]))
            if p.get("known_issues"):
                out.append(warning("source_quality_warning", "Open review issue inside this passage.",
                                   passage_id=p["passage_id"]))
        for r in results:
            if r.coverage == "partially_covered":
                out.append(warning("sufficiency_uncertain", f"Need only partly supported ({r.detail}).", need_id=r.need_id))
        if not self.backend.semantic_available:
            out.append(warning("semantic_channel_unavailable", "Vector channel off (no query encoder); keyword-only search."))
        if judge_errors:
            out.append(warning("sufficiency_uncertain", "Evidence judge unavailable; rules decided this bundle (judge_fallback)."))
        if cuts.get("context_budget"):
            out.append(warning("budget_truncated", f"{cuts['context_budget']} passage(s) skipped by the character budget."))
        return out

    def _empty(self, request: dict[str, Any], policy: CoursePolicy, code: str, message: str) -> dict[str, Any]:
        return grounding_bundle(request=request, retrieval_status="no_support_found", passages=[],
                                warnings=[warning(code, message)], snapshot_id=policy.retrieval_snapshot_id)

    def _finish(self, record: dict[str, Any], report: dict[str, Any], started: float) -> dict[str, Any]:
        report["timings_ms"]["total"] = round((time.perf_counter() - started) * 1000, 1)
        report["final"] = record.get("retrieval_status") or record.get("stop_reason")
        if record["record_type"] == "GroundingBundle":
            problems = check_bundle_invariants(record)
            if problems:
                raise AssertionError(f"bundle invariant violated: {problems}")
            self.registry.add(record)
        return record
