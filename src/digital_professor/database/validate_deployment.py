#!/usr/bin/env python3
"""Verify the Docker database against the source catalog and vector matrices."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from .import_data import DATA, EMBEDDINGS, HERE, MODEL_TABLES, read_jsonl


def main() -> None:
    from digital_professor.paths import database_port, DATABASE_CONFIG
    env_file = DATABASE_CONFIG / ".env"
    passwords = [line.partition("=")[2] for line in env_file.read_text(encoding="utf-8").splitlines()
                 if line.startswith("POSTGRES_PASSWORD=")]
    if len(passwords) != 1 or not passwords[0]:
        raise ValueError("Missing database password")

    inputs = read_jsonl(EMBEDDINGS / "embedding_inputs.jsonl")
    ordered_ids = [row["record_id"] for row in inputs]
    assert len(ordered_ids) == len(set(ordered_ids))
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    report = {"database": "course_knowledge", "model_checks": {}}

    with psycopg.connect(host="127.0.0.1", port=database_port(), dbname="course_knowledge",
                         user="coursekb", password=passwords[0]) as conn:
        register_vector(conn)
        assert conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
        expected_counts = {"courses": len(manifest["courses"]), "embedding_inputs": len(inputs),
                           "embedding_models": len(MODEL_TABLES)}
        for table in ("documents", "sections", "passages", "concepts", "concept_evidence", "review_issues"):
            expected_counts[table] = len(read_jsonl(DATA / f"{table}.jsonl"))
        for table in MODEL_TABLES.values():
            expected_counts[table[0]] = len(inputs)
        counts = {}
        for table, expected in expected_counts.items():
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            assert count == expected, (table, count, expected)
            counts[table] = count
        report["counts"] = counts

        database_inputs = conn.execute("SELECT record_id, input_sha256 FROM embedding_inputs").fetchall()
        assert {record_id: digest for record_id, digest in database_inputs} == {
            row["record_id"]: row["input_sha256"] for row in inputs
        }

        indexes = {row[0] for row in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'").fetchall()}
        required_indexes = {"embedding_inputs_text_idx", "embedding_bge_cosine_idx", "embedding_qwen_cosine_idx"}
        assert required_indexes <= indexes, required_indexes - indexes
        report["required_indexes"] = sorted(required_indexes)

        for model_key, (table, dimension) in MODEL_TABLES.items():
            matrix = np.load(EMBEDDINGS / model_key / "vectors.npy", allow_pickle=False)
            rows = conn.execute(f"SELECT record_id, embedding, vector_dims(embedding) FROM {table}").fetchall()
            fetched = {record_id: (vector, dims) for record_id, vector, dims in rows}
            assert set(fetched) == set(ordered_ids)
            assert all(dims == dimension for _, dims in fetched.values())
            actual_matrix = np.stack([fetched[record_id][0].to_numpy() for record_id in ordered_ids])
            maximum_error = float(np.max(np.abs(actual_matrix - matrix)))
            assert maximum_error < 1e-6, (model_key, maximum_error)
            query = matrix[0]
            closest_id, distance = conn.execute(
                f"SELECT record_id, embedding <=> %s AS distance FROM {table} ORDER BY embedding <=> %s LIMIT 1",
                (query, query),
            ).fetchone()
            assert closest_id == ordered_ids[0] and abs(distance) < 1e-6
            report["model_checks"][model_key] = {
                "rows": len(rows), "dimensions": dimension,
                "maximum_absolute_vector_error": maximum_error,
                "self_query_top_match": closest_id,
            }

        report["english_full_text_matches"] = conn.execute(
            "SELECT count(*) FROM embedding_inputs WHERE to_tsvector('english', input_text) @@ plainto_tsquery('english', 'theorem')"
        ).fetchone()[0]

    report["status"] = "passed"
    (HERE / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
