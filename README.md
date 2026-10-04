# Digital Professor — structured course retrieval

[中文说明](README.zh-CN.md) · [File guide](docs/FILE_GUIDE.md)

This project turns six supplied Calculus I / Number Theory I course files into a source-traceable knowledge base, two embedding indexes, and a hybrid retriever. It returns original evidence and a structured search report for downstream LLM input, evaluation and validation. It does not generate answers or expose a web API.

This is the organized team-sharing copy of the Week 3–4 work. Earlier presentation reports and Week 2 model experiments are kept as history. This is a research prototype with engineering-oriented organization, not a production release.

## Understand it in five minutes

1. Open [Week 4 report](docs/reports/week4/digital-professor-week4-report.html) locally in your browser.
2. Read the three schema roles below, then [the file guide](docs/FILE_GUIDE.md).
3. Inspect [50-question outputs](artifacts/evaluations/refinement_runs/facets_6.jsonl) and [the retrieval contract](contracts/retrieval_report.schema.json).
4. Use the quick start if you want to run the system. You can inspect reports and saved data without Docker or model downloads.

## What each step does

| Step | Input → work → output | Code |
| --- | --- | --- |
| 1. Knowledge | Six LaTeX sources → parse courses, files, sections, passages and concept links → SQL/JSONL catalog | `src/digital_professor/knowledge/` |
| 2. Embeddings | Source-linked texts → shared token-bounded inputs → normalized BGE and Qwen3 vectors | `src/digital_professor/embeddings/` |
| 3. Database | Catalog and vector exports → import into PostgreSQL/pgvector → source and search indexes | `infra/postgres/`, `src/digital_professor/database/` |
| 4. Retrieval | Question and filters → scope/source checks, vector + keyword search, fusion, evidence selection → cited originals + report | `src/digital_professor/retrieval/` |
| 5. Evaluation | Questions and expected evidence → compare retrieved groups and output decisions → per-question metrics and reports | `src/digital_professor/evaluation/` |

Three schemas serve three jobs: **knowledge input** keeps stored records consistent; **retrieved evidence** identifies each passage for LLM input; **retrieval report** records the request, outcome and process for validation and possible re-retrieval. `found` means evidence was returned, not that a final answer is verified. Scores are rankings, not confidence probabilities.

## Project structure

```text
github-ready/
├── README.md / README.zh-CN.md    # Start here / 从这里开始
├── src/digital_professor/
│   ├── knowledge/               # Parse and validate course knowledge
│   ├── embeddings/              # Prepare, encode, validate vectors
│   ├── database/                # Import and validate PostgreSQL
│   ├── retrieval/               # Search, scope policy, output checks
│   ├── evaluation/              # Benchmarks and experiments
│   └── paths.py                 # Shared portable paths
├── infra/postgres/              # SQL, Docker Compose, .env.example
├── contracts/                   # JSON interchange schema
├── data/
│   ├── sources/                 # Six source files
│   ├── catalog/                 # Linked knowledge records + SQLite
│   ├── embeddings/              # Shared inputs + two vector exports
│   └── benchmark/               # 50 questions + source hashes
├── tests/                       # Retrieval and request behavior tests
├── artifacts/
│   ├── evaluations/             # Saved runs; new evaluations write here
│   ├── history/                 # Frozen original catalog / DB reports
│   └── validation/              # Packaging verification results
├── docs/
│   ├── FILE_GUIDE*.md           # File-by-file guide in both languages
│   ├── reports/                 # Week 1–4 presentation reports
│   ├── architecture/            # Workflow diagrams and system reports
│   ├── research/                # Integration discussion PDFs
│   └── history/                 # Original notes and design decisions
├── archive/                     # Week 1 drafts / Week 2 model prototype
├── tools/                       # Offline package verification
├── requirements.lock.txt        # Captured runtime dependencies
├── requirements-test.txt        # Small test-only dependency set
├── pyproject.toml               # Importable src package
├── .github/workflows/ci.yml      # Offline-data checks in CI
└── .gitignore                   # Exclude local secrets / runtime state
```

## Quick start: reuse the included exports

