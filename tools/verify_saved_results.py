"""Verify saved output against relocated sources; do not rerun retrieval."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from digital_professor.paths import BENCHMARK, CATALOG, EVALUATIONS, PROJECT_ROOT
from digital_professor.retrieval.report_contract import validate_report_contract


def load(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def verify():
    manifest = json.loads((BENCHMARK / "benchmark_manifest.json").read_text())
    assert hashlib.sha256((BENCHMARK / "benchmark_50.jsonl").read_bytes()).hexdigest() == manifest["dataset_sha256"]
    assert hashlib.sha256((CATALOG / "manifest.json").read_bytes()).hexdigest() == manifest["source_manifest_sha256"]
    cases = {x["id"]: x for x in load(BENCHMARK / "benchmark_50.jsonl")}
    passages = {x["passage_id"]: x for x in load(CATALOG / "passages.jsonl")}
    documents = {x["document_id"]: x for x in load(CATALOG / "documents.jsonl")}
    rows = load(EVALUATIONS / "refinement_runs/facets_6.jsonl")
    assert len(rows) == len(cases) == 50
    assert {x["id"] for x in rows} == set(cases)
    positives = negatives = hits = 0
    for row in rows:
        case, report = cases[row["id"]], row["report"]
        validate_report_contract(report)
        assert report["question"] == case["question"]
        for hit in report["results"]:
            passage = passages[hit["passage_id"]]
            document = documents[passage["document_id"]]
            assert hit["filename"] == document["filename"]
            assert Path(hit["snapshot_path"]).name == document["filename"]
            assert hit["course_id"] == document["course_id"]
            assert hit["source_type"] == document["source_type"]
            assert hit["scope_status"] == passage["scope_status"] == "pilot_course_or_general"
            assert hit["review_status"] == document["review_status"]
            assert (hit["line_start"], hit["line_end"]) == (passage["start_line"], passage["end_line"])
            assert hit["raw_latex"] == passage["raw_latex"].strip()
            assert hit["raw_latex"] in report["context"] and f"[{hit['citation']}]" in report["context"]
            source = (PROJECT_ROOT / document["snapshot_path"]).read_text().splitlines()
            window = source[passage["start_line"] - 1:passage["end_line"]]
            cursor = 0
            for line in passage["raw_latex"].splitlines():
                while cursor < len(window) and window[cursor] != line:
                    cursor += 1
                assert cursor < len(window)
                cursor += 1
            hits += 1
        if case["kind"] == "answerable":
            assert report["status"] == "found"
            selected = [passages[x["passage_id"]] for x in report["results"]]
            for group in case["required_evidence_groups"]:
                assert any(
                    candidate["document_id"] == passages[gold]["document_id"]
                    and candidate["start_line"] <= passages[gold]["start_line"]
                    and candidate["end_line"] >= passages[gold]["end_line"]
                    for candidate in selected for gold in [anchor["passage_id"] for anchor in group]
                ), row["id"]
            positives += 1
        else:
            assert report["status"] == "not_found"
            assert not report["results"] and not report["context"] and report["not_found_reason"]
            negatives += 1
    assert positives == 46 and negatives == 4
    return {"mode": "offline_saved_output_verification_not_fresh_retrieval", "questions": len(rows),
            "complete_answerable": positives, "not_found_challenges": negatives, "source_hits_checked": hits}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
