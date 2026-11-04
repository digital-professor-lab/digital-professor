"""Who should decide retrieval on `may` turns? Compares three options on the labelled decision set.

  model   DeepSeek alone (tool offered with tool_choice=auto). Counts DeepSeek calls.
  jev     Jev alone: one yes/no question per case, no DeepSeek call. Reports p and accuracy at thresholds.
  both    Jev settles clear cases (force / skip), DeepSeek decides the rest.

Labels (data/tool_decision_cases.jsonl, 24 cases, 12 should-retrieve) are Sean's silver labels: spot-check them.
Every case is a `may` turn (probe, diagnose, check_understanding, transfer); must/must_not turns are fixed by code.

    python scripts/eval_tool_decisions.py --recommender jev            # needs the Jev key in week5 jev/.env; < $0.01
    python scripts/eval_tool_decisions.py --recommender model          # needs DEEPSEEK_API_KEY; Week 3 database running
    python scripts/eval_tool_decisions.py --recommender all            # all three, one report
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

WEEK8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEEK8))
from retrieval_tool import TurnContext, build_service, recommend_grounding, run_turn  # noqa: E402
from retrieval_tool.jev_recommender import FORCE_AT, SKIP_BELOW, JevSearchRecommender, load_jev_client  # noqa: E402
from retrieval_tool.llm import OpenAICompatibleLLM  # noqa: E402


def context(case: dict) -> TurnContext:
    return TurnContext(course_id="calc1", course_title="Calculus I", session_id="eval", turn_id=case["id"], question_id="calc1.eval",
                       correlation_id=f"eval-{case['id']}", action_type=case["action_type"],
                       retrieval_snapshot_id="snap.calc1.dev-ai-breakdown.1", concept_names=case["concept_names"],
                       student_message=case["student_message"], intent_summary=case["intent_summary"])


def confusion(rows: list[dict], key: str) -> dict:
    tp = sum(r[key] and r["should_retrieve"] for r in rows)
    tn = sum(not r[key] and not r["should_retrieve"] for r in rows)
    return {"accuracy": f"{tp + tn}/{len(rows)}", "missed_retrievals": sum(not r[key] and r["should_retrieve"] for r in rows),
            "unneeded_retrievals": sum(r[key] and not r["should_retrieve"] for r in rows)}


def run_jev(cases: list[dict]) -> dict:
    recommender = JevSearchRecommender(load_jev_client())
    rows = []
    for case in cases:
        p = recommender.probability(context(case))
        rows.append({"id": case["id"], "should_retrieve": case["should_retrieve"], "p": round(p, 4)})
    sweep = {}
    for t in (0.3, 0.4, 0.5, 0.6, 0.7):
        for r in rows:
            r["_hit"] = r["p"] >= t
        sweep[str(t)] = confusion(rows, "_hit")
    three_way = {"force": sum(r["p"] >= FORCE_AT for r in rows), "skip": sum(r["p"] < SKIP_BELOW for r in rows)}
    three_way["left_to_model"] = len(rows) - three_way["force"] - three_way["skip"]
    wrong_force = [r["id"] for r in rows if r["p"] >= FORCE_AT and not r["should_retrieve"]]
    wrong_skip = [r["id"] for r in rows if r["p"] < SKIP_BELOW and r["should_retrieve"]]
    for r in rows:
        r.pop("_hit", None)
    return {"rows": rows, "threshold_sweep": sweep, "three_way_at_defaults": three_way,
            "wrong_force": wrong_force, "wrong_skip": wrong_skip, "usage": recommender.client.usage.to_dict()}


def run_turns(cases: list[dict], *, with_jev: bool) -> dict:
    service = build_service("pgvector")
    service.policies["calc1"] = replace(service.policies["calc1"], external_processing_allowed=with_jev)
    llm = OpenAICompatibleLLM("deepseek")
    recommender = JevSearchRecommender(load_jev_client()) if with_jev else None
    rows, started = [], time.perf_counter()
    for case in cases:
        ctx = context(case)
        decision = recommend_grounding(case["action_type"])
        assert decision.mode == "may", case["id"]
        result = run_turn(llm, service, ctx, decision=decision, recommender=recommender)
        verdict = next((e for e in result.events if e["event_type"] == "retrieval_decision"), {})
        rows.append({"id": case["id"], "should_retrieve": case["should_retrieve"],
                     "retrieved": bool(result.requests), "deepseek_calls": result.llm_calls,
                     "jev_choice": verdict.get("choice"), "jev_p": verdict.get("p"),
                     "queries": [r["query"] for r in result.requests], "answer": result.answer,
                     "citation_ok": result.citation_check.get("ok")})
        print(f"  {case['id']} want={case['should_retrieve']!s:5} retrieved={rows[-1]['retrieved']!s:5} "
              f"deepseek_calls={result.llm_calls} jev={verdict.get('choice')}", flush=True)
    return {"summary": {**confusion(rows, "retrieved"), "deepseek_calls": sum(r["deepseek_calls"] for r in rows),
                        "seconds": round(time.perf_counter() - started, 1), "model": llm.model,
                        **({"jev_usage": recommender.client.usage.to_dict()} if recommender else {})},
            "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recommender", required=True, choices=("model", "jev", "both", "all"))
    args = parser.parse_args()
    cases = [json.loads(l) for l in (WEEK8 / "data/tool_decision_cases.jsonl").read_text().splitlines() if l.strip()]
    out: dict = {"cases": len(cases), "should_retrieve": sum(c["should_retrieve"] for c in cases)}
    if args.recommender in ("jev", "all"):
        print("== Jev alone ==")
        out["jev"] = run_jev(cases)
        print(json.dumps({k: out["jev"][k] for k in ("threshold_sweep", "three_way_at_defaults", "wrong_force", "wrong_skip")}, indent=1))
    if args.recommender in ("model", "all"):
        print("== DeepSeek alone ==")
        out["model"] = run_turns(cases, with_jev=False)
        print(json.dumps(out["model"]["summary"], indent=1))
    if args.recommender in ("both", "all"):
        print("== Jev + DeepSeek ==")
        out["both"] = run_turns(cases, with_jev=True)
        print(json.dumps(out["both"]["summary"], indent=1))
    path = WEEK8 / "results" / f"tool_decisions_{args.recommender}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {path.relative_to(WEEK8)}")


if __name__ == "__main__":
    main()
