#!/usr/bin/env python3
"""Run the frozen 50-question benchmark across five retrieval configurations."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from digital_professor.retrieval.search import Retriever
from digital_professor.paths import CATALOG, EVALUATIONS, BENCHMARK, EMBEDDINGS, resolve_source
HERE = EVALUATIONS
HERE.mkdir(parents=True, exist_ok=True)


DATA = CATALOG
RUNS = HERE / "benchmark_runs"
ARMS = [
    ("bge_vector", ("bge_base_en_v1_5",), False),
    ("qwen_vector", ("qwen3_embedding_0_6b",), False),
    ("bge_hybrid", ("bge_base_en_v1_5",), True),
    ("qwen_hybrid", ("qwen3_embedding_0_6b",), True),
    ("two_model_hybrid", ("bge_base_en_v1_5", "qwen3_embedding_0_6b"), True),
]
RANKS = (1, 3, 6)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def wilson_interval(successes: int, count: int, z: float = 1.96) -> list[float]:
    if count == 0:
        return [0.0, 0.0]
    p = successes / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    half = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [round(center - half, 4), round(center + half, 4)]


def passage_covers(retrieved_id: str, gold_id: str, passages: dict[str, dict[str, Any]]) -> bool:
    retrieved, gold = passages[retrieved_id], passages[gold_id]
    return (retrieved["document_id"] == gold["document_id"]
            and retrieved["start_line"] <= gold["start_line"]
            and retrieved["end_line"] >= gold["end_line"])


def integrity_errors(result: dict[str, Any], context: str, passages: dict[str, dict[str, Any]],
                     documents: dict[str, dict[str, Any]], source_lines: dict[str, list[str]]) -> list[str]:
    errors = []
    passage = passages.get(result["passage_id"])
    if passage is None:
        return ["unknown_passage"]
    document = documents[passage["document_id"]]
    if result["filename"] != document["filename"] or result["snapshot_path"] != document["snapshot_path"]:
        errors.append("document_metadata")
    if result["line_start"] != passage["start_line"] or result["line_end"] != passage["end_line"]:
        errors.append("line_range")
    if result["raw_latex"] != passage["raw_latex"].strip():
        errors.append("altered_latex")
    if result["raw_latex"] not in context or f"[{result['citation']}]" not in context:
        errors.append("context_omission")
    path = document["snapshot_path"]
    if path not in source_lines:
        source_lines[path] = resolve_source(path).read_text(encoding="utf-8").splitlines()
    lines = source_lines[path]
    span = [line.strip() for line in lines[passage["start_line"] - 1:passage["end_line"]] if line.strip()]
    extracted = [line.strip() for line in result["raw_latex"].splitlines() if line.strip()]
    position = 0
    for line in extracted:
        while position < len(span) and span[position] != line:
            position += 1
        if position == len(span):
            errors.append("source_span_mismatch")
            break
        position += 1
    return errors


def score_case(case: dict[str, Any], report: dict[str, Any], passages: dict[str, dict[str, Any]],
               documents: dict[str, dict[str, Any]], source_lines: dict[str, list[str]]) -> dict[str, Any]:
    results = report["results"]
    seen = [row["passage_id"] for row in results]
    leaks = [row["citation"] for row in results if row["scope_status"] != "pilot_course_or_general" or row["known_issues"]]
    errors = {row["citation"]: problems for row in results
              if (problems := integrity_errors(row, report["context"], passages, documents, source_lines))}
    scored = {"id": case["id"], "course_id": case["course_id"], "difficulty": case["difficulty"],
              "kind": case["kind"], "result_count": len(results), "scope_or_issue_leaks": leaks,
              "integrity_errors": errors, "retrieval_seconds": report["retrieval_seconds"],
              "context_characters": len(report["context"]), "passage_ids": seen,
              "selection_skip_reasons": report["selection_skip_reasons"],
              "raw_excerpt_characters": report["raw_excerpt_characters"],
              "course_top3": any(row["course_id"] == case["course_id"] for row in results[:3])}
    if case["kind"] == "answerable":
        groups = [[anchor["passage_id"] for anchor in group] for group in case["required_evidence_groups"]]
        group_ranks = []
        for group in groups:
            first = next((rank for rank, retrieved_id in enumerate(seen, start=1)
                          if any(passage_covers(retrieved_id, gold_id, passages) for gold_id in group)), None)
            group_ranks.append(first)
        scored["group_first_ranks"] = group_ranks
        scored["required_group_count"] = len(groups)
        scored["any_evidence_at"] = {str(k): any(rank is not None and rank <= k for rank in group_ranks)
                                     for k in RANKS}
        scored["complete_at"] = {str(k): all(rank is not None and rank <= k for rank in group_ranks)
                                 for k in RANKS}
        scored["group_hits_at"] = {str(k): sum(rank is not None and rank <= k for rank in group_ranks)
                                   for k in RANKS}
        first_evidence = min((rank for rank in group_ranks if rank is not None), default=None)
        scored["reciprocal_rank"] = 1 / first_evidence if first_evidence else 0.0
        scored["gold_groups"] = groups
    elif case["kind"] == "scope_excluded":
        excluded = case["excluded_anchor"]["passage_id"]
        scored["excluded_anchor_returned"] = any(passage_covers(row, excluded, passages) for row in seen)
    else:
        scored["absence_reason"] = case["absence_reason"]
        scored["returned_despite_missing_fact"] = bool(results)
    return scored


def summarize(cases: list[dict[str, Any]], scored: list[dict[str, Any]], elapsed: float,
              encoding_timings: dict[str, dict[str, float]],
              single_request_samples: list[float]) -> dict[str, Any]:
    positives = [row for row in scored if row["kind"] == "answerable"]
    summary: dict[str, Any] = {"batch_wall_seconds": round(elapsed, 3),
                               "amortized_seconds_per_question": round(elapsed / len(cases), 4),
                               "encoding_timings": encoding_timings,
                               "retrieval_p50_seconds": round(percentile([r["retrieval_seconds"] for r in scored], .5), 4),
                               "retrieval_p95_seconds": round(percentile([r["retrieval_seconds"] for r in scored], .95), 4),
                               "mean_context_characters": round(statistics.mean(r["context_characters"] for r in scored)),
                               "single_request_samples_seconds": [round(value, 3) for value in single_request_samples],
                               "single_request_p95_seconds": round(percentile(single_request_samples, .95), 3),
                               "returned_passages": sum(r["result_count"] for r in scored),
                               "questions_with_fewer_than_six_results": sum(r["result_count"] < 6 for r in scored),
                               "selection_skips": dict(Counter({reason: sum(r["selection_skip_reasons"][reason]
                                                                       for r in scored)
                                                                 for reason in ("broad_lexical_only", "document_cap", "context_budget")})),
                               "scope_or_issue_leaks": sum(len(r["scope_or_issue_leaks"]) for r in scored),
                               "integrity_failures": sum(len(r["integrity_errors"]) for r in scored)}
    summary["course_routing_at3"] = round(sum(r["course_top3"] for r in positives) / len(positives), 4)
    summary["mrr"] = round(statistics.mean(r["reciprocal_rank"] for r in positives), 4)
    total_groups = sum(r["required_group_count"] for r in positives)
    for k in RANKS:
        key = str(k)
        summary[f"group_recall_at{k}"] = round(sum(r["group_hits_at"][key] for r in positives) / total_groups, 4)
        successes = sum(r["complete_at"][key] for r in positives)
        summary[f"complete_at{k}"] = round(successes / len(positives), 4)
        summary[f"complete_at{k}_wilson95"] = wilson_interval(successes, len(positives))
        summary[f"any_evidence_at{k}"] = round(sum(r["any_evidence_at"][key] for r in positives) / len(positives), 4)
    slices = {}
    for label, subset in ((course, [r for r in positives if r["course_id"] == course])
                          for course in ("calc1", "number_theory_1")):
        slices[label] = {"questions": len(subset), "complete_at6": round(statistics.mean(r["complete_at"]["6"] for r in subset), 4),
                         "group_recall_at6": round(sum(r["group_hits_at"]["6"] for r in subset) /
                                                   sum(r["required_group_count"] for r in subset), 4)}
    for difficulty in ("easy", "medium", "hard"):
        subset = [r for r in positives if r["difficulty"] == difficulty]
        slices[difficulty] = {"questions": len(subset), "complete_at6": round(statistics.mean(r["complete_at"]["6"] for r in subset), 4),
                              "group_recall_at6": round(sum(r["group_hits_at"]["6"] for r in subset) /
                                                        sum(r["required_group_count"] for r in subset), 4)}
    summary["slices"] = slices
    role_groups = defaultdict(lambda: [0, 0])
    for case, row in zip(cases, scored):
        if case["kind"] != "answerable":
            continue
        for index, group in enumerate(case["required_evidence_groups"]):
            role = group[0]["source_type"]
            role_groups[role][0] += int(row["group_first_ranks"][index] is not None
                                        and row["group_first_ranks"][index] <= 6)
            role_groups[role][1] += 1
    summary["source_role_group_recall_at6"] = {
        role: {"hits": hits, "total": total, "recall": round(hits / total, 4)}
        for role, (hits, total) in role_groups.items()
    }
    multi = [row for row in positives if row["required_group_count"] > 1]
    summary["multi_evidence_complete_at6"] = round(statistics.mean(row["complete_at"]["6"] for row in multi), 4)
    summary["multi_evidence_questions"] = len(multi)
    summary["scope_challenges_returned"] = sum(r.get("excluded_anchor_returned", False) for r in scored)
    summary["absent_questions_with_results"] = sum(r.get("returned_despite_missing_fact", False) for r in scored)
    return summary


def render_report(metadata: dict[str, Any], summaries: dict[str, dict[str, Any]],
                  scored_by_arm: dict[str, list[dict[str, Any]]]) -> str:
    lines = ["# Fifty-Question Retrieval Benchmark", "", f"Dataset version: {metadata['dataset_version']}", "",
             f"Run time (UTC): {metadata['run_time_utc']}", "",
             f"Frozen dataset SHA-256: `{metadata['dataset_sha256']}`", "",
             "The same 50 English questions were run through five configurations. Labels are source-anchored silver labels, "
             "not instructor-approved relevance judgments. See [the framework](evaluation_framework.md) and "
             "[the full question set](benchmark_50.jsonl).", "",
             "## Main results", "",
             "| Arm | Group recall@6 | Complete@6 | Any@6 | MRR | Route@3 | Hard complete@6 | Batch seconds | DB p95 seconds | Single p95 seconds* |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, _, _ in ARMS:
        s = summaries[name]
        lines.append(f"| {name} | {s['group_recall_at6']:.3f} | {s['complete_at6']:.3f} | "
                     f"{s['any_evidence_at6']:.3f} | {s['mrr']:.3f} | {s['course_routing_at3']:.3f} | "
                     f"{s['slices']['hard']['complete_at6']:.3f} | {s['batch_wall_seconds']:.2f} | "
                     f"{s['retrieval_p95_seconds']:.3f} | {s['single_request_p95_seconds']:.2f} |")
    lines.extend(["", "The batch time includes local model loading, batched query encoding, and 50 sequential database searches. "
                  "DB p95 covers retrieval/assembly only; it excludes embedding. *Single p95 is the interpolated 95th "
                  "percentile of only three sequential single-question runs per arm; it is indicative, not a production SLA. "
                  "Batch times are affected by model-cache warm-up and fixed run order.", "",
                  f"The two-model complete@6 Wilson 95% interval is "
                  f"{summaries['two_model_hybrid']['complete_at6_wilson95']}; this reflects sampling of 46 "
                  "silver-labeled answerable questions, not uncertainty about instructor correctness.", "",
                  "## Depth and safety", "",
                  "| Arm | Group recall@1 | Group recall@3 | Complete@1 | Complete@3 | Scope/issue leaks | Source integrity failures |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for name, _, _ in ARMS:
        s = summaries[name]
        lines.append(f"| {name} | {s['group_recall_at1']:.3f} | {s['group_recall_at3']:.3f} | "
                     f"{s['complete_at1']:.3f} | {s['complete_at3']:.3f} | "
                     f"{s['scope_or_issue_leaks']} | {s['integrity_failures']} |")
    lines.extend(["", "## Per-course and difficulty slices", "",
                  "| Arm | Calculus complete@6 | Number Theory complete@6 | Easy | Medium | Hard |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for name, _, _ in ARMS:
        sl = summaries[name]["slices"]
        lines.append(f"| {name} | {sl['calc1']['complete_at6']:.3f} | "
                     f"{sl['number_theory_1']['complete_at6']:.3f} | {sl['easy']['complete_at6']:.3f} | "
                     f"{sl['medium']['complete_at6']:.3f} | {sl['hard']['complete_at6']:.3f} |")
    lines.extend(["", "## Source role, multi-evidence, and context packing", "",
                  "| Arm | Syllabus group recall | Context group recall | Textbook-reference group recall | Multi-evidence complete@6 | Budget skips | File-cap skips | <6 results |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for name, _, _ in ARMS:
        s = summaries[name]
        roles = s["source_role_group_recall_at6"]
        def display_role(role: str) -> str:
            value = roles.get(role, {"hits": 0, "total": 0, "recall": 0})
            return f"{value['recall']:.3f} ({value['hits']}/{value['total']})"
        lines.append(f"| {name} | {display_role('syllabus')} | "
                     f"{display_role('context')} | "
                     f"{display_role('textbook_reference')} | "
                     f"{s['multi_evidence_complete_at6']:.3f} | "
                     f"{s['selection_skips']['context_budget']} | {s['selection_skips']['document_cap']} | "
                     f"{s['questions_with_fewer_than_six_results']} |")
    lines.extend(["", "Role recall uses the first annotated source role for each required group; one group may have "
                  "acceptable alternatives. Budget and file-cap skips count rejected candidates, not necessarily lost gold evidence.", ""])
    lines.extend(["", "## Production-arm failures", ""])
    failures = [r for r in scored_by_arm["two_model_hybrid"] if r["kind"] == "answerable" and not r["complete_at"]["6"]]
    if failures:
        for row in failures:
            lines.append(f"- **{row['id']}** ({row['course_id']}, {row['difficulty']}): "
                         f"required groups first found at ranks {row['group_first_ranks']}; "
                         f"retrieved passages: {', '.join(row['passage_ids']) or 'none'}.")
    else:
        lines.append("- None in the 46 answerable questions.")
    prod = summaries["two_model_hybrid"]
    gates = {"group_recall_at6 >= 0.85": prod["group_recall_at6"] >= .85,
             "complete_at6 >= 0.75": prod["complete_at6"] >= .75,
             "hard_complete_at6 >= 0.60": prod["slices"]["hard"]["complete_at6"] >= .60,
             "course_routing_at3 >= 0.95": prod["course_routing_at3"] >= .95,
             "scope_and_issue_leaks = 0": prod["scope_or_issue_leaks"] == 0,
             "citation_integrity_failures = 0": prod["integrity_failures"] == 0}
    lines.extend(["", "## Pilot gate check", ""])
    for gate, passed in gates.items():
        lines.append(f"- {gate}: {'PASS' if passed else 'FAIL'}")
    lines.extend(["", f"The production arm passes {sum(gates.values())}/{len(gates)} retrieval pilot gates. "
                  "These gates do not override the unverified status of the source materials.", "",
                  "## Negative and scope challenges", ""])
    for name, _, _ in ARMS:
        s = summaries[name]
        lines.append(f"- `{name}`: {s['scope_challenges_returned']}/2 excluded anchors leaked; "
                     f"{s['absent_questions_with_results']}/2 absent-information questions still returned snippets.")
    lines.extend(["", "Explicit-request guards now return Not found for selected excluded scopes and unavailable source types. "
                  "They are not a calibrated semantic abstention policy. "
                  "Returning a topical passage for an absent fact is not evidence that the fact exists. "
                  "The answer prompt asks the LLM to say when evidence is insufficient, but answer behavior has not been tested. "
                  "General evidence sufficiency and answer behavior remain unvalidated despite the retrieval gates above passing.", "",
                  "## Interpretation and limits", "",
                  "- Version 1 was archived after a source-role coverage audit; version 2 rebalanced the dataset before its run. "
                  "The archived version-1 metrics are a separate benchmark and cannot be compared as if the dataset were unchanged.",
                  "- Gold groups were selected from supplied passages before running the models. Other valid passages may exist; "
                  "the numbers measure source-anchor coverage, not exhaustive human relevance.",
                  "- Content interruption is measured by missing required evidence groups and by exact source/context integrity. "
                  "A correct answer may still need facts absent from these course outlines.",
                  "- Precision@k and nDCG are deliberately withheld until a blind, pooled relevance review labels all top candidates.",
                  "- This is a local, sequential, batched run on a two-course, 476-vector corpus. It is not a concurrency, "
                  "large-corpus, or end-to-end answer-generation benchmark.",
                  "- Recommended next work: instructor adjudication of the 50 questions and sources, a calibrated "
                  "insufficient-evidence/abstention policy, and answer-grounding tests after the LLM is connected.", ""])
    return "\n".join(lines)


def main() -> None:
    RUNS.mkdir(exist_ok=True)
    benchmark_path = BENCHMARK / 'benchmark_50.jsonl'
    benchmark_manifest = json.loads((BENCHMARK / 'benchmark_manifest.json').read_text(encoding="utf-8"))
    digest = hashlib.sha256(benchmark_path.read_bytes()).hexdigest()
    assert digest == benchmark_manifest["dataset_sha256"], "Benchmark changed after freezing"
    assert hashlib.sha256((DATA / "manifest.json").read_bytes()).hexdigest() == benchmark_manifest["source_manifest_sha256"]
    cases = load_jsonl(benchmark_path)
    assert len(cases) == 50
    passages = {row["passage_id"]: row for row in load_jsonl(DATA / "passages.jsonl")}
    documents = {row["document_id"]: row for row in load_jsonl(DATA / "documents.jsonl")}
    source_lines: dict[str, list[str]] = {}
    summaries, scored_by_arm = {}, {}
    questions = [case["question"] for case in cases]

    for name, models, use_lexical in ARMS:
        start = time.perf_counter()
        with Retriever(models=models) as retriever:
            reports = retriever.search_many(questions, use_lexical=use_lexical, top_k=6,
                                            candidate_limit=40, context_chars=12000)
            timings = retriever.last_encoding_timings
        elapsed = time.perf_counter() - start
        assert len(reports) == 50
        with (RUNS / f"{name}.jsonl").open("w", encoding="utf-8") as stream:
            for case, report in zip(cases, reports):
                stream.write(json.dumps({"id": case["id"], "report": report}, ensure_ascii=False) + "\n")
        scored = [score_case(case, report, passages, documents, source_lines)
                  for case, report in zip(cases, reports)]
        scored_by_arm[name] = scored
        single_samples = []
        for case_index in (0, 17, 42):
            single_start = time.perf_counter()
            with Retriever(models=models) as retriever:
                retriever.search_many([questions[case_index]], use_lexical=use_lexical,
                                      top_k=6, candidate_limit=40, context_chars=12000)
            single_samples.append(time.perf_counter() - single_start)
        summaries[name] = summarize(cases, scored, elapsed, timings, single_samples)
        print(f"{name}: complete@6={summaries[name]['complete_at6']:.3f}, "
              f"group recall@6={summaries[name]['group_recall_at6']:.3f}, elapsed={elapsed:.1f}s", flush=True)

    input_manifest = json.loads((EMBEDDINGS / "input_manifest.json").read_text(encoding="utf-8"))
    metadata = {"run_time_utc": datetime.now(timezone.utc).isoformat(),
                "dataset_version": benchmark_manifest["version"],
                "previous_dataset_sha256": benchmark_manifest["previous_dataset_sha256"],
                "dataset_sha256": digest,
                "source_manifest_sha256": benchmark_manifest["source_manifest_sha256"],
                "embedding_input_sha256": input_manifest["shared_input_sha256"],
                "model_revisions": {key: spec["revision"] for key, spec in input_manifest["models"].items()},
                "python": platform.python_version(), "platform": platform.platform(),
                "settings": {"top_k": 6, "candidate_limit": 40, "context_chars": 12000,
                             "max_per_document": 4, "document_limit_mode": "soft",
                             "explicit_request_guards": True,
                             "decompose_query": True, "request_policy_version": "2",
                             "scope": "pilot_course_or_general", "include_flagged": False}}
    output = {"metadata": metadata, "summaries": summaries, "cases": scored_by_arm}
    (HERE / "benchmark_results.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    (HERE / "benchmark_report.md").write_text(render_report(metadata, summaries, scored_by_arm), encoding="utf-8")
    print(json.dumps({"results": str(HERE / "benchmark_results.json"),
                      "report": str(HERE / "benchmark_report.md")}, indent=2))


if __name__ == "__main__":
    main()
