#!/usr/bin/env python3
"""Compare hard/soft file limits without replacing the frozen Week 3 results."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from .run_benchmark import DATA, HERE, load_jsonl, score_case, summarize
from digital_professor.paths import BENCHMARK
from digital_professor.retrieval.search import Retriever, SOFT_FILE_EXCESS_FACTOR


def main() -> None:
    cases = load_jsonl(BENCHMARK / 'benchmark_50.jsonl')
    manifest = json.loads((BENCHMARK / 'benchmark_manifest.json').read_text())
    digest = hashlib.sha256((BENCHMARK / 'benchmark_50.jsonl').read_bytes()).hexdigest()
    assert digest == manifest["dataset_sha256"]
    assert hashlib.sha256((DATA / "manifest.json").read_bytes()).hexdigest() == manifest["source_manifest_sha256"]
    passages = {r["passage_id"]: r for r in load_jsonl(DATA / "passages.jsonl")}
    documents = {r["document_id"]: r for r in load_jsonl(DATA / "documents.jsonl")}
    output_dir = HERE / "policy_update_runs"
    output_dir.mkdir(exist_ok=True)
    summaries, scored_arms = {}, {}
    baseline = json.loads((HERE / "benchmark_results.json").read_text())
    baseline_cases = {r["id"]: r for r in baseline["cases"]["two_model_hybrid"]}
    with Retriever() as retriever:
        # Encode once so all six arms use identical query vectors.
        vectors = retriever._encode_questions([case["question"] for case in cases])
        encoding_timings = retriever.last_encoding_timings
        for mode in ("hard", "soft"):
            for limit in (2, 4, 5):
                name = f"{mode}_{limit}"
                start = time.perf_counter()
                reports = []
                for index, case in enumerate(cases):
                    query_start = time.perf_counter()
                    report = retriever._search_with_vectors(
                        case["question"], {key: values[index] for key, values in vectors.items()},
                        course_id=None, include_unconfirmed=False, include_outside_course=False,
                        include_flagged=False, top_k=6, candidate_limit=40,
                        context_chars=12000, use_lexical=True, max_per_document=limit,
                        document_limit_mode=mode,
                    )
                    report["retrieval_seconds"] = time.perf_counter() - query_start
                    reports.append(report)
                elapsed = time.perf_counter() - start
                scored = [score_case(case, report, passages, documents, {})
                          for case, report in zip(cases, reports)]
                summary = summarize(cases, scored, elapsed, encoding_timings, [])
                summary["fixed_vs_original"] = [r["id"] for r in scored if r["kind"] == "answerable"
                    and r["complete_at"]["6"] and not baseline_cases[r["id"]]["complete_at"]["6"]]
                summary["regressed_vs_original"] = [r["id"] for r in scored if r["kind"] == "answerable"
                    and not r["complete_at"]["6"] and baseline_cases[r["id"]]["complete_at"]["6"]]
                summary["challenge_not_found"] = {
                    case["id"]: {"status": report["status"], "reason": report["not_found_reason"]}
                    for case, report in zip(cases, reports) if case["kind"] != "answerable"
                }
                summary["answerable_not_found"] = [case["id"] for case, report in zip(cases, reports)
                    if case["kind"] == "answerable" and report["status"] == "not_found"]
                summaries[name], scored_arms[name] = summary, scored
                (output_dir / f"{name}.jsonl").write_text("".join(
                    json.dumps({"id": case["id"], "report": report}, ensure_ascii=False) + "\n"
                    for case, report in zip(cases, reports)))
                print(f"{name}: complete@6={summary['complete_at6']:.3f}; "
                      f"regressions={summary['regressed_vs_original']}; "
                      f"false Not found={summary['answerable_not_found']}", flush=True)
    output = {
        "metadata": {"run_time_utc": datetime.now(timezone.utc).isoformat(),
                     "dataset_sha256": digest, "top_k": 6, "context_chars": 12000,
                     "candidate_limit": 40, "soft_excess_factor": SOFT_FILE_EXCESS_FACTOR,
                     "encoding_timings": encoding_timings,
                     "limits": "Post-hoc same-set comparison; source-anchored silver labels, not instructor review. "
                               "All arms include new explicit-request guards; original artifacts are preserved. "
                               "Batch timings exclude shared query encoding and are not end-to-end latency."},
        "summaries": summaries, "cases": scored_arms,
    }
    (HERE / "policy_update_results.json").write_text(json.dumps(output, indent=2) + "\n")
    lines = ["# Retrieval Policy Update", "",
             "Same frozen Week 3 version-2 dataset; all six arms use the new explicit-request guards. "
             "This is a post-hoc diagnostic comparison, not independent validation.", "",
             "Soft limits reduce priority by 5% for each selection above the preferred count, "
             "but never discard a candidate solely because its file reached that count. "
             "This is a concentration heuristic, not an evidence-completeness judge.", "",
             "| Mode / file preference | Complete@6 | Group recall@6 | Fixed | Regressed | False Not found |",
             "| --- | ---: | ---: | --- | --- | --- |"]
    for name, s in summaries.items():
        lines.append(f"| {name} | {s['complete_at6']:.3f} | {s['group_recall_at6']:.3f} | "
                     f"{', '.join(s['fixed_vs_original']) or 'none'} | "
                     f"{', '.join(s['regressed_vs_original']) or 'none'} | "
                     f"{', '.join(s['answerable_not_found']) or 'none'} |")
    lines += ["", "## Explicit Not found cases", ""]
    for case_id, result in summaries["soft_4"]["challenge_not_found"].items():
        lines.append(f"- {case_id}: {result['status']} / {result['reason']}")
    lines += ["", "## Limits", "",
              "Not found guards match explicit requests for excluded courses/semesters and unavailable "
              "lecture/student records. They do not certify general semantic answerability. "
              "Found means passages were returned, not that they prove an answer. "
              "Sources remain unverified; top-6 and the context budget can still omit necessary evidence.", ""]
    (HERE / "policy_update_report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
