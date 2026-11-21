"""Syllabus scope: only the textbook sections a syllabus lists are ingested."""

from __future__ import annotations

import pymupdf
import pytest

from digital_professor.course_context.ingestion import DocumentIngestionService, SourceUpload
from digital_professor.course_context.syllabus_scope import parse_syllabus_scope, plan_textbook_scope

# The layout a PDF syllabus comes out in: bullets, and the number and the title on separate lines.
SYLLABUS = """Calculus I Course Syllabus 110.106
Course Topics
• Review (2 weeks)
o
Chapter 1
• Limits
o
2.1
Limits (with formal definition from 2.3)
• Derivatives
o
3.2
The Chain Rule
o
3.9
Linear Approximation
Office hours 10.30
"""

# A book in another edition: the Chain Rule is 3.1 here, and 3.2 is something else.
TOC = [
    (1, "1 Preview", 1), (2, "1.1 Functions", 1), (2, "1.2 Graphs", 20),
    (1, "2 Limits and Continuity", 40), (2, "2.1 Limits", 40), (2, "2.2 Continuity", 50),
    (2, "2.3 A Formal Definition of Limits", 60),
    (1, "3 Differentiation", 70), (2, "3.1 The Chain Rule and Higher Derivatives", 70),
    (3, "3.1.1 The Chain Rule", 70), (3, "3.1.2 Related Rates", 75),
    (2, "3.2 Derivatives of Trigonometric Functions", 80), (2, "3.3 Linear Approximation", 90),
    (1, "4 Differential Equations", 100), (2, "4.1 Solving Differential Equations", 100),
    (2, "4.2 Equilibria", 130),
]


def _book(pages: int = 160, toc: list | None = TOC) -> bytes:
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        doc.new_page().insert_text((72, 72), f"Page {number}\nDefinition: material printed on page {number}.")
    if toc:
        doc.set_toc(toc)
    data = doc.tobytes()
    doc.close()
    return data


def test_syllabus_topic_list_is_read_from_split_lines() -> None:
    entries = parse_syllabus_scope(SYLLABUS)
    assert [e.label for e in entries] == ["Chapter 1", "2.1 Limits", "3.2 The Chain Rule",
                                          "3.9 Linear Approximation"]
    assert entries[1].references == ("2.3",)


def test_sections_are_found_by_title_not_by_number() -> None:
    plan = plan_textbook_scope(_book(), parse_syllabus_scope(SYLLABUS))
    assert plan.applied, plan.reason
    found = {m["syllabus"]: m["textbook"] for m in plan.matched}
    # "3.2 The Chain Rule" is 3.1 in this edition; 3.2 here is trigonometric derivatives and stays out.
    assert found["3.2 The Chain Rule"] == "3.1 The Chain Rule and Higher Derivatives"
    assert found["3.9 Linear Approximation"] == "3.3 Linear Approximation"
    assert found["2.1 Limits (refers to 2.3)"] == "2.3 A Formal Definition of Limits"
    assert 75 in plan.pages                       # the whole section, including related rates
    assert 85 not in plan.pages                   # 3.2 trigonometric derivatives
    assert 1 in plan.pages and 20 in plan.pages   # Chapter 1
    assert 110 not in plan.pages                  # chapter 4 is not on the syllabus
    assert not plan.unmatched


@pytest.mark.parametrize("pdf, reason", [
    (lambda: _book(toc=None), "no table of contents"),
    (lambda: _book(pages=40, toc=[row for row in TOC if row[2] <= 40]), "fewer than"),
])
def test_whole_document_is_used_when_the_scope_cannot_be_trusted(pdf, reason) -> None:
    plan = plan_textbook_scope(pdf(), parse_syllabus_scope(SYLLABUS))
    assert not plan.applied and reason in plan.reason


def test_whole_document_is_used_when_most_entries_are_missing() -> None:
    syllabus = "2.1\nTopology\n2.2\nMeasure Theory\n3.1\nThe Chain Rule\n"
    plan = plan_textbook_scope(_book(), parse_syllabus_scope(syllabus))
    assert not plan.applied and "were found" in plan.reason


def test_ingestion_reads_only_scoped_pages_and_keeps_page_numbers(monkeypatch) -> None:
    syllabus = SourceUpload("calculus_syllabus.txt", "text/plain", SYLLABUS.encode())
    book = SourceUpload("textbook.pdf", "application/pdf", _book())
    monkeypatch.delenv("DP_TEXTBOOK_SCOPE", raising=False)            # off by default: the whole book
    default = DocumentIngestionService().ingest_course([syllabus, book], syllabus=syllabus)
    assert next(d for d in default.documents if d.filename == "textbook.pdf").scope is None

    monkeypatch.setenv("DP_TEXTBOOK_SCOPE", "on")
    workspace = DocumentIngestionService().ingest_course([syllabus, book], syllabus=syllabus)
    textbook = next(d for d in workspace.documents if d.filename == "textbook.pdf")
    assert textbook.page_count == 160
    assert textbook.scope["applied"] and textbook.scope["indexed_pages"] < 160
    pages = {block.page_number for block in textbook.chunks}
    assert 75 in pages and 110 not in pages
    assert all(f"page {block.page_number}" in block.text for block in textbook.chunks if "printed on" in block.text)

    monkeypatch.setenv("DP_TEXTBOOK_SCOPE", "off")
    whole = DocumentIngestionService().ingest_course([syllabus, book], syllabus=syllabus)
    textbook = next(d for d in whole.documents if d.filename == "textbook.pdf")
    assert textbook.scope is None and 110 in {block.page_number for block in textbook.chunks}
