# Two-Course Knowledge Base: Initial Build

This Week 3 deliverable turns the three LaTeX files for each of two courses in `resource/` into a source-traceable data catalog and two sets of real document embeddings. PostgreSQL 17 with pgvector is deployed in Docker and populated with the catalog and both vector sets. A hybrid student-question retrieval pipeline now returns source-linked context. **Answer generation and an HTTP application API are not included yet.**

SQLite and the JSONL/NumPy exports remain portable build artifacts. The active database is Docker PostgreSQL with pgvector, with its persistent data bind-mounted under `week3/knowledge_base/postgres/docker_data/`.

## Outputs

- [Course catalog](data/catalog.md): browse the course and document hierarchy and sample concept cards.
- [Concept-card review list](data/concept_cards.md): inspect every extracted card with its source line and scope flag.
- [Quality report](data/quality_report.md): ingestion counts, provenance limits, and scope flags.
- [SQLite database](data/knowledge_base.sqlite): courses, documents, sections, passages, concept cards, and evidence links.
- `data/*.jsonl`: export of the main database tables for review or migration.
- `data/sources/`: byte-identical snapshots of the six input LaTeX files. The files in `resource/` are unchanged.
- [Manifest](data/manifest.json): source paths, snapshot paths, SHA-256 hashes, statuses, and counts.
- [Embedding inputs](embeddings/embedding_inputs.jsonl): shared, source-linked English inputs for both models, with token counts and hashes.
- `embeddings/bge_base_en_v1_5/` and `embeddings/qwen3_embedding_0_6b/`: normalized float32 `.npy` vector matrices, row maps, exact model revisions, and generation manifests.
- [Embedding build report](embeddings/embedding_report.md): model versions, vector counts, scope distribution, and validation limits.
- [PostgreSQL deployment guide](postgres/README.md): local connection, startup, data import, validation, and shutdown.
- [PostgreSQL validation report](postgres/validation_report.json): catalog counts, exact vector comparison, dimensions, indexes, and sample queries.
- [Retrieval guide](retrieval/README.md): cross-course hybrid search, source filters, citations, command-line use, and Python integration.
- [Retrieval pilot evaluation](retrieval/evaluation_report.md): five sample questions and ranked source citations.
- [Fifty-question evaluation framework](retrieval/evaluation_framework.md) and [benchmark report](retrieval/benchmark_report.md): model comparison, evidence completeness, source integrity, failure analysis, and latency.

## October 1 retrieval update

The live retrieval default now uses a soft per-file preference of four passages and explicit `Not found` results for unsupported request patterns or empty evidence. The frozen Week 3 benchmark remains historical; see [the separate policy comparison](retrieval/policy_update_report.md) for the six new settings and remaining limits. This update does not add an answer model or a general semantic evidence-sufficiency classifier.

The later [refinement](retrieval/refinement_report.md) adds scope/source explanations and focused subquestion retrieval. On the existing 50-question set, completeness is now 46/46 answerable questions; six wordings of the two known hard cases achieve 5/6. These are post-hoc silver-label checks, not a general correctness guarantee.

## Data relationships

```text
course → document (syllabus / context / textbook_reference)
                     → section tree → passage (source line numbers + raw LaTeX)
concept card ───────────────────────→ passage
```

Concept cards are extracted from headings, explicitly labeled core-concept bullets, and the section-by-section topic table in the Calculus I textbook-based breakdown. They are **navigation records derived from the supplied AI-organized materials**, not newly generated textbook facts or instructor-approved conclusions. Every card links to a passage with source-file line numbers.

The source type `textbook_reference` is deliberately distinct from `textbook_original`: the supplied files are textbook-based course breakdowns or design packages, not the complete textbook texts. All six documents are marked `unverified` pending instructor review. Calculus II passages are flagged as outside the Calculus I pilot course. The second-semester number theory material is flagged for scope confirmation.

## Embedding structure

Concept-card inputs contain the course, section path, concept title, and source-derived summary. Passage inputs contain the course, section path, and readable passage text. Structured fields such as course ID, source role, scope, review status, and source lines remain metadata; the original LaTeX is preserved in the catalog and is not replaced by the embedding text.

Long passages are divided into overlapping word-boundary segments using the BGE tokenizer, with a maximum of 384 tokens per input. Both models encode **the same shared input records**, and every vector row maps back to a concept or passage ID. Two non-content title-page fragments are skipped. Material flagged as outside the pilot course remains identifiable in metadata; retrieval must enforce the appropriate scope filter later.

The model cache and Python environment are under this directory. The exact Hugging Face model commits and input SHA-256 are recorded in each manifest, so a later index can reject vectors generated from stale inputs.

## Database deployment

The [Docker Compose configuration](postgres/compose.yaml) runs `pgvector/pgvector:pg17` on `127.0.0.1:55432`. The database is `course_knowledge`; its account is `coursekb`. Its password is stored only in the local `postgres/.env` file (mode `0600`). Keep that file private and back it up with the database volume. The container starts automatically when Docker starts unless it was manually stopped.

The schema includes source-traceable catalog tables, embedding metadata, both vector tables, a course/scope index, an English full-text index, and HNSW cosine indexes. See the [deployment guide](postgres/README.md) for operations. The previous temporary native PostgreSQL instance has been stopped; Docker is the active database.

## Rebuild

From the project root:

```bash
python3 week3/knowledge_base/build_kb.py
python3 week3/knowledge_base/validate_kb.py
week3/knowledge_base/.venv/bin/python week3/knowledge_base/prepare_embedding_inputs.py
week3/knowledge_base/.venv/bin/python week3/knowledge_base/generate_embeddings.py bge_base_en_v1_5
week3/knowledge_base/.venv/bin/python week3/knowledge_base/generate_embeddings.py qwen3_embedding_0_6b
week3/knowledge_base/.venv/bin/python week3/knowledge_base/validate_embeddings.py
```

The catalog builder uses only the Python standard library. The embedding scripts use Sentence Transformers, PyTorch, Transformers, and NumPy. Rebuilding replaces generated artifacts under `data/` and refreshes the six source snapshots. It does not modify `resource/`. When the catalog changes, regenerate the shared embedding inputs and both vector matrices. Open the SQLite file with any SQLite browser, or inspect the JSONL exports. To update course labels, file mappings, or provenance rules, edit `COURSES`, `SOURCES`, or `PROVENANCE` at the top of `build_kb.py` and rebuild.

## Instructor review before student-facing use

1. Confirm each file's actual status and whether it was adopted for the course.
2. Confirm whether Number Theory I includes the second-semester material.
3. Spot-check section structure, formulas, and concept-card source lines against the [quality report](data/quality_report.md).
4. If complete textbook files or verified lecture records become available, ingest them as **new source versions**. Do not relabel the existing summaries as original sources.
