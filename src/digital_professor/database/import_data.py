#!/usr/bin/env python3
"""Atomically load the catalog and both embedding matrices into PostgreSQL."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg import sql


from digital_professor.paths import database_port, CATALOG, EMBEDDINGS, DATABASE_CONFIG, DATABASE_REPORTS, resolve_source
HERE = DATABASE_REPORTS
HERE.mkdir(parents=True, exist_ok=True)
DATA = CATALOG
MODEL_TABLES = {
    "bge_base_en_v1_5": ("embedding_bge", 768),
    "qwen3_embedding_0_6b": ("embedding_qwen", 1024),
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def insert_rows(conn: psycopg.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    values = [tuple(row[col] for col in columns) for row in rows]
    with conn.cursor() as cursor:
        cursor.executemany(statement, values)


def load(host: str, port: int, database: str, user: str, password_file: Path | None) -> dict:
    catalog_manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    input_manifest = json.loads((EMBEDDINGS / "input_manifest.json").read_text(encoding="utf-8"))
    input_path = EMBEDDINGS / "embedding_inputs.jsonl"
    assert file_sha256(input_path) == input_manifest["shared_input_sha256"]
    for doc in catalog_manifest["documents"]:
        assert file_sha256(resolve_source(doc["snapshot_path"])) == doc["sha256"]
    inputs = read_jsonl(input_path)
    assert len(inputs) == input_manifest["record_count"]
    matrices = {}
    model_manifests = {}
    for model_key, (_, dimension) in MODEL_TABLES.items():
        directory = EMBEDDINGS / model_key
        model_manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        assert model_manifest["input_sha256"] == input_manifest["shared_input_sha256"]
        assert model_manifest["model_revision"] == input_manifest["models"][model_key]["revision"]
        vector_path = directory / "vectors.npy"
        assert file_sha256(vector_path) == model_manifest["vectors_sha256"]
        matrix = np.load(vector_path, allow_pickle=False)
        assert matrix.shape == (len(inputs), dimension)
        assert np.isfinite(matrix).all()
        matrices[model_key] = matrix
        model_manifests[model_key] = model_manifest

    connection_options = dict(host=host, port=port, dbname=database, user=user, autocommit=True)
    if password_file is not None:
        password_lines = password_file.read_text(encoding="utf-8").splitlines()
        passwords = [line.partition("=")[2] for line in password_lines if line.startswith("POSTGRES_PASSWORD=")]
        if len(passwords) != 1 or not passwords[0]:
            raise ValueError("Password file must contain exactly one POSTGRES_PASSWORD entry")
        connection_options["password"] = passwords[0]
    conn = psycopg.connect(**connection_options)
    register_vector(conn)
    try:
        with conn.transaction():
            conn.execute("TRUNCATE embedding_bge, embedding_qwen, embedding_models, embedding_inputs, concept_evidence, review_issues, concepts, passages, sections, documents, courses CASCADE")
            insert_rows(conn, "courses", [dict(course_id=cid, **course) for cid, course in catalog_manifest["courses"].items()])
            for table in ("documents", "sections", "passages", "concepts", "concept_evidence", "review_issues"):
                insert_rows(conn, table, read_jsonl(DATA / f"{table}.jsonl"))
            insert_rows(conn, "embedding_inputs", inputs)
            models = []
            for model_key, (_, dimension) in MODEL_TABLES.items():
                spec = input_manifest["models"][model_key]
                model_manifest = model_manifests[model_key]
                models.append(dict(
                    model_key=model_key, repository=spec["repository"], revision=spec["revision"],
                    input_sha256=input_manifest["shared_input_sha256"],
                    vector_sha256=model_manifest["vectors_sha256"],
                    dimensions=dimension, normalized=True,
                ))
            insert_rows(conn, "embedding_models", models)
            for model_key, (table, _) in MODEL_TABLES.items():
                matrix = matrices[model_key]
                rows = [(record["record_id"], matrix[index]) for index, record in enumerate(inputs)]
                with conn.cursor() as cursor:
                    cursor.executemany(
                        sql.SQL("INSERT INTO {} (record_id, embedding) VALUES (%s, %s)").format(sql.Identifier(table)),
                        rows,
                    )
        counts = {}
        for table in ("courses", "documents", "sections", "passages", "concepts", "concept_evidence",
                      "review_issues", "embedding_inputs", "embedding_models", "embedding_bge", "embedding_qwen"):
            counts[table] = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
        assert counts["embedding_inputs"] == counts["embedding_bge"] == counts["embedding_qwen"] == len(inputs)
        report = {
            "server_version": conn.execute("SHOW server_version").fetchone()[0],
            "pgvector_version": conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0],
            "database": database,
            "host": host,
            "port": port,
            "user": user,
            "counts": counts,
            "model_revisions": {key: input_manifest["models"][key]["revision"] for key in MODEL_TABLES},
            "input_sha256": input_manifest["shared_input_sha256"],
        }
        (HERE / "import_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=database_port())
    parser.add_argument("--database", default="course_knowledge")
    parser.add_argument("--user", default="coursekb")
    parser.add_argument("--password-file", type=Path, default=DATABASE_CONFIG / ".env")
    arguments = parser.parse_args()
    print(json.dumps(load(arguments.host, arguments.port, arguments.database, arguments.user, arguments.password_file), indent=2))
