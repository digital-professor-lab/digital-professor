#!/usr/bin/env python3
"""Build a source-traceable course catalog from the six supplied LaTeX files.

This intentionally creates no embeddings and implements no user-query retrieval.
All derived records retain document and line provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from pathlib import Path


from digital_professor.paths import PROJECT_ROOT, SOURCES, CATALOG
HERE = PROJECT_ROOT
RESOURCE = SOURCES
OUT = CATALOG
SNAPSHOTS = OUT / "sources"

SOURCES = [
    ("calc1", "syllabus", "Calc1_Syllabus_Claude.tex"),
    ("calc1", "context", "Calc1_Content_Claude.tex"),
    ("calc1", "textbook_reference", "Calc1_Book_Claude.tex"),
    ("number_theory_1", "syllabus", "Number_Syllabus_Claude.tex"),
    ("number_theory_1", "context", "Number_Content_Claude.tex"),
    ("number_theory_1", "textbook_reference", "Number_Claude_Interactive.tex"),
]

COURSES = {
    "calc1": {
        "name": "Calculus I for Biological and Social Sciences",
        "note": "Provided files cover Calculus I; the context file also describes proposed Calculus II material.",
    },
    "number_theory_1": {
        "name": "Number Theory I",
        "note": "Provided context describes a two-semester sequence; scope needs instructor confirmation.",
    },
}

PROVENANCE = {
    "syllabus": "AI-prepared syllabus/course guide; official adoption not established",
    "context": "AI-prepared course context; not verified lecture record",
    "textbook_reference": "AI-prepared textbook-based course breakdown; original textbook full text not supplied",
}

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE courses (
    course_id TEXT PRIMARY KEY, name TEXT NOT NULL, note TEXT NOT NULL
);
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(course_id),
    source_type TEXT NOT NULL, filename TEXT NOT NULL, source_path TEXT NOT NULL,
    snapshot_path TEXT NOT NULL, sha256 TEXT NOT NULL, line_count INTEGER NOT NULL,
    provenance TEXT NOT NULL, review_status TEXT NOT NULL
);
CREATE TABLE sections (
    section_id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(document_id),
    parent_id TEXT REFERENCES sections(section_id), level INTEGER NOT NULL,
    title TEXT NOT NULL, heading_kind TEXT NOT NULL,
    start_line INTEGER NOT NULL, end_line INTEGER NOT NULL
);
CREATE TABLE passages (
    passage_id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(document_id),
    section_id TEXT NOT NULL REFERENCES sections(section_id),
    passage_kind TEXT NOT NULL, scope_status TEXT NOT NULL,
    start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
    raw_latex TEXT NOT NULL, readable_text TEXT NOT NULL
);
CREATE TABLE concepts (
    concept_id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(course_id),
    title TEXT NOT NULL, summary TEXT NOT NULL, extraction_method TEXT NOT NULL,
    review_status TEXT NOT NULL
);
CREATE TABLE concept_evidence (
    concept_id TEXT NOT NULL REFERENCES concepts(concept_id),
    passage_id TEXT NOT NULL REFERENCES passages(passage_id),
    relation TEXT NOT NULL,
    PRIMARY KEY (concept_id, passage_id)
);
CREATE TABLE review_issues (
    issue_id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(document_id),
    source_line INTEGER NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE INDEX passages_document ON passages(document_id);
CREATE INDEX passages_section ON passages(section_id);
CREATE INDEX concepts_course ON concepts(course_id);
"""


def stable_id(prefix: str, value: str) -> str:
    return prefix + "_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def braced_args(s: str, pos: int, maximum: int = 3) -> list[str]:
    """Read consecutive balanced LaTeX arguments, on one physical line."""
    result = []
    for _ in range(maximum):
        while pos < len(s) and s[pos].isspace():
            pos += 1
        if pos >= len(s) or s[pos] != "{":
            break
        start = pos + 1
        depth = 1
        pos += 1
        while pos < len(s) and depth:
            if s[pos] == "{" and (pos == 0 or s[pos - 1] != "\\"):
                depth += 1
            elif s[pos] == "}" and (pos == 0 or s[pos - 1] != "\\"):
                depth -= 1
            pos += 1
        if depth:
            break
        result.append(s[start : pos - 1])
    return result