Use Python 3.11+ (the local checks used Python 3.12) and Docker with Compose. Run commands from this repository root. Dependencies include PyTorch and embedding libraries; installation/model downloads can be large. The lock file captures the working environment rather than guaranteeing every OS/CPU combination.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python -m pip install --no-deps -e .
```
The catalog and small vector matrices are already included. These checks do not need an answer model, database or API keys:

```bash
python -m digital_professor.knowledge.validate_kb
python -m digital_professor.embeddings.validate_embeddings
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/verify_saved_results.py
```
For live retrieval, initialize your own database:

```bash
cp infra/postgres/.env.example infra/postgres/.env
# Edit infra/postgres/.env and choose your own POSTGRES_PASSWORD.
docker compose --project-directory infra/postgres -f infra/postgres/compose.yaml up -d --wait
docker compose --project-directory infra/postgres -f infra/postgres/compose.yaml exec -T database psql -v ON_ERROR_STOP=1 -U coursekb -d course_knowledge < infra/postgres/schema.sql
python -m digital_professor.database.import_data
python -m digital_professor.database.validate_deployment
python -m digital_professor.retrieval.search "What does the Fundamental Theorem of Calculus say about accumulation?" --format json
```

The query models download on first use into ignored `.cache/`; the vectors alone do not replace those models. The default database is `course_knowledge`, user `coursekb`, localhost port `55432`. If that port is occupied, add `DP_DB_PORT=55433` to the local `infra/postgres/.env`; Compose, import, validation and retrieval all read it. Never commit the real `.env`.

The import replaces catalog/vector rows in this project's database. Stop it without removing data:

```bash
docker compose --project-directory infra/postgres -f infra/postgres/compose.yaml stop
```

## Rebuild when sources change

```bash
python -m digital_professor.knowledge.build_kb
python -m digital_professor.knowledge.validate_kb
python -m digital_professor.embeddings.prepare_embedding_inputs
python -m digital_professor.embeddings.generate_embeddings bge_base_en_v1_5
python -m digital_professor.embeddings.generate_embeddings qwen3_embedding_0_6b
python -m digital_professor.embeddings.validate_embeddings
python -m digital_professor.evaluation.build_benchmark
python -m digital_professor.database.import_data
python -m digital_professor.database.validate_deployment
```

Rebuilding overwrites current derived files; preserve an experiment version before changing source material. Review benchmark anchors when content changes. `prepare_embedding_inputs` resolves model revisions at preparation time; preserve the existing manifests when reproducing pinned vectors. The catalog uses repository-relative source paths. `paths.py` resolves them independently of the current working directory.

## Run evaluations

```bash
python -m digital_professor.evaluation.evaluate_refinement
python -m digital_professor.evaluation.evaluate_paraphrases
```

These commands use live models/database and write new results to `artifacts/evaluations/`. Save a historical copy first if you need the previous run. Other comparison scripts are described in the file guide.

## Progress and validation limits

The saved current benchmark covers all annotated evidence groups for **46/46 answerable questions**, and all **4/4 scope/missing-source questions** return `not_found` with empty evidence. Together, the 50 cases meet the expected retrieval outcomes. Six supplementary phrasings reach 5/6. The labels are provisional and source-grounded; the supplied materials remain unverified. This is not teacher-verified textbook accuracy or generated-answer evaluation.

For this reorganization, the catalog was rebuilt and validated, both vector exports checked, package imports and 13 behavior tests passed, and the saved 50-case output was checked against the relocated sources. Docker was unavailable during packaging, so live DB initialization and fresh model retrieval were not rerun. See [packaging validation](artifacts/validation/packaging-checks.json).

## Historical records

`artifacts/evaluations/` contains preserved earlier runs with their original hashes and paths. `artifacts/history/original-catalog/` preserves the catalog those results used. Current runnable records are under `data/`. Do not silently relabel old runs as results of the reorganized implementation. Original notes under `docs/history/` and the Week 2 archive may mention old paths; use this README for current commands.

The source materials are course design/outline files, not complete original textbooks. Source locations are LaTeX line numbers, not textbook page numbers. No credentials, model weights, Python environments or live database files are included. Start with a private team repository; confirm sharing rights before making course materials public.
