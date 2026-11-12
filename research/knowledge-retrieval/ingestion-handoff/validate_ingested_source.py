#!/usr/bin/env python3
"""Check an IngestedSource file before handing it to Retrieval.

    python validate_ingested_source.py FILE.json [--course-context calc1.course-context.json] [--preview]

1. JSON Schema (ingested-source.schema.json, next to this script). Needs: pip install -U "jsonschema>=4"
2. Checks a schema cannot express: IDs unique and resolvable, page and line ranges inside the pages,
   blocks inside their section and in reading order without overlap, solution/proof links, page hashes,
   and (with --course-context) that every concept ID exists in that Course Context file.
3. --preview prints what Retrieval will index from the file (one row per block).

Exit code 0 = no errors (warnings may remain), 1 = errors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCHEMA = Path(__file__).with_name("ingested-source.schema.json")


def schema_errors(record: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return ["jsonschema is not installed (pip install jsonschema); schema check skipped"]
    if not hasattr(jsonschema, "Draft202012Validator"):
        return ["jsonschema 4.0 or newer is needed (pip install -U jsonschema); schema check skipped"]
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")),
                                                format_checker=jsonschema.FormatChecker())
    return [f"schema: {'/'.join(map(str, e.absolute_path)) or '(top)'}: {e.message}"
            for e in sorted(validator.iter_errors(record), key=lambda e: list(map(str, e.absolute_path)))]


def position(page: int, line: int) -> tuple[int, int]:
    return (page, line)


def check(record: dict, course_context: dict | None, course_context_sha: str | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    pages = {p["page_number"]: p for p in record.get("pages", [])}
    page_count = record.get("document", {}).get("source_file", {}).get("page_count")

    # Pages: 1..n, each listed once, hash matches the lines.
    numbers = [p["page_number"] for p in record.get("pages", [])]
    if numbers != sorted(set(numbers)):
        errors.append("pages: page_number values must be unique and in increasing order")
    if record.get("status") == "ingested" and page_count and numbers != list(range(1, page_count + 1)):
        errors.append(f"pages: status is ingested, so pages 1..{page_count} must all be present (got {numbers[:5]}...)")
    for p in record.get("pages", []):
        digest = hashlib.sha256("\n".join(p["lines"]).encode("utf-8")).hexdigest()
        if digest != p["text_sha256"]:
            errors.append(f"page {p['page_number']}: text_sha256 does not match its lines")

    def span(kind: str, item: dict, ident: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
        start = position(item["page_start"], item["line_start"])
        end = position(item["page_end"], item["line_end"])
        ok = True
        for page, line, which in ((*start, "start"), (*end, "end")):
            if page not in pages:
                errors.append(f"{kind} {ident}: {which} page {page} is not in pages")
                ok = False
            elif line > len(pages[page]["lines"]):
                errors.append(f"{kind} {ident}: {which} line {line} is past the end of page {page} "
                              f"({len(pages[page]['lines'])} lines)")
                ok = False
        if start > end:
            errors.append(f"{kind} {ident}: starts after it ends")
            ok = False
        return (start, end) if ok else None

    # Sections: unique IDs, parents exist, levels nest, children inside parents.
    sections = {}
    for s in record.get("sections", []):
        if s["section_id"] in sections:
            errors.append(f"section {s['section_id']}: duplicate section_id")
        sections[s["section_id"]] = s
    spans = {sid: span("section", s, sid) for sid, s in sections.items()}
    for sid, s in sections.items():
        parent = s["parent_id"]
        if parent is None:
            if s["level"] != 1:
                errors.append(f"section {sid}: top-level section must have level 1")
            continue
        if parent not in sections:
            errors.append(f"section {sid}: parent_id {parent} not found")
            continue
        if s["level"] != sections[parent]["level"] + 1:
            errors.append(f"section {sid}: level must be parent level + 1")
        if spans[sid] and spans[parent] and not (spans[parent][0] <= spans[sid][0] and spans[sid][1] <= spans[parent][1]):
            errors.append(f"section {sid}: lies outside its parent {parent}")

    # Blocks: unique IDs, known section, inside the section, reading order, no overlap, links.
    blocks = {}
    previous_end = None
    previous_id = None
    for b in record.get("blocks", []):
        bid = b["block_id"]
        if bid in blocks:
            errors.append(f"block {bid}: duplicate block_id")
        blocks[bid] = b
        if b["section_id"] not in sections:
            errors.append(f"block {bid}: section_id {b['section_id']} not found")
        s = span("block", b, bid)
        if s is None:
            continue
        sec_span = spans.get(b["section_id"])
        if sec_span and not (sec_span[0] <= s[0] and s[1] <= sec_span[1]):
            errors.append(f"block {bid}: lies outside its section {b['section_id']}")
        if previous_end is not None and s[0] <= previous_end:
            errors.append(f"block {bid}: overlaps or comes before the previous block {previous_id} "
                          "(list blocks in reading order, without shared lines)")
        previous_end, previous_id = s[1], bid
        if len(b["text"]) < 20 and b["type"] not in ("exercise", "solution", "formula"):
            warnings.append(f"block {bid}: very short text; Retrieval skips blocks under ~40 characters, "
                            "consider merging it into a neighbour")
        if len(b["text"].split()) > 400:
            warnings.append(f"block {bid}: long block ({len(b['text'].split())} words); fine if it is one unit, "
                            "Retrieval will split it for embedding")

    for bid, b in blocks.items():
        target = b.get("for_block_id")
        if target is None:
            continue
        if target not in blocks:
            errors.append(f"block {bid}: for_block_id {target} not found")
        elif b["type"] == "solution" and blocks[target]["type"] not in ("exercise", "example"):
            errors.append(f"block {bid}: a solution must point at an exercise or example")
        elif b["type"] == "proof" and blocks[target]["type"] != "theorem":
            errors.append(f"block {bid}: a proof must point at a theorem")
    for bid, b in blocks.items():
        if b["type"] == "exercise" and not any(o.get("for_block_id") == bid for o in blocks.values()):
            warnings.append(f"block {bid}: exercise has no solution block (fine if the material has none)")

    for w in record.get("warnings", []):
        if w.get("block_id") and w["block_id"] not in blocks:
            errors.append(f"warning {w['code']}: block_id {w['block_id']} not found")
        if w.get("page_number") and w["page_number"] not in pages and w["code"] not in ("page_unreadable", "page_range_skipped"):
            errors.append(f"warning {w['code']}: page {w['page_number']} not in pages")

    # Concepts must come from the referenced Course Context file.
    if course_context is not None:
        known = {c["id"] for c in course_context.get("Concept", [])}
        course = course_context.get("Course", {}).get("id")
        if course and course != record.get("course_id"):
            errors.append(f"course_id {record.get('course_id')} does not match the Course Context ({course})")
        for kind, items, key in (("section", sections.values(), "section_id"), ("block", blocks.values(), "block_id")):
            for item in items:
                for cid in item["concept_ids"]:
                    if cid not in known:
                        errors.append(f"{kind} {item[key]}: concept_id {cid} is not in the Course Context")
        if course_context_sha and course_context_sha != record.get("course_context_ref", {}).get("content_sha256"):
            warnings.append("course_context_ref.content_sha256 differs from the Course Context file given; "
                            "concept IDs were checked against the file given")
    else:
        warnings.append("no --course-context given: concept IDs not checked")
    return errors, warnings


def preview(record: dict) -> None:
    """What Retrieval will index: one search unit per block (long blocks are split later, at embedding time)."""
    sections = {s["section_id"]: s for s in record["sections"]}

    def path(sid: str) -> str:
        names = []
        while sid:
            s = sections[sid]
            names.append(f"{s['number']} {s['title']}" if s["number"] else s["title"])
            sid = s["parent_id"]
        return " > ".join(reversed(names))

    doc = record["document"]
    reference_only = doc["document_role"] == "syllabus"
    citable = doc["source_provenance"] == "source_document" and doc["review_status"] == "reviewed" and not reference_only
    print(f"\n{doc['document_id']} @ {doc['content_version']}  role={doc['document_role']}  "
          f"citable in production: {'yes' if citable else 'no (needs source_document + reviewed, and not a syllabus)'}")
    for b in record["blocks"]:
        where = f"p{b['page_start']}:{b['line_start']}-p{b['page_end']}:{b['line_end']}"
        shown = "engine only" if b["visibility"] == "engine_only" else "student"
        print(f"  {b['type']:<11} {where:<14} {shown:<11} {path(b['section_id'])[:48]:<48} {', '.join(b['concept_ids'])[:70]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path)
    parser.add_argument("--course-context", type=Path)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    record = json.loads(args.file.read_text(encoding="utf-8"))
    errors = schema_errors(record)
    cc = cc_sha = None
    if args.course_context:
        raw = args.course_context.read_bytes()
        cc, cc_sha = json.loads(raw), hashlib.sha256(raw).hexdigest()
    if not [e for e in errors if e.startswith("schema:")]:
        more, warnings = check(record, cc, cc_sha)
        errors += more
    else:
        warnings = ["structure checks skipped until the schema errors are fixed"]

    for e in errors:
        print("ERROR  ", e)
    for w in warnings:
        print("warning", w)
    print(f"\n{args.file.name}: {len(errors)} error(s), {len(warnings)} warning(s)")
    if args.preview and not errors:
        preview(record)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
