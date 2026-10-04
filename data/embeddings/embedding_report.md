# Embedding Build Report

## Result

Both requested Hugging Face models generated real, normalized float32 document embeddings from the same source-linked English input set.

| Model | Exact revision | Vectors | Dimensions | File |
| --- | --- | ---: | ---: | --- |
| `BAAI/bge-base-en-v1.5` | `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a` | 476 | 768 | `bge_base_en_v1_5/vectors.npy` |
| `Qwen/Qwen3-Embedding-0.6B` | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | 476 | 1,024 | `qwen3_embedding_0_6b/vectors.npy` |

The shared input contains 216 concept-card records and 260 passage-segment records from 219 unique passages. Two non-content title-page fragments were skipped. Longer passages were segmented with a 25-word overlap; every input contains at most 384 BGE tokens. The input SHA-256 and each vector file's SHA-256 are recorded in the manifests.

## Scope retained as metadata

The corpus includes flagged material so the vectors remain a faithful representation of the supplied files. A later retrieval service must apply the scope rules:

- 439 records: pilot-course or general material.
- 20 records: second-semester Number Theory context awaiting course-scope confirmation.
- 17 records: Calculus II material outside the Calculus I pilot course.

The flags, review status, source role, document ID, section path, and source-file line numbers are stored in `embedding_inputs.jsonl`. The `.npy` matrices have the same row order as that file and the model-specific `rows.jsonl` files.

## Validation and interpretation

`validate_embeddings.py` confirms both matrix shapes, finite values, unit-length vectors, model revisions, file checksums, and exact row-to-source mappings. The scripts ran on Apple MPS with pinned Hugging Face model revisions. Package versions are in `../requirements-embeddings.lock.txt`.

This validation confirms that the embeddings were generated and linked correctly. It does **not** establish retrieval accuracy. The next step is an instructor-labeled English question set and a comparison of keyword, BGE, Qwen, and hybrid retrieval. The supplied `textbook_reference` files remain AI-organized course breakdowns rather than complete original textbooks; embeddings do not change that provenance.
