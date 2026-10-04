#!/usr/bin/env python3
"""Post-hoc test of whether the per-document cap causes multi-evidence misses."""

from __future__ import annotations

import json
import time

from .run_benchmark import DATA, HERE, load_jsonl, score_case, summarize
from digital_professor.paths import BENCHMARK
from digital_professor.retrieval.search import Retriever


def main() -> None:
    cases = load_jsonl(BENCHMARK / 'benchmark_50.jsonl')
    saved = json.loads((HERE / "benchmark_results.json").read_text(encoding="utf-8"))
    baseline = saved["summaries"]["two_model_hybrid"]
    passages = {row["passage_id"]: row for row in load_jsonl(DATA / "passages.jsonl")}
    documents = {row["document_id"]: row for row in load_jsonl(DATA / "documents.jsonl")}
    start = time.perf_counter()
    with Retriever() as retriever:
        reports = retriever.search_many([case["question"] for case in cases], max_per_document=4,
                                        top_k=6, candidate_limit=40, context_chars=12000,
                                        document_limit_mode="hard")
        timings = retriever.last_encoding_timings
    elapsed = time.perf_counter() - start
    source_lines: dict[str, list[str]] = {}
    scored = [score_case(case, report, passages, documents, source_lines)
              for case, report in zip(cases, reports)]
    alternative = summarize(cases, scored, elapsed, timings, [])
    baseline_cases = {row["id"]: row for row in saved["cases"]["two_model_hybrid"]}
    fixed = [row["id"] for row in scored if row["kind"] == "answerable" and row["complete_at"]["6"]
             and not baseline_cases[row["id"]]["complete_at"]["6"]]
    regressed = [row["id"] for row in scored if row["kind"] == "answerable" and not row["complete_at"]["6"]
                 and baseline_cases[row["id"]]["complete_at"]["6"]]
    output = {"dataset_sha256": saved["metadata"]["dataset_sha256"],
              "change": "max_per_document: 2 -> 4 (hard); current explicit-request guards enabled",
              "baseline_complete_at6": baseline["complete_at6"],
              "alternative_complete_at6": alternative["complete_at6"],
              "baseline_group_recall_at6": baseline["group_recall_at6"],
              "alternative_group_recall_at6": alternative["group_recall_at6"],
              "fixed_questions": fixed, "regressed_questions": regressed,
              "baseline_mean_context_characters": baseline["mean_context_characters"],
              "alternative_mean_context_characters": alternative["mean_context_characters"],
              "alternative_scope_or_issue_leaks": alternative["scope_or_issue_leaks"],
              "alternative_integrity_failures": alternative["integrity_failures"],
              "alternative_context_budget_skips": alternative["selection_skips"]["context_budget"]}
    (HERE / "file_cap_ablation.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    lines = ["# Post-Hoc File-Cap Ablation", "",
             "This is a diagnostic experiment on the same frozen version-2 questions. It was designed after inspecting "
             "the primary benchmark failures and is **not** part of the predeclared five-arm comparison.", "",
             "This rerun uses hard-4 selection and the current explicit-request guards, compared with the saved "
             "historical hard-2 baseline. Top-k remains 6 and the raw-excerpt budget remains 12,000 characters. "
             "Negative-case behavior is therefore affected by more than the file-cap change; "
             "use evaluate_policy_update.py for a comparison with the guards held constant.", "",
             f"- Complete evidence@6: {baseline['complete_at6']:.3f} -> {alternative['complete_at6']:.3f}.",
             f"- Required-group recall@6: {baseline['group_recall_at6']:.3f} -> {alternative['group_recall_at6']:.3f}.",
             f"- Newly completed questions: {', '.join(fixed) or 'none'}.",
             f"- Regressed questions: {', '.join(regressed) or 'none'}.",
             f"- Mean assembled context characters: {baseline['mean_context_characters']} -> "
             f"{alternative['mean_context_characters']}.",
             f"- Alternative scope/issue leaks: {alternative['scope_or_issue_leaks']}; "
             f"source integrity failures: {alternative['integrity_failures']}.", "",
             "A larger context and more passages from one document can increase noise and cost. This result does not "
             "justify changing the production default without instructor relevance judgments and answer-level evaluation.", ""]
    (HERE / "file_cap_ablation.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
