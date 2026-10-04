#!/usr/bin/env python3
"""Prepare the same source-linked English texts for two embedding models."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path


from digital_professor.paths import PROJECT_ROOT, CATALOG, EMBEDDINGS, CACHE
HERE = PROJECT_ROOT
DATA = CATALOG

os.environ.setdefault("HF_HOME", str(CACHE))

from huggingface_hub import model_info  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402


MODELS = {
    "bge_base_en_v1_5": "BAAI/bge-base-en-v1.5",
    "qwen3_embedding_0_6b": "Qwen/Qwen3-Embedding-0.6B",
}
MAX_BGE_TOKENS = 384
OVERLAP_WORDS = 25


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def section_path(section_id: str, sections: dict[str, dict]) -> str:
    names = []
    current = section_id
    while current:
        section = sections[current]
        if section["level"]:
            names.append(section["title"])
        current = section["parent_id"]
    return " > ".join(reversed(names))


def token_count(tokenizer, value: str) -> int:
    return len(tokenizer.encode(value, add_special_tokens=True, truncation=False))


def split_text(tokenizer, prefix: str, body: str) -> list[tuple[str, int]]:
    """Split on word boundaries to stay below the BGE model's token limit."""
    full = prefix + body
    if token_count(tokenizer, full) <= MAX_BGE_TOKENS:
        return [(full, token_count(tokenizer, full))]
    words = body.split()
    if not words:
        raise ValueError("Cannot split empty embedding body")
    result = []
    start = 0
    while start < len(words):
        low, high = start + 1, len(words)
        best = start
        while low <= high:
            mid = (low + high) // 2
            candidate = prefix + " ".join(words[start:mid])
            if token_count(tokenizer, candidate) <= MAX_BGE_TOKENS:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        if best == start:
            raise ValueError(f"One source token exceeds the embedding budget near: {words[start][:80]}")
        value = prefix + " ".join(words[start:best])
        result.append((value, token_count(tokenizer, value)))
        if best == len(words):
            break
        start = max(start + 1, best - OVERLAP_WORDS)
    return result


def prepare() -> None:
    EMBEDDINGS.mkdir(parents=True, exist_ok=True)
    revisions = {name: model_info(repo_id).sha for name, repo_id in MODELS.items()}
    tokenizer = AutoTokenizer.from_pretrained(
        MODELS["bge_base_en_v1_5"], revision=revisions["bge_base_en_v1_5"]
    )
    conn = sqlite3.connect(DATA / "knowledge_base.sqlite")
    conn.row_factory = sqlite3.Row
    courses = {r["course_id"]: dict(r) for r in conn.execute("SELECT * FROM courses")}
    documents = {r["document_id"]: dict(r) for r in conn.execute("SELECT * FROM documents")}
    sections = {r["section_id"]: dict(r) for r in conn.execute("SELECT * FROM sections")}
    passage_by_id = {r["passage_id"]: dict(r) for r in conn.execute("SELECT * FROM passages")}
    records = []
    skipped = []

    for row in conn.execute("SELECT * FROM passages ORDER BY document_id, start_line, passage_id"):
        passage = dict(row)
        doc = documents[passage["document_id"]]
        body = passage["readable_text"].strip()
        if len(body) < 40 or body in (r"\maketitle", r"\maketitle \tableofcontents"):
            skipped.append({"entity_type": "passage", "entity_id": passage["passage_id"], "reason": "non-content front matter"})
            continue
        path = section_path(passage["section_id"], sections)
        prefix = f"Course: {courses[doc['course_id']]['name']}. Section: {path or 'Front matter'}. Content: "
        segments = split_text(tokenizer, prefix, body)
        for index, (value, count) in enumerate(segments):
            records.append(dict(
                record_id=f"passage:{passage['passage_id']}:{index}",
                entity_type="passage", entity_id=passage["passage_id"],
                segment_index=index, segment_count=len(segments),
                course_id=doc["course_id"], document_id=doc["document_id"],
                source_type=doc["source_type"], section_path=path,
                scope_status=passage["scope_status"], review_status=doc["review_status"],
                source_line_start=passage["start_line"], source_line_end=passage["end_line"],
                input_text=value, input_sha256=sha256_text(value), bge_token_count=count,
            ))

    concept_links = dict(conn.execute("SELECT concept_id, passage_id FROM concept_evidence"))
    for row in conn.execute("SELECT * FROM concepts ORDER BY course_id, concept_id"):
        card = dict(row)
        passage = passage_by_id[concept_links[card["concept_id"]]]
        doc = documents[passage["document_id"]]
        path = section_path(passage["section_id"], sections)
        prefix = f"Course: {courses[card['course_id']]['name']}. Section: {path or 'Front matter'}. Concept: "
        body = f"{card['title']}. Description: {card['summary']}"
        segments = split_text(tokenizer, prefix, body)
        for index, (value, count) in enumerate(segments):
            records.append(dict(
                record_id=f"concept:{card['concept_id']}:{index}",
                entity_type="concept", entity_id=card["concept_id"],
                segment_index=index, segment_count=len(segments),
                course_id=card["course_id"], document_id=doc["document_id"],
                source_type=doc["source_type"], section_path=path,
                scope_status=passage["scope_status"], review_status=card["review_status"],
                source_line_start=passage["start_line"], source_line_end=passage["end_line"],
                input_text=value, input_sha256=sha256_text(value), bge_token_count=count,
            ))
    conn.close()

    assert len({r["record_id"] for r in records}) == len(records)
    assert all(0 < r["bge_token_count"] <= MAX_BGE_TOKENS for r in records)
    input_file = EMBEDDINGS / "embedding_inputs.jsonl"
    with input_file.open("w", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    input_sha = hashlib.sha256(input_file.read_bytes()).hexdigest()
    manifest = {
        "status": "prepared_for_embedding",
        "models": {name: {"repository": MODELS[name], "revision": revision}
                   for name, revision in revisions.items()},
        "shared_input_file": str(input_file),
        "shared_input_sha256": input_sha,
        "max_bge_tokens": MAX_BGE_TOKENS,
        "overlap_words": OVERLAP_WORDS,
        "record_count": len(records),
        "concept_record_count": sum(r["entity_type"] == "concept" for r in records),
        "passage_record_count": sum(r["entity_type"] == "passage" for r in records),
        "skipped": skipped,
    }
    (EMBEDDINGS / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: manifest[k] for k in ("record_count", "concept_record_count", "passage_record_count", "skipped")}, indent=2))


if __name__ == "__main__":
    prepare()
