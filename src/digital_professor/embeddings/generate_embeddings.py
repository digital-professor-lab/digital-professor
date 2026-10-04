#!/usr/bin/env python3
"""Generate two real embedding matrices from the shared, source-linked inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


from digital_professor.paths import PROJECT_ROOT, CATALOG, EMBEDDINGS, CACHE
HERE = PROJECT_ROOT

os.environ.setdefault("HF_HOME", str(CACHE))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np  # noqa: E402
import sentence_transformers  # noqa: E402
import torch  # noqa: E402
import transformers  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402


EXPECTED_DIMENSIONS = {"bge_base_en_v1_5": 768, "qwen3_embedding_0_6b": 1024}
BATCH_SIZES = {"bge_base_en_v1_5": 16, "qwen3_embedding_0_6b": 4}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(model_key: str, device: str) -> None:
    inputs_path = EMBEDDINGS / "embedding_inputs.jsonl"
    input_manifest = json.loads((EMBEDDINGS / "input_manifest.json").read_text(encoding="utf-8"))
    assert sha256_file(inputs_path) == input_manifest["shared_input_sha256"]
    inputs = [json.loads(line) for line in inputs_path.read_text(encoding="utf-8").splitlines()]
    assert len(inputs) == input_manifest["record_count"]
    spec = input_manifest["models"][model_key]
    output = EMBEDDINGS / model_key
    output.mkdir(parents=True, exist_ok=True)

    model = SentenceTransformer(spec["repository"], revision=spec["revision"], device=device)
    texts = [row["input_text"] for row in inputs]
    vectors = model.encode(
        texts,
        batch_size=BATCH_SIZES[model_key],
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    vectors = np.asarray(vectors, dtype=np.float32)
    assert vectors.shape == (len(inputs), EXPECTED_DIMENSIONS[model_key]), vectors.shape
    assert np.isfinite(vectors).all()
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3), (float(norms.min()), float(norms.max()))
    vector_path = output / "vectors.npy"
    np.save(vector_path, vectors, allow_pickle=False)

    row_map = output / "rows.jsonl"
    with row_map.open("w", encoding="utf-8") as stream:
        for index, row in enumerate(inputs):
            stream.write(json.dumps({
                "row_index": index,
                "record_id": row["record_id"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "input_sha256": row["input_sha256"],
            }, sort_keys=True) + "\n")
    metadata = {
        "model_repository": spec["repository"],
        "model_revision": spec["revision"],
        "device": device,
        "sentence_transformers_version": sentence_transformers.__version__,
        "transformers_version": transformers.__version__,
        "torch_version": torch.__version__,
        "input_sha256": input_manifest["shared_input_sha256"],
        "vectors_sha256": sha256_file(vector_path),
        "rows_sha256": sha256_file(row_map),
        "shape": list(vectors.shape),
        "dtype": str(vectors.dtype),
        "normalized": True,
        "encoding": "SentenceTransformer.encode with model-specific document defaults",
        "batch_size": BATCH_SIZES[model_key],
    }
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=sorted(EXPECTED_DIMENSIONS))
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps" if torch.backends.mps.is_available() else "cpu")
    args = parser.parse_args()
    generate(args.model, args.device)
