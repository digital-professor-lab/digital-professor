"""One-command check of the retrieval tool. Needs only numpy and jsonschema.

No Docker, API key, model download or other working tree. From the repository root:

    python research/knowledge-retrieval/retrieval-tool/scripts/smoke_check.py

It checks: imports, schema generation and validation, planner behaviour, request and failure records, the
citation check, and one stubbed retrieval turn. With --write-fixture it also rewrites
results/fixtures/stubbed_explain_turn.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
sys.path.insert(0, str(PACKAGE / "scripts"))

FIXTURE = PACKAGE / "results" / "fixtures" / "stubbed_explain_turn.json"
CHAIN = "calc1.03-derivatives.chain-rule"
SNAPSHOT = "snap.calc1.dev-ai-breakdown.1"
TOOL_ARGS = {"query": "chain rule for composite functions", "purpose": "answer_grounding", "concept_id": CHAIN,
             "evidence_needs": [{"need_type": "theorem_statement", "description": "Statement of the chain rule",
                                 "anchor": "chain rule"}]}


def check(name: str, passed: bool, detail: str = "") -> None:
    print(f"ok    {name}" if passed else f"FAIL  {name}  {detail}")
    if not passed:
        raise SystemExit(1)


def turn_context(**overrides):
    from retrieval_tool import TurnContext
    return TurnContext(**{**dict(course_id="calc1", session_id="smoke", turn_id="turn-1", question_id="calc1.smoke",
                                 correlation_id="corr-smoke", action_type="explain", retrieval_snapshot_id=SNAPSHOT,
                                 concept_ids=[CHAIN], course_title="Calculus I",
                                 student_message="I got cos(x^2). Why was that marked wrong?"), **overrides})


def stubbed_turn():
    from retrieval_tool import build_service, recommend_grounding, run_turn
    from retrieval_tool.llm import ScriptedLLM, answer, tool_call
    from retrieval_tool.tool_schema import build_request
    service = build_service("fixture")
    # Passages get the labels P1, P2, ... in rank order, so the reply cites the first passage that covers the need.
    preview = service.handle(build_request(TOOL_ARGS, turn_context(turn_id="preview")))
    covering = preview["need_coverage"][0]["passage_ids"][0]
    label = 1 + [p["passage_id"] for p in preview["passages"]].index(covering)
    llm = ScriptedLLM([tool_call(TOOL_ARGS), answer(f"The chain rule applies here [P{label}]. What is the inner function?")])
    return run_turn(llm, service, turn_context(), decision=recommend_grounding("explain"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-fixture", action="store_true")
    args = parser.parse_args()

    import jsonschema
    from export_schemas import rendered, schema_folder
    from retrieval_tool import build_service, recommend_grounding, verify_grounding_refs
    from retrieval_tool.backends import BackendUnavailable
    from retrieval_tool.planner import RetrievalPlanner, plan_is_usable, plan_to_request, validate_plan
    from retrieval_tool.schemas import validate_record
    from retrieval_tool.service import RetrievalService
    from retrieval_tool.tool_schema import build_request
    check("imports", True)

    files = rendered()
    for name, text in files.items():
        jsonschema.Draft202012Validator.check_schema(json.loads(text))
    check("schemas generate and are valid", len(files) == 4, str(sorted(files)))
    folder = schema_folder()
    if folder.exists():
        stale = [n for n, text in files.items() if (folder / n).read_text(encoding="utf-8") != text]
        check("schema files match the code", not stale, str(stale))
    else:
        print(f"note  {folder} not present yet; comparison skipped")

    turn = turn_context()
    decision = recommend_grounding("explain")
    planner = RetrievalPlanner.from_folder(["calc1"])
    draft = planner.draft(turn, decision)
    repaired = planner.finalize({**TOOL_ARGS, "concept_id": "calc1.99-made-up"}, draft, turn)
    check("planner keeps the question's concept", [c["concept_id"] for c in repaired["concepts"] if c["role"] == "primary"] == [CHAIN])
    check("planner records its repairs", "unknown_concept_dropped" in [r["code"] for r in repaired["repairs"]])
    check("plan is valid", plan_is_usable(repaired) and not validate_plan(repaired), str(validate_plan(repaired)))

    service = build_service("fixture")
    request = plan_to_request(repaired, turn, purpose="answer_grounding")
    check("request validates", not validate_record(request), str(validate_record(request)))
    bundle = service.handle(request)
    check("bundle validates", not validate_record(bundle), str(validate_record(bundle)))
    stop = service.handle({**request, "retrieval_snapshot_id": "snap.old"})
    check("stop record validates", stop.get("stop_reason") == "version_mismatch" and not validate_record(stop), str(stop)[:200])

    class Down:
        name, semantic_available = "down", True

        def query_facets(self, question):
            return []

        def run(self, *a, **k):
            raise BackendUnavailable("index_unavailable", "database down")

    failed = RetrievalService(Down(), service.catalog, service.policies).handle(request)
    check("index fault is `failed`, not `no_support_found`",
          failed["retrieval_status"] == "failed" and not validate_record(failed), str(failed)[:200])

    needed = next(iter(bundle["need_coverage"]))["passage_ids"][:1]
    accepted = verify_grounding_refs(needed, [bundle], session_id=turn.session_id, turn_id=turn.turn_id)
    rejected = verify_grounding_refs(["psg_made_up"], [bundle], session_id=turn.session_id, turn_id=turn.turn_id)
    check("citation check", accepted["ok"] and not rejected["ok"], str((accepted, rejected))[:200])

    result = stubbed_turn()
    check("stubbed turn searches and cites", len(result.requests) == 1 and result.citation_check.get("ok") and bool(result.grounding_refs),
          str(result.citation_check))
    for record in [*result.requests, *result.records]:
        check(f"turn {record['record_type']} validates", not validate_record(record), str(validate_record(record)))

    current = {"note": "Current records from a stubbed turn on the local fixture. Not a search-quality result.",
               "decision": result.decision, "requests": result.requests, "records": result.records,
               "grounding_refs": result.grounding_refs, "citation_check": result.citation_check}
    if args.write_fixture:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {FIXTURE}")
    print("Smoke check passed.")


if __name__ == "__main__":
    main()