def readable(tex: str) -> str:
    """A conservative display/search preview; raw_latex remains authoritative."""
    tex = re.sub(r"(?m)^\s*%.*$", "", tex)
    tex = re.sub(r"\\(?:begin|end)\{[^{}]+\}(?:\[[^]]*\])?", " ", tex)
    tex = re.sub(r"\\(?:label|ref|pageref)\{([^{}]+)\}", r" \1 ", tex)
    tex = re.sub(r"\\(?:textbf|textit|emph|mathrm|mathbb|mathcal|textcolor)\b", " ", tex)
    tex = re.sub(r"\\(?:item|par|noindent|quad|qquad|hfill|newline|bigskip|smallskip|clearpage|newpage)\b", " ", tex)
    tex = tex.replace("\\&", "&").replace("\\%", "%")
    tex = re.sub(r"\\\\(?:\[[^]]*\])?", " ", tex)
    tex = tex.replace("{", "").replace("}", "").replace("$", "")
    tex = re.sub(r"\s+", " ", tex)
    return tex.strip()


def heading_for(line: str) -> tuple[int, str, str] | None:
    stripped = line.strip()
    m = re.match(r"\\(section|subsection|subsubsection)\*?\s*", stripped)
    if m:
        args = braced_args(stripped, m.end(), 1)
        if args:
            return {"section": 1, "subsection": 2, "subsubsection": 3}[m.group(1)], readable(args[0]), m.group(1)
    for token, level, title_index in ((r"\begin{unitbox}", 2, 1), (r"\ChapHead", 3, 0)):
        if stripped.startswith(token):
            args = braced_args(stripped, len(token), 3)
            if len(args) > title_index:
                title = readable(args[title_index])
                if token == r"\begin{unitbox}" and args:
                    title = f"Unit {readable(args[0])}: {title}"
                return level, title, token
    return None


def split_passages(content: list[tuple[int, str]], max_chars: int = 2300) -> list[list[tuple[int, str]]]:
    """Split on paragraph boundaries, then lines if a long LaTeX table has no blanks."""
    blocks: list[list[tuple[int, str]]] = []
    block: list[tuple[int, str]] = []
    for line in content:
        if not line[1].strip():
            if block:
                blocks.append(block)
                block = []
        elif not line[1].lstrip().startswith("%"):
            block.append(line)
    if block:
        blocks.append(block)
    passages: list[list[tuple[int, str]]] = []
    pending: list[tuple[int, str]] = []
    for block in blocks:
        if len("\n".join(x[1] for x in pending + block)) <= max_chars:
            pending.extend(block)
            continue
        if pending:
            passages.append(pending)
            pending = []
        if len("\n".join(x[1] for x in block)) <= max_chars:
            pending = block
            continue
        for line in block:
            if pending and len("\n".join(x[1] for x in pending + [line])) > max_chars:
                passages.append(pending)
                pending = []
            pending.append(line)
    if pending:
        passages.append(pending)
    return passages


def scope_status(doc_id: str, line: int) -> str:
    if doc_id == "calc1:context" and 399 <= line < 639:
        return "outside_pilot_course_calc2"
    if doc_id == "calc1:context" and 671 <= line < 697:
        return "outside_pilot_course_calc2_schedule"
    if doc_id == "calc1:textbook_reference" and 720 <= line < 749:
        return "outside_pilot_course_calc2_lookahead"
    if doc_id == "number_theory_1:context" and 351 <= line < 602:
        return "second_semester_scope_unconfirmed"
    if doc_id == "number_theory_1:context" and 632 <= line < 661:
        return "second_semester_scope_unconfirmed"
    return "pilot_course_or_general"


