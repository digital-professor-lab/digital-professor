#!/usr/bin/env python3
"""Validate source traceability and internal consistency of the built catalog."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


from digital_professor.paths import CATALOG, resolve_source
DATA = CATALOG


def validate() -> dict[str, int]:
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(DATA / "knowledge_base.sqlite")
    conn.row_factory = sqlite3.Row
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()

    documents = {r["document_id"]: dict(r) for r in conn.execute("SELECT * FROM documents")}
    assert len(documents) == 6
    assert {r["course_id"] for r in documents.values()} == {"calc1", "number_theory_1"}
    assert all(r["review_status"] == "unverified" for r in documents.values())
    source_lines = {}
    for doc in manifest["documents"]:
        original = resolve_source(doc["source_path"]).read_bytes()
        snapshot = resolve_source(doc["snapshot_path"]).read_bytes()
        checksum = hashlib.sha256(original).hexdigest()
        assert original == snapshot and checksum == doc["sha256"]
        source_lines[doc["document_id"]] = original.decode("utf-8").splitlines()

    sections = {r["section_id"]: dict(r) for r in conn.execute("SELECT * FROM sections")}
    for sec in sections.values():
        assert 1 <= sec["start_line"] <= sec["end_line"] <= len(source_lines[sec["document_id"]])
        if sec["parent_id"]:
            parent = sections[sec["parent_id"]]
            assert parent["document_id"] == sec["document_id"]
            assert parent["start_line"] <= sec["start_line"] <= sec["end_line"] <= parent["end_line"]

    passages = {r["passage_id"]: dict(r) for r in conn.execute("SELECT * FROM passages")}
    for passage in passages.values():
        doc_id = passage["document_id"]
        sec = sections[passage["section_id"]]
        assert sec["document_id"] == doc_id
        assert sec["start_line"] <= passage["start_line"] <= passage["end_line"] <= sec["end_line"]
        window = source_lines[doc_id][passage["start_line"] - 1 : passage["end_line"]]
        expected_lines = passage["raw_latex"].splitlines()
        cursor = 0
        for expected in expected_lines:
            while cursor < len(window) and window[cursor] != expected:
                cursor += 1
            assert cursor < len(window), (passage["passage_id"], expected)
            cursor += 1

    concepts = {r["concept_id"]: dict(r) for r in conn.execute("SELECT * FROM concepts")}
    links = [dict(r) for r in conn.execute("SELECT * FROM concept_evidence")]
    assert len(links) == len(concepts)
    assert {r["concept_id"] for r in links} == set(concepts)
    for link in links:
        passage = passages[link["passage_id"]]
        assert concepts[link["concept_id"]]["course_id"] == documents[passage["document_id"]]["course_id"]
        assert not passage["scope_status"].startswith("outside_pilot_course")

    for issue in conn.execute("SELECT * FROM review_issues"):
        assert 1 <= issue["source_line"] <= len(source_lines[issue["document_id"]])
    totals = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
              for table in ("courses", "documents", "sections", "passages", "concepts", "concept_evidence", "review_issues")}
    conn.close()
    return totals


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
