# Retrieval tool (V1 prototype)

Course knowledge retrieval as a **tool the tutoring model calls**. Code decides when the tool is required, optional or not offered for each tutoring action. A validated retrieval plan decides what to search for. The search itself is the Week 3 retrieval code, unchanged. Every result is checked against the stated needs, and every citation is checked before it reaches the student.

- Design and contracts: [`specs/rag-retrieval.md`](../../../specs/rag-retrieval.md) (PR #11, JDP-36)
- JSON Schemas of the exchanged records: `specs/schemas/` (generated from this code by `scripts/export_schemas.py`)
- Jira: JDP-42 (tool on shared interfaces), JDP-43 (status and failure handling), JDP-44 (dataset integration, partly)

## Layout

```text
retrieval-tool/
├── retrieval_tool/          the package
│   ├── policy.py            grounding policy: 12 tutoring actions → must / may / not_needed / must_not
│   ├── planner.py           retrieval plan: concept linking → draft → model refinement → code validation
│   ├── tool_schema.py       the tool the model sees; builds RetrievalRequest (system fields injected)
│   ├── service.py           RetrievalRequest → GroundingBundle / RetrievalStop (preflight, Week 3 search, evidence check)
│   ├── backends.py          Week 3 pgvector search (real), replay of Week 3 runs, offline test stand-in
│   ├── evidence.py          evidence check per need: rules, plus the Jev judge
│   ├── jev_decider.py       Jev settles "may" turns
│   ├── citations.py         labels P1, P2… for the model; citation check before delivery
│   ├── agent_loop.py        reference turn loop: policy → model → tool → answer → citation check
│   ├── schemas.py           JSON Schemas of the records; validate_record()
│   ├── records.py           record builders and bundle invariants
│   ├── llm.py               OpenAI-compatible adapter (DeepSeek, Gemini, Kimi, OpenAI) + scripted test model
│   └── __init__.py          build_tutoring_runtime(): the recommended setup in one call
├── scripts/                 demo and evaluation scripts (see below)
├── tests/                   99 offline tests
├── data/                    Course Context copy, demo scenarios, labelled evaluation cases
└── results/                 sample inputs/outputs from real runs (2026-10-29)
```

## Setup

Python 3.11+. The Week 3 index and retrieval code live on the branch `Sean/-Retrieval-working`. Check that branch out into a separate folder and point `DP_RETRIEVAL_ROOT` at it:

```bash
git worktree add ../retrieval-week3 origin/Sean/-Retrieval-working
export DP_RETRIEVAL_ROOT="$(cd ../retrieval-week3 && pwd)"
pip install numpy jsonschema
```

| Variable | Needed for | Default |
|---|---|---|
| `DP_RETRIEVAL_ROOT` | Everything: the Week 3 catalog, benchmark and rules | `../output/github-ready` |
| `WEEK3_KB` | Live search: a local Week 3 `knowledge_base` folder (Docker database settings and model cache) | `../week3/knowledge_base` |
| `WEEK5_JEV` | Optional: the Week 5 Jev client. Without it, rules and the main AI model take over | `../week5 jev` |
| `DEEPSEEK_API_KEY` | Optional: real-model demos and evaluations. Type it in; never store it | — |

## Run

From this folder:

```bash
python -m unittest discover -s tests
python scripts/benchmark_check.py --replay-only
```

- **Tests** run offline. Tests that need the Week 3 index skip when `DP_RETRIEVAL_ROOT` is not set; the schema-file tests skip until `specs/schemas/` exists.
- **The replay check** feeds Week 3's saved search results through the tool and confirms the same passages come back (46/46).
- **Live search** (`python scripts/benchmark_check.py` without `--replay-only`) needs the Week 3 Docker database and the BGE / Qwen encoders. It currently runs on Sean's machine; the results are in `results/week3_alignment.json`.

Real-model demos need an API key:

```bash
read -s "DEEPSEEK_API_KEY?DeepSeek key: "; export DEEPSEEK_API_KEY
python scripts/demo_turn.py --all --llm deepseek
```

| Script | What it does |
|---|---|
| `demo_turn.py` | Six tutoring turns end to end: explain, inspect, probe, out of corpus, another course |
| `benchmark_check.py` | Week 3 vs the tool path on the 50 benchmark questions |
| `eval_tool_decisions.py` | Who should decide "may" turns: the main AI model, Jev, or both (24 labelled turns) |
| `eval_evidence_judge.py` | Rules vs Jev on "does this passage state the need?" (28 labelled pairs) |
| `eval_planning.py` | Does the plan pick the right course concept? Code vs code + model (36 labelled turns) |
| `export_schemas.py` | Writes the JSON Schemas; `--check` fails if they are out of date |

## Results (2026-10-29, Sean's machine, main AI model = DeepSeek)

| File | Shows |
|---|---|
| `demo_*_deepseek.json` | Full records of six real turns: request, bundle, answer, citation check, events |
| `week3_alignment.json`, `week3_alignment_replay.json` | Tool path = Week 3 with the course filter, passage for passage |
| `tool_decisions_all.json` | 22/24 with Jev + model vs 17/24 with the model alone |
| `evidence_judge_eval.json` | Jev 0 false "covered" vs 8 for the rules (28 pairs) |
| `planning_eval*.json` | Right concept 22/36 (code only) and 35/36 (code + model) |
| `grounding_policy_table.json`, `tool_definition.openai.json`, `retrieval_plan_example.json` | The policy table, the tool as the model sees it, and three worked plans |

The demo records were produced before two later changes, so they lack bundle `course_id` / `question_id` and use plan format @1. Everything else in them matches the schemas.

## Notes

- The development corpus is AI-made course outlines, so passages are `unverified` and have no page numbers yet (spec Appendix I).
- Jev writes a response cache to `cache/` inside this folder. It is local; do not commit it.
- The main AI model is not chosen yet. DeepSeek is only what the current tests use.
