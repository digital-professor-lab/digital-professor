"""Digital Professor — Course Knowledge Retrieval as a tool call (Week 8, Sean).

Quick start (on the Mac, Week 3 Docker database running):

    from retrieval_tool import build_service, TurnContext, recommend_grounding, run_turn
    service = build_service()                      # Week 3 code + Docker DB + BGE/Qwen, Week 3 thresholds
    decision = recommend_grounding("explain")      # the Engine or coordinator applies the agreed policy
    result = run_turn(llm, service, ctx, decision=decision)
    service = build_service(options=RetrievalOptions(facet_source="evidence_needs"))   # one switch on
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .agent_loop import TurnResult, run_turn
from .backends import Catalog, InMemoryBackend, PgvectorBackend, ReplayBackend
from .citations import verify_grounding_refs
from .policy import GROUNDING_POLICY, POLICY_VERSION, recommend_grounding, policy_table
from .service import CoursePolicy, RetrievalOptions, RetrievalService, default_scope_checker, development_policy
from .tool_schema import TOOL_NAME, TurnContext, anthropic_tool, build_request, openai_tool, tool_for_decision

WEEK8 = Path(__file__).resolve().parents[1]


def retrieval_root() -> Path:
    """The Week 3 package with data/ and src/: DP_RETRIEVAL_ROOT, .week3/ from scripts/setup_week3.sh,
    or the local package at ../output/github-ready."""
    env = os.environ.get("DP_RETRIEVAL_ROOT")
    candidates = [Path(env)] if env else [WEEK8 / ".week3", WEEK8.parent / "output" / "github-ready"]
    for root in candidates:
        if (root / "data" / "catalog" / "passages.jsonl").exists():
            return root
    raise FileNotFoundError(f"Week 3 index files not found under {candidates[0]}; run bash scripts/setup_week3.sh "
                            "or set DP_RETRIEVAL_ROOT")


def week3_folder() -> Path | None:
    """The live Week 3 folder (Docker DB credentials + model cache); override with WEEK3_KB."""
    kb = Path(os.environ.get("WEEK3_KB", WEEK8.parent / "week3" / "knowledge_base"))
    return kb if kb.exists() else None


def build_service(backend: str = "pgvector", *, root: Path | None = None, options: RetrievalOptions | None = None,
                  policies: dict[str, CoursePolicy] | None = None, judge: Any = None, model_scope_checker: Any = None,
                  replay_file: Path | None = None, test_double: bool = False, encoder: Any = None) -> RetrievalService:
    """backend: "pgvector" (default, real Week 3 search), "replay" (Week 3's saved reports),
    "memory" (Week 3 code over Week 3 files; requires test_double=True because its numbers are not Week 3's),
    or "fixture" (no Week 3 code, database or models; for tests and the smoke check only)."""
    if backend == "fixture":
        from .local_fixture import FIXTURE_ROOT, LocalFixtureBackend, fixture_scope_checker
        from .planner import RetrievalPlanner
        catalog = Catalog.load(FIXTURE_ROOT)
        policies = policies or {c: development_policy(c) for c in sorted(catalog.courses())}
        return RetrievalService(LocalFixtureBackend(catalog), catalog, policies, scope_checker=fixture_scope_checker,
                                model_scope_checker=model_scope_checker, judge=judge, options=options,
                                planner=RetrievalPlanner.from_folder(sorted(catalog.courses())))
    root = root or retrieval_root()
    catalog = Catalog.load(root)
    if backend == "pgvector":
        search_backend: Any = PgvectorBackend(root, week3_kb=week3_folder())
    elif backend == "replay":
        search_backend = ReplayBackend(root, replay_file or root / "artifacts/evaluations/refinement_runs/facets_6.jsonl")
    elif backend == "memory":
        if not test_double:
            raise ValueError("the in-memory backend is a test stand-in; pass test_double=True (never for benchmarks)")
        search_backend = InMemoryBackend(root, catalog=catalog, encoder=encoder)
    else:
        raise ValueError("backend must be 'pgvector', 'replay', 'memory' or 'fixture'")
    policies = policies or {c: development_policy(c) for c in sorted(catalog.courses())}
    from .planner import RetrievalPlanner
    planner = RetrievalPlanner.from_folder(sorted(catalog.courses()))
    return RetrievalService(search_backend, catalog, policies, scope_checker=default_scope_checker(root),
                            model_scope_checker=model_scope_checker, judge=judge, options=options, planner=planner)


def build_tutoring_runtime(backend: str = "pgvector", *, use_jev: bool = True, warm_up: bool = True, **kwargs: Any) -> tuple[RetrievalService, Any, list[str]]:
    """The recommended setup for tutoring turns (adopted 2026-10-29 after the labelled checks):

    * retrieval = Week 3 code and thresholds; evidence gate on;
    * evidence judge = Jev, judge_mode "on" (28 labelled pairs: 0 false "covered" vs 8 for the rules);
      the rules decide whenever Jev fails;
    * optional-search recommender = Jev (24 labelled turns: 22/24 vs 17/24 for DeepSeek alone);
      the caller chooses whether to pass it to `run_turn`.

    Without the Jev key (or with use_jev=False) everything falls back to rules + the tutoring model.
    Returns (service, decider_or_None, notes).
    """
    notes: list[str] = []
    judge, recommender = None, None
    if use_jev:
        from .jev_recommender import default_recommender, default_evidence_judge
        try:
            judge = default_evidence_judge()
            notes.append("evidence judge: jev (on)")
        except Exception as error:
            notes.append(f"evidence judge: rules only ({str(error)[:100]})")
        recommender, note = default_recommender()
        notes.append(f"may-turn decisions: {note}")
    else:
        notes.append("Jev off: rules decide evidence, the tutoring model decides may-turns")
    options = RetrievalOptions(judge_mode="on" if judge is not None else "off")
    service = build_service(backend, options=options, judge=judge, **kwargs)
    if warm_up:
        notes.append(f"encoders loaded at startup ({service.warm_up()}s)")
    return service, recommender, notes


__all__ = ["build_tutoring_runtime", "build_service", "retrieval_root", "run_turn", "TurnResult", "TurnContext", "recommend_grounding", "policy_table",
           "GROUNDING_POLICY", "POLICY_VERSION", "RetrievalService", "RetrievalOptions", "CoursePolicy", "week3_folder", "development_policy",
           "openai_tool", "anthropic_tool", "tool_for_decision", "build_request", "verify_grounding_refs", "TOOL_NAME"]
