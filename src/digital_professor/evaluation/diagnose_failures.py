#!/usr/bin/env python3
"""Locate whether production-arm evidence misses occur before or after candidate retrieval."""

from __future__ import annotations

import json

from .run_benchmark import DATA, HERE, load_jsonl, passage_covers
from digital_professor.paths import BENCHMARK
from digital_professor.retrieval.search import Retriever, lexical_or_query


def main() -> None:
    cases = {case["id"]: case for case in load_jsonl(BENCHMARK / 'benchmark_50.jsonl')}
    saved = json.loads((HERE / "benchmark_results.json").read_text(encoding="utf-8"))
    scored = [row for row in saved["cases"]["two_model_hybrid"]
              if row["kind"] == "answerable" and not row["complete_at"]["6"]]
    passages = {row["passage_id"]: row for row in load_jsonl(DATA / "passages.jsonl")}
    documents = {row["document_id"]: row for row in load_jsonl(DATA / "documents.jsonl")}
    questions = [cases[row["id"]]["question"] for row in scored]
    lines = ["# Production-Arm Failure Diagnostics", "",
             "This analysis uses the frozen version-2 questions and reruns only the six failed questions. "
             "It checks whether required source passages entered any of the four top-40 candidate channels. "
             "A missing silver anchor can still have a semantically valid alternative elsewhere.", ""]
    with Retriever() as retriever:
        vectors = retriever._encode_questions(questions)
        filter_sql, filter_params = retriever._filters(None, ["pilot_course_or_general"], False)
        for index, row in enumerate(scored):
            case = cases[row["id"]]
            question = case["question"]
            channels = {}
            for model_key in retriever.models:
                channels[model_key] = retriever._vector_channel(
                    model_key, vectors[model_key][index], filter_sql, filter_params, 40)
            channels["lexical_exact"] = retriever._lexical_channel(question, filter_sql, filter_params, 40)
            channels["lexical_broad"] = retriever._lexical_channel(
                lexical_or_query(question), filter_sql, filter_params, 40)
            record_ids = list(dict.fromkeys(record_id for ids in channels.values() for record_id in ids))
            hydrated = retriever._hydrate(record_ids)
            candidate_passages = {entry["passage_id"] for entry in hydrated.values()}
            selected_passages = row["passage_ids"]
            lines.extend([f"## {row['id']}: {question}", ""])
            for group_number, group in enumerate(case["required_evidence_groups"], start=1):
                if row["group_first_ranks"][group_number - 1] is not None:
                    continue
                gold = [anchor["passage_id"] for anchor in group]
                matching_candidates = [passage_id for passage_id in candidate_passages
                                       if any(passage_covers(passage_id, anchor, passages) for anchor in gold)]
                if not matching_candidates:
                    reason = "candidate-generation miss"
                else:
                    gold_documents = {passages[anchor]["document_id"] for anchor in gold}
                    selected_in_same_document = sum(passages[passage_id]["document_id"] in gold_documents
                                                    for passage_id in selected_passages)
                    reason = ("candidate found; two excerpts from the same document were already selected (file-cap pressure)"
                              if selected_in_same_document >= 2 else
                              "candidate found; lost during ranking or final selection")
                sources = [f"{documents[passages[anchor]['document_id']]['filename']}:"
                           f"{passages[anchor]['start_line']}-{passages[anchor]['end_line']}" for anchor in gold]
                lines.append(f"- Evidence group {group_number}: {reason}. Gold anchor(s): {', '.join(sources)}. "
                             f"Candidate passages covering an anchor: {len(matching_candidates)}.")
            lines.append("")
    (HERE / "failure_diagnostics.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"failed_questions": len(scored), "report": str(HERE / "failure_diagnostics.md")}, indent=2))


if __name__ == "__main__":
    main()
