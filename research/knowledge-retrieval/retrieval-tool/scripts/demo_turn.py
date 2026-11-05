"""Run one tutoring turn end to end: grounding policy → model → retrieval tool → answer → citation check.

    python scripts/demo_turn.py --scenario chain_rule_explain                  # offline, scripted model
    python scripts/demo_turn.py --scenario chain_rule_explain --llm deepseek   # real model (DEEPSEEK_API_KEY)
    python scripts/demo_turn.py --all                                          # every scenario, scripted
    Retrieval always runs Week 3's code on the Docker database (start it first, see README).
    --test-double uses the offline in-memory stand-in instead; its retrieval is NOT Week 3's (logic checks only).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WEEK8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEEK8))
from dataclasses import replace  # noqa: E402

from retrieval_tool import TurnContext, build_service, recommend_grounding, run_turn  # noqa: E402
from retrieval_tool.llm import OpenAICompatibleLLM, ScriptedLLM, answer, tool_call  # noqa: E402


def scripted(steps):
    """Replays the scenario; one extra label-free reply answers a citation rewrite if the check asks for one."""
    import re
    replies = [tool_call(s["tool_call"], call_id=f"call_{i}") if "tool_call" in s else answer(s["answer"])
               for i, s in enumerate(steps)]
    last = next((s["answer"] for s in reversed(steps) if "answer" in s), "")
    return ScriptedLLM(replies + [answer(re.sub(r"\s*\[P\d+(?:,\s*P\d+)*\]", "", last))])


def run(name, scenario, service, llm_name, recommender=None):
    context = {"course_id": "calc1", "course_title": "Calculus I", "session_id": "demo-session", "turn_id": f"turn-{name}",
               "correlation_id": f"corr-{name}", "retrieval_snapshot_id": "snap.calc1.dev-ai-breakdown.1",
               "question_id": "calc1.demo", **scenario["context"]}
    ctx = TurnContext(**context)
    llm = scripted(scenario["scripted"]) if llm_name == "scripted" else OpenAICompatibleLLM(llm_name)
    result = run_turn(llm, service, ctx, decision=recommend_grounding(ctx.action_type), goal=scenario["goal"],
                      recommender=recommender)
    print(f"\n=== {name}  (action={ctx.action_type}, policy={result.decision['mode']}, llm={llm_name})")
    print(f"student : {ctx.student_message}")
    for e in result.events:
        if e["event_type"] in ("retrieval_decision", "policy", "citation_rewrite"):
            print(f"event   : {e}")
        if e["event_type"] == "retrieval" and e.get("judge"):
            print(f"judge   : rules={e['judge']['rules']}  jev={e['judge']['verdicts']}  {e['judge'].get('error') or ''}")
    for req, rec in zip(result.requests, result.records):
        status = rec.get("retrieval_status") or f"stop:{rec.get('stop_reason')}"
        print(f"tool    : [{req['producer']}] query={req['query']!r} needs={[n['need_type'] for n in req['evidence_needs']]}"
              f" origin={req['query_origin']} -> {status}")
        for p in rec.get("passages", []):
            loc = p["legacy_locator"]
            print(f"          {p['passage_id']}  {loc['file']}:{loc['source_line_start']}-{loc['source_line_end']}  "
                  f"{p['passage_text'][:80].replace(chr(10), ' ')}...")
        for c in rec.get("need_coverage") or []:
            print(f"          need {c['need_id']}: {c['coverage']} ({c['method']})")
    print(f"tutor   : {result.answer}")
    print(f"refs    : {result.grounding_refs}  citation_check_ok={result.citation_check.get('ok')}  "
          f"model_calls={result.llm_calls}")
    model_ms = sum(e["ms"] for e in result.events if e["event_type"] == "model_call")
    retr = [e["timings_ms"] for e in result.events if e["event_type"] == "retrieval"]
    recommender_ms = sum(e.get("ms", 0) for e in result.events if e["event_type"] == "retrieval_decision")
    print(f"time    : model {model_ms/1000:.1f}s | retrieval {sum(t.get('total', 0) for t in retr)/1000:.1f}s "
          f"(of which Jev judge {sum(t.get('judge', 0) for t in retr)/1000:.1f}s) | Jev recommender {recommender_ms/1000:.1f}s")
    suffix = "_testdouble" if service.backend.name == "in_memory" else ""
    out = WEEK8 / "results" / f"demo_{name}_{llm_name}{suffix}.json"
    out.write_text(json.dumps({"context": context, **result.to_dict()}, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main():
    scenarios = json.loads((WEEK8 / "data" / "demo_scenarios.json").read_text(encoding="utf-8"))
    scenarios.pop("_note")
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=sorted(scenarios), default="chain_rule_explain")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--llm", default="scripted", choices=("scripted", "deepseek", "gemini", "kimi", "openai"))
    parser.add_argument("--no-jev", action="store_true",
                        help="do not use Jev for may-turn decisions (default: Jev decides when its key is available)")
    parser.add_argument("--judge", default=None, choices=("off", "shadow", "on"),
                        help="override the evidence judge (default: the recommended runtime, Jev on)")
    parser.add_argument("--test-double", action="store_true",
                        help="local fixture instead of the Week 3 database (not Week 3 retrieval)")
    args = parser.parse_args()
    from retrieval_tool import RetrievalOptions, build_tutoring_runtime
    if args.test_double:
        service, recommender = build_service("fixture"), None
    elif args.judge is None and not args.no_jev:
        service, recommender, notes = build_tutoring_runtime("pgvector", use_jev=args.llm != "scripted")
        print("setup: " + "; ".join(notes))
    else:
        judge = None
        if args.judge not in (None, "off"):
            from retrieval_tool.jev_recommender import default_evidence_judge
            judge = default_evidence_judge()
        service = build_service("pgvector", options=RetrievalOptions(judge_mode=args.judge or "off"), judge=judge)
        recommender = None
        if not args.no_jev and args.llm != "scripted":
            from retrieval_tool.jev_recommender import default_recommender
            recommender, note = default_recommender()
            print(f"may-turn decisions: {note}")
    if args.test_double:
        print("NOTE: --test-double: retrieval is the offline stand-in, not Week 3. Use only to check the turn logic.")
    for name in (sorted(scenarios) if args.all else [args.scenario]):
        run(name, scenarios[name], service, args.llm, recommender)


if __name__ == "__main__":
    main()
