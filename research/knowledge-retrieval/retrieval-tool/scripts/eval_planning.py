"""Retrieval planning check: does the plan point at the right course concept?

36 labelled student turns (data/planning_cases.jsonl): 17 name the topic, 14 paraphrase it, 5 should link to
nothing (outside the course, or no content request). Two planners are compared:

  code        concept linking against the Course Context list only (no model). Offline, free.
  code+model  the code draft + one DeepSeek call that may pick concepts from the list (enum) and rewrite
              queries; the result is validated and repaired by code. Needs DEEPSEEK_API_KEY; ~36 calls.

Scoring per turn uses the PRIMARY concept(s) only — they decide what counts as support:
  correct     primary concepts non-empty and all acceptable (or none when none should be)
  wrong       a primary concept is not acceptable
  abstained   no primary concept although the turn has one (safe, but the plan has no concept)
Related concepts are reported separately (they are recorded, not used to judge evidence), as is
"not_in_course" on the turns about material outside the course.
Labels are Sean's silver labels; spot-check them.

    python scripts/eval_planning.py                 # code only
    python scripts/eval_planning.py --llm deepseek  # code vs code+DeepSeek
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

WEEK8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEEK8))
from retrieval_tool import TurnContext, recommend_grounding  # noqa: E402
from retrieval_tool.planner import RetrievalPlanner, validate_plan  # noqa: E402


def outcome(selected: list[str], acceptable: list[str]) -> str:
    if not acceptable:
        return "correct" if not selected else "wrong"
    if not selected:
        return "abstained"
    return "correct" if all(s in acceptable for s in selected) else "wrong"


def primary(plan: dict) -> list[str]:
    return [c["concept_id"] for c in plan.get("concepts", []) if c.get("role", "primary") == "primary"]


def related(plan: dict) -> list[str]:
    return [c["concept_id"] for c in plan.get("concepts", []) if c.get("role") == "related"]


def summarize(rows: list[dict], key: str) -> dict:
    counts = Counter(r[key] for r in rows)
    by_kind = {}
    for kind in ("named", "paraphrase", "outside", "no_content"):
        sub = [r for r in rows if r["kind"] == kind]
        if sub:
            by_kind[kind] = f"{sum(r[key] == 'correct' for r in sub)}/{len(sub)}"
    return {"correct": f"{counts['correct']}/{len(rows)}", "wrong": counts["wrong"], "abstained": counts["abstained"],
            "correct_by_kind": by_kind}


def context(case: dict) -> TurnContext:
    return TurnContext(course_id="calc1", course_title="Calculus I", session_id="plan-eval", turn_id=case["id"],
                       question_id="calc1.adhoc", correlation_id=f"plan-{case['id']}", action_type="explain",
                       student_message=case["student_message"], retrieval_snapshot_id="snap.calc1.dev-ai-breakdown.1")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", default=None, choices=("deepseek", "gemini", "kimi", "openai"))
    args = parser.parse_args()
    cases = [json.loads(l) for l in (WEEK8 / "data/planning_cases.jsonl").read_text().splitlines() if l.strip()]
    planner = RetrievalPlanner.from_folder(["calc1"])
    decision = recommend_grounding("explain")
    rows = []
    for case in cases:
        draft = planner.draft(context(case), decision)
        selected = primary(draft)
        rows.append({"id": case["id"], "kind": case["kind"], "message": case["student_message"],
                     "acceptable": case["acceptable_concepts"], "code": selected, "code_related": related(draft),
                     "code_outcome": outcome(selected, case["acceptable_concepts"]),
                     "code_top_candidates": [(h["concept_id"], h["score"]) for h in draft["linking"]["candidates"][:3]]})
    out: dict = {"cases": len(cases), "code": summarize(rows, "code_outcome")}

    if args.llm:
        from retrieval_tool import build_service
        from retrieval_tool.agent_loop import propose_plan
        from retrieval_tool.llm import OpenAICompatibleLLM
        llm = OpenAICompatibleLLM(args.llm)
        service = build_service("replay")      # planning only: nothing is searched
        repairs = Counter()
        for case, row in zip(cases, rows):
            result = propose_plan(llm, service, context(case), decision=decision)
            plan = result.get("plan") or {}
            selected = primary(plan)
            raw = result.get("raw_args") or {}
            row.update({"model": selected, "model_outcome": outcome(selected, case["acceptable_concepts"]),
                        "model_related": related(plan), "concept_status": plan.get("concept_status"),
                        "model_raw_concepts": {k: raw.get(k) for k in ("concept_id", "related_concept_ids", "concept_ids")
                                               if k in raw},
                        "model_queries": [n["query"] for n in plan.get("needs", [])], "model_ms": result.get("ms"),
                        "repairs": plan.get("repairs", []), "schema_problems": validate_plan(plan) if plan else ["no plan"],
                        "error": result.get("error")})
            repairs.update(r["code"] for r in plan.get("repairs", []))
            print(f"  {case['id']} {row['code_outcome']:9s} → {row['model_outcome']:9s} {selected}"
                  f"{'  related=' + str(row['model_related']) if row['model_related'] else ''}"
                  f"{'  [not_in_course]' if row['concept_status'] == 'not_in_course' else ''}", flush=True)
        outside = [r for r in rows if r["kind"] == "outside"]
        out["code+model"] = {**summarize(rows, "model_outcome"), "model": llm.model,
                             "turns_with_related": sum(bool(r["model_related"]) for r in rows),
                             "related_not_acceptable": sum(any(c not in r["acceptable"] for c in r["model_related"])
                                                           for r in rows if r["acceptable"]),
                             "outside_marked_not_in_course": f"{sum(r['concept_status'] == 'not_in_course' for r in outside)}/{len(outside)}",
                             "repairs": dict(repairs), "schema_problems": sum(bool(r["schema_problems"]) for r in rows),
                             "mean_ms": round(sum(r["model_ms"] or 0 for r in rows) / len(rows))}
    out["rows"] = rows
    name = f"planning_eval{'_' + args.llm if args.llm else ''}.json"
    (WEEK8 / "results" / name).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    for r in rows:
        if r["code_outcome"] == "wrong" or r.get("model_outcome") == "wrong":
            print(f"  WRONG {r['id']}: code={r['code']} model={r.get('model')} acceptable={r['acceptable']}")
    print(f"saved results/{name}")


if __name__ == "__main__":
    main()
