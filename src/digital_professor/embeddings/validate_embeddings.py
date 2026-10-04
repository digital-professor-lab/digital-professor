#!/usr/bin/env python3
"""Check both embedding artifacts against their shared input and source IDs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


from digital_professor.paths import PROJECT_ROOT, CATALOG, EMBEDDINGS, CACHE
HERE = PROJECT_ROOT
ROOT = EMBEDDINGS
EXPECTED_DIMS = {"bge_base_en_v1_5": 768, "qwen3_embedding_0_6b": 1024}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> dict:
    input_manifest = json.loads((ROOT / "input_manifest.json").read_text(encoding="utf-8"))
    input_path = ROOT / "embedding_inputs.jsonl"
    assert sha256_file(input_path) == input_manifest["shared_input_sha256"]
    inputs = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines()]
    assert len(inputs) == input_manifest["record_count"]
    assert len({r["record_id"] for r in inputs}) == len(inputs)
    assert all(0 < r["bge_token_count"] <= input_manifest["max_bge_tokens"] for r in inputs)
    report = {"shared_input_records": len(inputs), "models": {}}
    for model_key, expected_dim in EXPECTED_DIMS.items():
        output = ROOT / model_key
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        vector_path = output / "vectors.npy"
        rows_path = output / "rows.jsonl"
        assert sha256_file(vector_path) == manifest["vectors_sha256"]
        assert sha256_file(rows_path) == manifest["rows_sha256"]
        assert manifest["input_sha256"] == input_manifest["shared_input_sha256"]
        assert manifest["model_revision"] == input_manifest["models"][model_key]["revision"]
        vectors = np.load(vector_path, mmap_mode="r", allow_pickle=False)
        assert vectors.shape == (len(inputs), expected_dim)
        assert vectors.dtype == np.float32
        assert np.isfinite(vectors).all()
        norms = np.linalg.norm(vectors, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-3)
        rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == len(inputs)
        for index, (row, source) in enumerate(zip(rows, inputs)):
            assert row["row_index"] == index
            assert row["record_id"] == source["record_id"]
            assert row["entity_id"] == source["entity_id"]
            assert row["input_sha256"] == source["input_sha256"]
        report["models"][model_key] = {
            "shape": list(vectors.shape),
            "normalized": True,
            "model_revision": manifest["model_revision"],
        }
    return report


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
