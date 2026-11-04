"""Week 3 alignment check: does the tool path return exactly what Week 3 returns?

Runs (needs the Week 3 Docker database and model cache on the Mac, unless --replay-only):

  week3_direct         Week 3 `Retriever.search_many`, unmodified, exactly the Week 3 `facets_6` configuration
                       (top_k 6, 40 candidates, 12,000 chars, soft limit 4/file, sub-questions, NO course filter).
                       This is the 46/46 reference.
  week3_direct_course  the same Week 3 call, but with each question's course_id as filter (the tool always
                       scopes to one course, rag-retrieval.md §5.1). Shows what the course filter alone changes.
  tool                 RetrievalRequest → GroundingBundle through the tool path (Week 3 code underneath).
                       Must equal week3_direct_course passage-for-passage, in the same order.
  replay               offline: Week 3's saved facets_6 reports through the tool wrapper. Must reproduce 46/46.

Scoring is Week 3's own rule (evaluation/run_benchmark.py `passage_covers` + `complete_at`): a gold anchor is
found when a returned passage of the same document contains its line range within the first 6 results.

    python scripts/benchmark_check.py                    # all live runs + replay
    python scripts/benchmark_check.py --replay-only      # no Docker needed
Two tool settings are reported: `tool` (week3_parity: evidence gate off, must equal Week 3) and
`tool_production` (evidence gate on, as in tutoring turns: shows what the gate removes).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

WEEK8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEEK8))
from retrieval_tool import RetrievalOptions, TurnContext, build_service, retrieval_root, week3_folder  # noqa: E402
from retrieval_tool.tool_schema import build_request  # noqa: E402

TOP_K = 6


def load(root: Path):
    read = lambda p: [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]  # noqa: E731
    cases = read(root / "data/benchmark/benchmark_50.jsonl")
    passages = {p["passage_id"]: p for p in read(root / "data/catalog/passages.jsonl")}
    return cases, passages


def passage_covers(retrieved_id: str, gold_id: str, passages: dict) -> bool:
    """Copied from Week 3 evaluation/run_benchmark.py (same document, line range contains the gold span)."""
    if retrieved_id == gold_id:
        return True
    retrieved, gold = passages.get(retrieved_id), passages.get(gold_id)
    if retrieved is None or gold is None:
        return False
    return (retrieved["document_id"] == gold["document_id"] and retrieved["start_line"] <= gold["start_line"]
            and retrieved["end_line"] >= gold["end_line"])


def score(cases: list[dict], selected: dict[str, list[str]], statuses: dict[str, str], passages: dict) -> dict:
    complete, withheld, per_case = 0, 0, {}
    answerable = [c for c in cases if c["kind"] == "answerable"]
    for case in cases:
        ids = selected.get(case["id"], [])[:TOP_K]
        if case["kind"] == "answerable":
            ok = all(any(passage_covers(r, a["passage_id"], passages) for r in ids for a in group)
                     for group in case["required_evidence_groups"])
            complete += ok
            per_case[case["id"]] = {"complete_at6": ok, "status": statuses.get(case["id"]), "passages": ids}
        else:
            ok = statuses.get(case["id"]) in ("not_found", "needs_clarification", "no_support_found", "stop:needs_clarification")
            withheld += ok
            per_case[case["id"]] = {"withheld": ok, "status": statuses.get(case["id"])}
    return {"complete_at6": f"{complete}/{len(answerable)}", "non_answerable_withheld": f"{withheld}/{len(cases) - len(answerable)}",
            "cases": per_case}


def week3_direct(cases: list[dict], *, course_filter: bool) -> tuple[dict, dict]:
    kb = week3_folder()
    if kb is None:
        raise SystemExit("Week 3 folder not found (../week3/knowledge_base); set WEEK3_KB")
    sys.path.insert(0, str(kb / "retrieval"))
    from search import Retriever  # Week 3, unmodified
    selected, statuses = {}, {}
    with Retriever() as retriever:
        if course_filter:
            for case in cases:
                report = retriever.search_many([case["question"]], course_id=case["course_id"], top_k=TOP_K,
                                               candidate_limit=40, context_chars=12000, decompose_query=True)[0]
                selected[case["id"]] = [r["passage_id"] for r in report["results"]]
                statuses[case["id"]] = report["status"]
        else:
            reports = retriever.search_many([c["question"] for c in cases], top_k=TOP_K, candidate_limit=40,
                                            context_chars=12000, decompose_query=True)
            for case, report in zip(cases, reports):
                selected[case["id"]] = [r["passage_id"] for r in report["results"]]
                statuses[case["id"]] = report["status"]
    return selected, statuses


def tool_path(cases: list[dict], service) -> tuple[dict, dict]:
    selected, statuses = {}, {}
    for case in cases:
        ctx = TurnContext(course_id=case["course_id"], session_id="bench", turn_id=case["id"], question_id=case["id"],
                          correlation_id=f"bench-{case['id']}", action_type="explain",
                          retrieval_snapshot_id=f"snap.{case['course_id']}.dev-ai-breakdown.1")
        args = {"query": case["question"], "purpose": "answer_grounding",
                "evidence_needs": [{"need_type": "method_guidance", "description": case["question"][:200]}]}
        record = service.handle(build_request(args, ctx, top_k=TOP_K))
        selected[case["id"]] = [p["legacy_locator"]["week3_passage_id"] for p in record.get("passages", [])]
        statuses[case["id"]] = record.get("retrieval_status") or f"stop:{record.get('stop_reason')}"
    return selected, statuses


def compare(a: dict, b: dict) -> list[str]:
    """Question ids whose returned passages differ (ids or order)."""
    return sorted(k for k in set(a) | set(b) if a.get(k, []) != b.get(k, []))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-only", action="store_true", help="offline: only the replay check")
    args = parser.parse_args()
    root = retrieval_root()
    cases, passages = load(root)
    out: dict = {"top_k": TOP_K, "runs": {}, "parity": {}}
    parity, production = RetrievalOptions.week3_parity(), RetrievalOptions()

    # replay: Week 3's saved facets_6 reports through the wrapper (no course filter was used when they were recorded)
    replay_file = root / "artifacts/evaluations/refinement_runs/facets_6.jsonl"
    recorded = {json.loads(l)["id"]: json.loads(l)["report"] for l in replay_file.read_text().splitlines() if l.strip()}
    rec_sel = {k: [r["passage_id"] for r in v["results"]] for k, v in recorded.items()}
    rec_status = {k: v["status"] for k, v in recorded.items()}
    sel, st = tool_path(cases, build_service("replay", root=root, options=parity, replay_file=replay_file))
    out["runs"]["week3_recorded_facets_6"] = score(cases, rec_sel, rec_status, passages)
    out["runs"]["replay_through_tool"] = score(cases, sel, st, passages)
    out["parity"]["replay_vs_recorded_differs"] = compare(rec_sel, sel)
    g_sel, g_st = tool_path(cases, build_service("replay", root=root, options=production, replay_file=replay_file))
    out["runs"]["replay_through_tool_production"] = score(cases, g_sel, g_st, passages)
    out["parity"]["evidence_gate_emptied"] = sorted(k for k in sel if sel[k] and not g_sel.get(k))

    if not args.replay_only:
        t = time.perf_counter()
        d_sel, d_st = week3_direct(cases, course_filter=False)
        out["runs"]["week3_direct"] = {**score(cases, d_sel, d_st, passages), "seconds": round(time.perf_counter() - t, 1)}
        t = time.perf_counter()
        c_sel, c_st = week3_direct(cases, course_filter=True)
        out["runs"]["week3_direct_course"] = {**score(cases, c_sel, c_st, passages), "seconds": round(time.perf_counter() - t, 1)}
        t = time.perf_counter()
        service = build_service("pgvector", root=root, options=parity)
        t_sel, t_st = tool_path(cases, service)
        out["runs"]["tool"] = {**score(cases, t_sel, t_st, passages), "seconds": round(time.perf_counter() - t, 1),
                               "options": parity.describe()}
        service.options = production
        p_sel, p_st = tool_path(cases, service)
        out["runs"]["tool_production"] = {**score(cases, p_sel, p_st, passages), "options": production.describe()}
        out["parity"]["week3_direct_vs_recorded_differs"] = compare(rec_sel, d_sel)
        out["parity"]["course_filter_changes"] = compare(d_sel, c_sel)
        out["parity"]["tool_vs_week3_direct_course_differs"] = compare(c_sel, t_sel)

    name = "week3_alignment" + ("_replay" if args.replay_only else "")
    (WEEK8 / "results" / f"{name}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"{'run':28s} complete@6   withheld")
    for run, res in out["runs"].items():
        print(f"{run:28s} {res['complete_at6']:>10s}   {res['non_answerable_withheld']}")
    for key, ids in out["parity"].items():
        print(f"{key}: {'none' if not ids else ', '.join(ids)}")
    print(f"saved results/{name}.json")


if __name__ == "__main__":
    try:
        retrieval_root()
    except FileNotFoundError as error:
        raise SystemExit(f"{error}\nThis check compares against Week 3, so it needs that checkout. "
                         "The self-contained check is scripts/smoke_check.py.")
    main()
