# Retrieval tool (V1 prototype)

Course knowledge retrieval as a **tool the tutoring model calls**. The Tutoring Engine or coordinator applies the agreed grounding policy and decides whether a turn's search is required, optional or unnecessary. Retrieval provides the policy table and a search recommendation, then validates and runs the accepted request. A validated retrieval plan decides what to search for. The search itself is the Week 3 retrieval code, unchanged. Every result is checked against the stated needs, and every citation is checked before it reaches the student.

- Design and contracts: [`specs/rag-retrieval.md`](../../../specs/rag-retrieval.md) (PR #11, JDP-36)
- JSON Schemas of the exchanged records: `specs/schemas/` (generated from this code by `scripts/export_schemas.py`)
- Jira: JDP-42 (tool on shared interfaces), JDP-43 (status and failure handling), JDP-44 (dataset integration, partly)

## Quick start

Python 3.11+. From this folder:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
python scripts/smoke_check.py
python -m unittest discover -s tests
```

These commands need no Docker, API key, model download or other working tree. From the repository root, the smoke check is:

```bash
python research/knowledge-retrieval/retrieval-tool/scripts/smoke_check.py
```

It checks imports, schema generation and validation, planner behaviour, request and failure records, the citation check and one stubbed retrieval turn.

## Test results

| Setup | Result |
|---|---|
| `pip install -e ".[test]"` | 126 tests: 100 pass, 26 skip |
| Also `bash scripts/setup_week3.sh` | 126 tests: 107 pass, 19 skip |
| Also `pip install -e ".[postgres]"` | 126 tests: 126 pass |

These counts assume `specs/schemas/` is present (PR #11). Until it is, the two schema-file tests also skip.

The core tests use the local fixture in `data/fixture_corpus/`, a small subset of the Week 3 catalog. Its term-overlap search is a test stand-in, so it says nothing about search quality. Each skipped test states what it needs. `tests/test_week3_integration.py` holds the tests that need Week 3, and none of them needs Docker, an API key or a model download.

## Dependencies

| Extra | Install | Used for |
|---|---|---|
| `test` | `pip install -e ".[test]"` | Core tests and the smoke check |
| `replay` | `pip install -e ".[replay]"` | Replay of Week 3's saved results; also run `bash scripts/setup_week3.sh` |
| `postgres` | `pip install -e ".[postgres]"` | Week 3 search code on PostgreSQL and pgvector |
| `embeddings` | `pip install -e ".[embeddings]"` | BGE and Qwen query encoders for live search |
| `integrations` | No packages | The model-provider and Jev clients use only the standard library. They need an API key |

## Week 3 dependency

The Week 3 code and data are pinned to one commit. This script checks that commit out into `.week3/`, which git ignores:

```bash
bash scripts/setup_week3.sh
```

To use another checkout, set `DP_RETRIEVAL_ROOT`.

| Variable | Needed for | Default |
|---|---|---|
| `DP_RETRIEVAL_ROOT` | Replay and integration tests | `.week3/` |
| `WEEK3_KB` | Live search: a local Week 3 `knowledge_base` folder (Docker database settings and model cache) | `../week3/knowledge_base` |
| `OPENROUTER_API_KEY` or `TYPESAFE_API_KEY` | Optional: Jev. Without a key, rules and the main AI model take over | — |
| `JEV_ENV_FILE` | Optional: a private `.env` file holding the Jev key | `../week5 jev/.env` |
| `DEEPSEEK_API_KEY` | Optional: real-model demos and evaluations. Type it in; never store it | — |

## Other runs

After `bash scripts/setup_week3.sh`:

```bash
python scripts/benchmark_check.py --replay-only
```

This replay feeds Week 3's saved search results through the tool and confirms that the same passages come back (46/46).

Live search needs the Week 3 Docker database and the BGE and Qwen encoders. It currently runs on Sean's machine:

```bash
pip install -e ".[postgres,embeddings]"
python scripts/benchmark_check.py
read -s "DEEPSEEK_API_KEY?DeepSeek key: "; export DEEPSEEK_API_KEY
python scripts/demo_turn.py --all --llm deepseek
```

| Script | What it does |
|---|---|
| `smoke_check.py` | The self-contained check above |
| `setup_week3.sh` | Checks out the pinned Week 3 commit |
| `demo_turn.py` | Six tutoring turns end to end; `--llm scripted --test-double` runs on the local fixture |
| `benchmark_check.py` | Week 3 vs the tool path on the 50 benchmark questions |
| `eval_tool_decisions.py` | Who should settle `may` turns: the main AI model, Jev, or both (24 labelled turns) |
| `eval_evidence_judge.py` | Rules vs Jev on "does this passage state the need?" (28 labelled pairs) |
| `eval_planning.py` | Does the plan pick the right course concept? Code vs code + model (36 labelled turns) |
| `export_schemas.py` | Writes the JSON Schemas; `--check` fails if they are out of date |
| `build_fixture_corpus.py` | Maintainers only: rebuilds the local fixture from Week 3 |

## Layout

```text
retrieval-tool/
├── retrieval_tool/          the package
│   ├── policy.py            grounding policy table and pure helper; the Engine or coordinator applies it
│   ├── planner.py           retrieval plan: concept linking → draft → model refinement → code validation
│   ├── tool_schema.py       the tool the model sees; builds RetrievalRequest (system fields injected)
│   ├── service.py           RetrievalRequest → GroundingBundle / RetrievalStop (preflight, search, evidence check)
│   ├── backends.py          Week 3 pgvector search (real), replay of Week 3 runs, in-memory stand-in over Week 3 code
│   ├── local_fixture.py     local fixture search for core tests and the smoke check; no Week 3 code
│   ├── evidence.py          evidence check per need: rules, plus the Jev judge
│   ├── jev_client.py        Jev API client: cache, retries, cost tracking, offline mock
│   ├── jev_recommender.py   Jev recommends a search on `may` turns
│   ├── citations.py         labels P1, P2… for the model; citation check before delivery
│   ├── agent_loop.py        reference turn loop: caller's decision → model → tool → answer → citation check
│   ├── schemas.py           JSON Schemas of the records; validate_record()
│   ├── records.py           record builders and bundle invariants
│   ├── llm.py               OpenAI-compatible adapter (DeepSeek, Gemini, Kimi, OpenAI) + scripted test model
│   └── __init__.py          build_tutoring_runtime(): the recommended setup in one call
├── scripts/                 setup, smoke, demo and evaluation scripts
├── tests/                   core tests, plus test_week3_integration.py
├── data/                    Course Context copy, local fixture, demo scenarios, labelled evaluation cases
└── results/                 current fixtures, evaluation summaries and historical run records
```

## Who decides what

`run_turn` requires the caller's accepted decision:

```python
decision = recommend_grounding(action_type)     # the Engine or coordinator applies the agreed policy
result = run_turn(llm, service, ctx, decision=decision, recommender=recommender)
```

`recommend_grounding` is a pure lookup. The recommender is optional, and it is consulted only on `may` turns. Retrieval does not choose a tutoring action or override the caller's decision.

## Results

| File | Shows |
|---|---|
| `results/fixtures/stubbed_explain_turn.json` | Current request, bundle and citation check from a stubbed turn. Validated by a test; rewrite with `smoke_check.py --write-fixture` |
| `results/historical/2026-10-29/demo_*_deepseek.json` | Six real turns from 2026-10-29. They predate the current schemas ([details](results/historical/README.md)) |
| `results/week3_alignment.json`, `results/week3_alignment_replay.json` | Tool path = Week 3 with the course filter, passage for passage |
| `results/tool_decisions_all.json` | 22/24 with Jev + model vs 17/24 with the model alone |
| `results/evidence_judge_eval.json` | Jev 0 false "covered" vs 8 for the rules (28 pairs) |
| `results/planning_eval*.json` | Right concept 22/36 (code only) and 35/36 (code + model) |
| `results/grounding_policy_table.json`, `results/tool_definition.openai.json`, `results/retrieval_plan_example.json` | The policy table, the tool as the model sees it, and three worked plans |

The evaluation numbers are from 2026-10-29 on Sean's machine, with DeepSeek as the main AI model. They have not been rerun since the code was reorganised for review.

## Notes

- The development corpus is AI-made course outlines, so passages are `unverified` and have no page numbers yet (spec Appendix I).
- Jev writes a response cache to `cache/` inside this folder. Git ignores it.
- The main AI model is not chosen yet. DeepSeek is only what the current tests use.
