#!/usr/bin/env python3
"""Run a small, source-inspected retrieval check across both pilot courses."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from digital_professor.retrieval.search import Retriever
from digital_professor.paths import EVALUATIONS, BENCHMARK, resolve_source
HERE = EVALUATIONS
HERE.mkdir(parents=True, exist_ok=True)


CASES = [
    ("How is the derivative used to model the growth of a biological population?", "calc1"),
    ("What does the Fundamental Theorem of Calculus say about accumulation and integration?", "calc1"),
    ("What is a Dedekind domain, and why do fractional ideals matter?", "number_theory_1"),
    ("How do ramification and residue degree describe primes in a number field extension?", "number_theory_1"),
    ("How many prime ideals lie above 2 in the cyclotomic field Q(zeta_7)?", "number_theory_1"),
]


def main() -> None:
    with Retriever() as retriever:
        reports = retriever.search_many([question for question, _ in CASES], top_k=5)
        issues = retriever.conn.execute(
            "SELECT d.filename, issue.source_line FROM review_issues issue "
            "JOIN documents d ON d.document_id = issue.document_id WHERE issue.status <> 'resolved'"
        ).fetchall()
    with Retriever(models=("bge_base_en_v1_5",)) as retriever:
        unconfirmed_report = retriever.search_many(
            ["How are adeles and ideles studied in the second semester?"],
            include_unconfirmed=True, top_k=8,
        )[0]
        flagged_report = retriever.search_many(
            ["In Q(zeta_7), how many primes lie over 2 and what is the residue degree?"],
            include_flagged=True, top_k=10,
        )[0]
    unconfirmed_visible = any(result["scope_status"] == "second_semester_scope_unconfirmed"
                              for result in unconfirmed_report["results"])
    issue_visible_with_opt_in = any(result["known_issues"] for result in flagged_report["results"])
    assert unconfirmed_visible, "Opted-in second-semester material did not surface"
    assert issue_visible_with_opt_in, "Opted-in known issue was not labeled"

    lines = ["# Retrieval Pilot Evaluation", "",
             f"Run time (UTC): {datetime.now(timezone.utc).isoformat()}", "",
             "This is a five-question smoke test of cross-course routing, source citation, and the known-issue filter. "
             "It is not a measured relevance benchmark or an instructor accuracy review.", ""]
    case_results = []
    for (question, expected_course), report in zip(CASES, reports):
        results = report["results"]
        top_three = results[:3]
        course_hit = any(result["course_id"] == expected_course for result in top_three)
        flagged_leak = any(result["filename"] == issue["filename"] and
                           result["line_start"] <= issue["source_line"] <= result["line_end"]
                           for result in results for issue in issues)
        citation_valid = all(resolve_source(result["snapshot_path"]).exists() and result["line_start"] <= result["line_end"]
                             and result["citation"] == f"S{index + 1}"
                             for index, result in enumerate(results))
        assert course_hit, f"Expected course absent from top 3: {question}"
        assert not flagged_leak, f"Known issue surfaced: {question}"
        assert citation_valid, f"Invalid citation: {question}"
        assert all(result["scope_status"] == "pilot_course_or_general" for result in results)
        lines.extend([f"## {question}", "", f"Expected course in top 3: `{expected_course}` — passed", "",
                      "| Rank | Course | Source | Lines | Section |", "| ---: | --- | --- | --- | --- |"])
        for index, result in enumerate(results, start=1):
            section = result["section_path"].replace("|", "\\|")[:90]
            lines.append(f"| {index} | {result['course_id']} | {result['filename']} | "
                         f"{result['line_start']}-{result['line_end']} | {section} |")
        lines.append("")
        case_results.append({
            "question": question, "expected_course": expected_course,
            "course_in_top_three": course_hit, "known_issue_excluded": not flagged_leak,
            "citations_valid": citation_valid,
            "top_sources": [{key: result[key] for key in ("course_id", "filename", "line_start", "line_end", "section_path")}
                            for result in results],
        })
    lines.extend(["## Scope and issue opt-in checks", "",
                  f"- Unconfirmed second-semester material appears only when requested: {unconfirmed_visible}.",
                  f"- The known issue is labeled when explicitly included: {issue_visible_with_opt_in}.", "",
                  "## Limits", "", "- The supplied source files are AI-prepared and unverified.",
                  "- Some passages are course outlines, so a relevant hit may still lack enough detail to answer.",
                  "- A larger instructor-labeled question set is needed to measure recall, precision, and answer grounding.", ""])
    (HERE / "evaluation_report.md").write_text("\n".join(lines), encoding="utf-8")
    (HERE / "evaluation_results.json").write_text(json.dumps(case_results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(case_results), "passed": len(case_results),
                      "unconfirmed_opt_in": unconfirmed_visible,
                      "known_issue_opt_in": issue_visible_with_opt_in,
                      "report": str(HERE / "evaluation_report.md")}, indent=2))


if __name__ == "__main__":
    main()
