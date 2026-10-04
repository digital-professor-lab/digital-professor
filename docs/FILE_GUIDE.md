# File guide

[中文](FILE_GUIDE.zh-CN.md) · [Start here](../README.md)

Current code is grouped by function. Run modules with `python -m digital_professor.<module>`. Original-to-organized paths are recorded in [file-mapping.json](file-mapping.json).

| File (relative to src/digital_professor) | Purpose |
| --- | --- |
| `knowledge/build_kb.py` | Parse sources and build linked SQL/JSONL records. |
| `knowledge/validate_kb.py` | Verify IDs, relationships, source lines and hashes. |
| `embeddings/prepare_embedding_inputs.py` | Create shared token-bounded texts for both models. |
| `embeddings/generate_embeddings.py` | Encode and save normalized vectors and row mappings. |
| `embeddings/validate_embeddings.py` | Check dimensions, norms, row IDs and hashes. |
| `database/import_data.py` | Replace database catalog/vector rows in a transaction. |
| `database/validate_deployment.py` | Compare PostgreSQL records and vectors with exports. |
| `retrieval/search.py` | Hybrid search, evidence selection and cited context. |
| `retrieval/request_policy.py` | Classify scope/source requests and form focused queries. |
| `retrieval/report_contract.py` | Check status and evidence consistency at runtime. |
| `evaluation/build_benchmark.py` | Build the 50 questions, anchors and manifest. |
| `evaluation/run_benchmark.py` | Run model comparisons and score evidence groups. |
| `evaluation/evaluate_retrieval.py` | Small cross-course retrieval smoke evaluation. |
| `evaluation/ablate_file_cap.py` | Compare per-file passage caps. |
| `evaluation/diagnose_failures.py` | Inspect missed expected evidence. |
| `evaluation/evaluate_policy_update.py` | Compare hard and soft per-file settings. |
| `evaluation/evaluate_refinement.py` | Compare full questions, focused facets and context size. |
| `evaluation/evaluate_paraphrases.py` | Check six new phrasings of two known cases. |
| `paths.py` | Resolve shared data paths and database port. |

Each `__init__.py` defines a package; it is not a separate pipeline step.

| Other file/directory | Purpose |
| --- | --- |
| `infra/postgres/schema.sql` | Catalog, embedding tables and search indexes. |
| `infra/postgres/compose.yaml` | Pinned database image and local persistence. |
| `infra/postgres/.env.example` | Password/port template with placeholders. |
| `contracts/retrieval_report.schema.json` | Full structured hit/report interchange definition. |
| `tests/test_request_policy.py` | Scope, source and output-decision tests. |
| `tests/test_search_policy.py` | Selection budgets and Not found behavior tests. |
| `data/sources/*.tex` | Six current ingestion sources. |
| `data/catalog/` | Courses, documents, sections, passages, concepts, evidence links, issues, manifest and SQLite. |
| `data/embeddings/` | Shared inputs, exact revisions, row mappings and small vector matrices. |
| `data/benchmark/` | Current frozen questions and matching portable catalog hash. |
| `artifacts/evaluations/` | Historical runs and the default destination for new evaluations. |
| `artifacts/history/` | Original catalog and database validation snapshots, preserved unchanged. |
| `artifacts/validation/` | Results of validating the organized copy. |
| `docs/reports/` | Presentation reports grouped by week. |
| `docs/architecture/` | Workflow HTML diagrams and PDF reports. |
| `docs/research/` | Integration discussion PDFs; filenames retain the source versions. |
| `docs/history/` | Original plans, README snapshots and progress notes. |
| `archive/week2/` | Earlier Gemini/DeepSeek/Kimi lesson experiments and results. |
| `archive/week1-drafts/` | Earlier presentation drafts. |
| `tools/verify_saved_results.py` | Offline verification of saved hits against relocated sources. |
| `requirements.lock.txt` | Captured full dependency environment. |
| `requirements-test.txt` | Small dependency set for offline checks/CI. |
| `pyproject.toml` | Install the src package in editable mode. |
| `.github/workflows/ci.yml` | Unit tests, catalog/vector and saved-output checks. |
| `.gitignore` | Prevent local secrets and runtime files from entering Git. |

Week 2 instructions are historical, not the current retrieval entry point. External-model scripts require the colleague’s own API keys and may incur API charges; no such calls were run during packaging.