def parse_document(doc_id: str, lines: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return sections, passages, and heading-derived concept candidates."""
    begin = next(i for i, x in enumerate(lines, 1) if r"\begin{document}" in x)
    end = next(i for i, x in enumerate(lines[begin:], begin + 1) if r"\end{document}" in x)
    root_id = f"{doc_id}:root"
    root = dict(section_id=root_id, document_id=doc_id, parent_id=None, level=0,
                title="Document front matter", heading_kind="root", start_line=begin, end_line=end)
    sections = [root]
    by_id = {root_id: root}
    content: dict[str, list[tuple[int, str]]] = {root_id: []}
    stack = [root_id]
    candidates = []
    for lineno in range(begin + 1, end):
        line = lines[lineno - 1]
        heading = heading_for(line)
        if heading:
            level, title, kind = heading
            while len(stack) > 1 and by_id[stack[-1]]["level"] >= level:
                closing = stack.pop()
                by_id[closing]["end_line"] = lineno - 1
            parent = stack[-1]
            section_id = stable_id("sec", f"{doc_id}:{lineno}:{title}")
            section = dict(section_id=section_id, document_id=doc_id, parent_id=parent,
                           level=level, title=title, heading_kind=kind,
                           start_line=lineno, end_line=end - 1)
            sections.append(section)
            by_id[section_id] = section
            content[section_id] = []
            stack.append(section_id)
            candidates.append((section_id, lineno, title, kind))
        else:
            content[stack[-1]].append((lineno, line))
    passages = []
    by_section: dict[str, list[dict]] = {}
    for sec in sections:
        groups = split_passages(content[sec["section_id"]])
        for group in groups:
            raw = "\n".join(x[1] for x in group)
            preview = readable(raw)
            if not preview:
                continue
            start, stop = group[0][0], group[-1][0]
            passage = dict(
                passage_id=stable_id("pass", f"{doc_id}:{start}:{stop}:section"),
                document_id=doc_id, section_id=sec["section_id"], passage_kind="section_text",
                scope_status=scope_status(doc_id, start),
                start_line=start, end_line=stop, raw_latex=raw, readable_text=preview,
            )
            passages.append(passage)
            by_section.setdefault(sec["section_id"], []).append(passage)
    concepts = []
    generic = ("course overview", "course description", "assessment", "weekly schedule", "prerequisite map", "course map", "modeling project")
    for sec_id, lineno, title, kind in candidates:
        if any(term in title.lower() for term in generic):
            continue
        if kind == "section" and not (title.lower().startswith(("module ", "semester "))):
            continue
        own = by_section.get(sec_id, [])
        if not own:
            continue
        if own[0]["scope_status"].startswith("outside_pilot_course"):
            continue
        summary = own[0]["readable_text"][:450]
        concepts.append(dict(title=title, summary=summary, passage_id=own[0]["passage_id"],
                             method="latex_heading", lineno=lineno))
    return sections, passages, concepts


def table_row_concepts(doc_id: str, lines: list[str], sections: list[dict]) -> tuple[list[dict], list[dict]]:
    """Calc I textbook-based breakdown stores its fine-grained topics in tables."""
    if doc_id != "calc1:textbook_reference":
        return [], []
    outline = next(s for s in sections if s["title"] == "Detailed Module Breakdown")
    section_candidates = sorted(sections, key=lambda s: (s["level"], s["start_line"]), reverse=True)
    passages, concepts = [], []
    for lineno, line in enumerate(lines, 1):
        if not outline["start_line"] <= lineno <= outline["end_line"]:
            continue
        m = re.match(r"^\s*(\d+(?:\.\d+)*)(?:\\opt)?\s*&\s*([^&]+?)\s*&\s*([^&]+?)\s*&", line)
        if not m:
            continue
        number, topic, objective = m.groups()
        title = f"{number} {readable(topic)}"
        parent = next((s for s in section_candidates if s["start_line"] <= lineno <= s["end_line"]), None)
        if parent is None:
            continue
        passage_id = stable_id("pass", f"{doc_id}:{lineno}:table_row")
        passages.append(dict(passage_id=passage_id, document_id=doc_id,
                             section_id=parent["section_id"], passage_kind="textbook_outline_row",
                             scope_status="pilot_course_or_general",
                             start_line=lineno, end_line=lineno, raw_latex=line,
                             readable_text=f"{title}. Learning objective: {readable(objective)}"))
        concepts.append(dict(title=title, summary=readable(objective),
                             passage_id=passage_id, method="textbook_outline_row", lineno=lineno))
    return passages, concepts


def explicit_core_concepts(doc_id: str, lines: list[str], passages: list[dict]) -> list[dict]:
    """Expose explicit 'Core concepts' bullets in the number theory course package."""
    if doc_id != "number_theory_1:textbook_reference":
        return []
    concepts = []
    active = False
    for lineno, line in enumerate(lines, 1):
        if r"\textbf{Core concepts}" in line:
            active = True
            continue
        if active and (r"\textbf{Learning objectives}" in line or r"\subsection" in line or r"\section" in line):
            active = False
        if not active:
            continue
        match = re.match(r"\s*\\item(?:\[[^]]*\])?\s*(.+)", line)
        if not match:
            continue
        summary = readable(match.group(1))
        if not summary:
            continue
        if summary.lower().startswith(("examples:", "non-example:")):
            continue
        title = summary[:110].strip()
        source = next((p for p in passages if p["start_line"] <= lineno <= p["end_line"]), None)
        if source is None:
            continue
        concepts.append(dict(title=title, summary=summary, passage_id=source["passage_id"],
                             method="explicit_core_concept_bullet", lineno=lineno))
    return concepts


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in records:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build() -> None:
    if not RESOURCE.is_dir():
        raise SystemExit(f"Missing source directory: {RESOURCE}")
    OUT.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "knowledge_base.sqlite"
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    for cid, course in COURSES.items():
        conn.execute("INSERT INTO courses VALUES (?, ?, ?)", (cid, course["name"], course["note"]))

    documents, sections, passages, concepts, links = [], [], [], [], []
    for course_id, source_type, filename in SOURCES:
        path = RESOURCE / filename
        data = path.read_bytes()
        lines = data.decode("utf-8").splitlines()
        snapshot = SNAPSHOTS / filename
        shutil.copyfile(path, snapshot)
        if hashlib.sha256(snapshot.read_bytes()).digest() != hashlib.sha256(data).digest():
            raise RuntimeError(f"Source snapshot checksum mismatch: {filename}")
        doc_id = f"{course_id}:{source_type}"
        document = dict(document_id=doc_id, course_id=course_id, source_type=source_type,
                        filename=filename, source_path=str(path.relative_to(PROJECT_ROOT)), snapshot_path=str(snapshot.relative_to(PROJECT_ROOT)),
                        sha256=hashlib.sha256(data).hexdigest(), line_count=len(lines),
                        provenance=PROVENANCE[source_type], review_status="unverified")
        documents.append(document)
        sec, pas, cards = parse_document(doc_id, lines)
        extra_passages, extra_cards = table_row_concepts(doc_id, lines, sec)
        sections.extend(sec)
        passages.extend(pas + extra_passages)
        core_cards = explicit_core_concepts(doc_id, lines, pas)
        for card in cards + extra_cards + core_cards:
            concept_id = stable_id("concept", f"{doc_id}:{card['lineno']}:{card['title']}")
            concepts.append(dict(concept_id=concept_id, course_id=course_id,
                                 title=card["title"], summary=card["summary"],
                                 extraction_method=card["method"], review_status="auto_extracted_unreviewed"))
            links.append(dict(concept_id=concept_id, passage_id=card["passage_id"], relation="derived_from"))

    for row in documents:
        conn.execute("INSERT INTO documents VALUES (:document_id,:course_id,:source_type,:filename,:source_path,:snapshot_path,:sha256,:line_count,:provenance,:review_status)", row)
    # Parents must be inserted before children; the parser emits preorder.
    for row in sections:
        conn.execute("INSERT INTO sections VALUES (:section_id,:document_id,:parent_id,:level,:title,:heading_kind,:start_line,:end_line)", row)
    for row in passages:
        conn.execute("INSERT INTO passages VALUES (:passage_id,:document_id,:section_id,:passage_kind,:scope_status,:start_line,:end_line,:raw_latex,:readable_text)", row)
    for row in concepts:
        conn.execute("INSERT INTO concepts VALUES (:concept_id,:course_id,:title,:summary,:extraction_method,:review_status)", row)
    for row in links:
        conn.execute("INSERT INTO concept_evidence VALUES (:concept_id,:passage_id,:relation)", row)
    review_issues = []
    number_lines = (RESOURCE / "Number_Claude_Interactive.tex").read_text(encoding="utf-8").splitlines()
    for source_line, line in enumerate(number_lines, 1):
        if "three unramified primes each with" in line and r"\zeta_7" in line:
            review_issues.append(dict(
                issue_id="number_theory_cyclotomic_split_count",
                document_id="number_theory_1:textbook_reference", source_line=source_line,
                severity="high", status="needs_instructor_review",
                description="The draft states that 2 gives three unramified primes of residue degree 3 in Q(zeta_7). Since [Q(zeta_7):Q] = 6 and 2 has order 3 modulo 7, the expected number is 6/3 = 2, not 3.",
            ))
    for row in review_issues:
        conn.execute("INSERT INTO review_issues VALUES (:issue_id,:document_id,:source_line,:severity,:status,:description)", row)
    conn.commit()
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"Foreign key violations: {violations[:5]}")
    conn.close()

    for name, rows in (("documents", documents), ("sections", sections), ("passages", passages),
                       ("concepts", concepts), ("concept_evidence", links), ("review_issues", review_issues)):
        write_jsonl(OUT / f"{name}.jsonl", rows)

    counts = Counter((d["course_id"], d["source_type"]) for d in documents)
    assert len(documents) == 6 and all(v == 1 for v in counts.values())
    manifest = {
        "schema_version": 1,
        "status": "catalog_only_no_embeddings_no_retrieval",
        "courses": COURSES,
        "counts": {"documents": len(documents), "sections": len(sections),
                   "passages": len(passages), "concepts": len(concepts),
                   "concept_links": len(links), "review_issues": len(review_issues)},
        "documents": documents,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    doc_by_id = {d["document_id"]: d for d in documents}
    passage_by_id = {p["passage_id"]: p for p in passages}
    concept_by_id = {c["concept_id"]: c for c in concepts}
    catalog = ["# Course Knowledge Base Catalog", "", "Generated by `build_kb.py`. All concept cards require instructor review. Line numbers refer to the source snapshots in `data/sources/`. See [all concept cards](concept_cards.md).", ""]
    card_review = ["# Concept Cards for Instructor Review", "", "These entries were extracted from the supplied AI-organized files. Each one retains a source location and remains unreviewed.", ""]
    for course_id, course in COURSES.items():
        catalog += [f"## {course['name']} (`{course_id}`)", "", course["note"], ""]
        for doc in (d for d in documents if d["course_id"] == course_id):
            did = doc["document_id"]
            catalog += [f"### {doc['source_type']} · [{doc['filename']}](sources/{doc['filename']})", "",
                        f"Provenance: {doc['provenance']}.", ""]
            card_review += [f"## {course['name']} · {doc['source_type']}", ""]
            doc_sections = [s for s in sections if s["document_id"] == did and s["level"] > 0]
            for section in doc_sections:
                indent = "  " * (section["level"] - 1)
                scope = scope_status(did, section["start_line"])
                scope_note = "" if scope == "pilot_course_or_general" else f"; scope: `{scope}`"
                catalog.append(f"{indent}- {section['title']} (line {section['start_line']}{scope_note})")
            doc_links = [x for x in links if doc_by_id[passage_by_id[x["passage_id"]]["document_id"]]["document_id"] == did]
            catalog += ["", f"Concept cards: {len(doc_links)}. See `concepts.jsonl` for complete records.", ""]
            if doc_links:
                examples = doc_links[:5]
                catalog += ["Examples: " + "; ".join(concept_by_id[x["concept_id"]]["title"] for x in examples) + ".", ""]
            for link in doc_links:
                card = concept_by_id[link["concept_id"]]
                passage = passage_by_id[link["passage_id"]]
                summary = card["summary"].replace("\n", " ")[:240]
                scope = passage["scope_status"]
                scope_note = "" if scope == "pilot_course_or_general" else f"; scope `{scope}`"
                card_review.append(
                    f"- **{card['title']}** — {summary} "
                    f"([source](sources/{doc['filename']}), line {passage['start_line']}{scope_note}; "
                    f"ID `{card['concept_id']}`)."
                )
            card_review.append("")
    (OUT / "catalog.md").write_text("\n".join(catalog), encoding="utf-8")
    (OUT / "concept_cards.md").write_text("\n".join(card_review), encoding="utf-8")
    report = ["# Ingestion Quality Report", "", "This build creates a document catalog, section passages, and source-linked concept cards. It does not generate embeddings or implement retrieval.", "",
              "| Course | Source type | Section nodes | Passages | Concept cards |", "| --- | --- | ---: | ---: | ---: |"]
    for doc in documents:
        did = doc["document_id"]
        report.append(f"| {doc['course_id']} | {doc['source_type']} | "
                      f"{sum(s['document_id'] == did for s in sections)} | "
                      f"{sum(p['document_id'] == did for p in passages)} | "
                      f"{sum(c['concept_id'] in {x['concept_id'] for x in links if x['passage_id'] in {p['passage_id'] for p in passages if p['document_id'] == did}} for c in concepts)} |")
    report += ["", "## Provenance and scope", "", "- All six files have Claude-based names and appear to be AI-authored or AI-organized course materials. Their review status is `unverified`.",
               "- `textbook_reference` is a textbook-based course breakdown or design package, not the complete original textbook. Citations may point only to this supplied file and its sections or lines.",
               "- The `context` files alone do not prove that a particular instructor covered specific material in class.",
               "- Calculus II content in the calculus context and the textbook-based look-ahead is marked `outside_pilot_course_*` and must not be treated as Calculus I evidence by default.",
               "- The second-semester number theory context is marked `second_semester_scope_unconfirmed`; instructor confirmation is needed.",
               "", "## Validation", "", "- All six snapshots match the SHA-256 checksums of the input files.",
               "- SQLite foreign-key validation passes; every concept card links to a source passage.",
               "- Formulas remain in `raw_latex`; `readable_text` is only a preview and must not replace the original when citing.",
               "- Sections and passages retain source-file line numbers for instructor review.", ""]
    number_content = (RESOURCE / "Number_Content_Claude.tex").read_text(encoding="utf-8")
    if number_content.rstrip().endswith(r"\end{document}t"):
        report.append("- `Number_Content_Claude.tex` has a trailing `t` after `\\end{document}`. It does not affect body parsing; the input file was not modified.")
    for issue in review_issues:
        report.append(f"- Review issue `{issue['issue_id']}` at `{doc_by_id[issue['document_id']]['filename']}:{issue['source_line']}`: {issue['description']} The source was not edited.")
    (OUT / "quality_report.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(manifest["counts"], ensure_ascii=False))


if __name__ == "__main__":
    build()
