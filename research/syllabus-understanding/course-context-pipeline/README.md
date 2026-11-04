# Course Context — Stage A pipeline

Turns a course **syllabus** into a structured **CourseContext JSON** (Course,
Module, Concept, LearningObjective, Source), per
[`specs/course-context.md`](../../../specs/course-context.md) §2 (Stage A).

**Provider-agnostic & configurable:** the syllabus, prompt, output path, and the
LLM (`base_url` / `model` / key) all come from config or CLI flags — nothing is
hardcoded. Default LLM is **local Ollama** (free, no key).

## Pipeline (Phase 1)

```
intake → generate → validate → (regenerate on errors) → write → flag → review.json
```

- **Validate** (`validate.py`) — the conformance gate (rules V-01..V-10 from
  `specs/course-context.validation-and-flagging.md`; warnings disabled in v1).
  Errors **block publication**: an invalid result is never written to the published
  output path (a clearly-marked `<out>.rejected.json` is written instead) and it
  drives regeneration.
- **Flag** (`flag.py`) — on a zero-error file, writes a human-review worklist
  (`<out>.review.json`) of AI-inferred "check-first" fields (rules F-01/F-03).
  Every inferred check-first field is flagged; each assumption's optional
  `confidence` orders the list (shakiest first) but never suppresses a review item.

### QuestionSchema builder (Phase 3)

Builds the per-question **QuestionSchema** target (what the Tutoring Engine consumes)
from a **validated CourseContext** + a free-text **question**, per `course-context.md`
§3.2/§3.3. This is the **runtime path** (`origin: runtime`): the question isn't in a
bank, so the builder uses an LLM (provider-agnostic — DeepSeek/OpenAI/Ollama) to solve
it and write the teaching content.

```bash
python -m course_context_pipeline.build_question_schema \
    --course-context ../../../specs/examples/calc1.course-context.json \
    --question "\\int x\\cos(x) dx" \
    --base-url https://api.deepseek.com/v1 --model deepseek-chat \
    --api-key-env DEEPSEEK_API_KEY \
    --out output/qs.xcosx.json
```

- **Copied verbatim from the CourseContext:** `learning_objectives`, misconception
  `description`/`mitigation`, prerequisite names, `source_ids`.
- **Written by the LLM:** `correct_approach`, `alternative_approaches`,
  `reference_answer`, each prerequisite `relevance`, each misconception `cue`, and
  `question_type`/`expected_response_modes`.
- **Derived:** the runtime id `<primary concept>.adhoc-<8 hex>` (SHA-1 of the
  normalised prompt) and `built_from.content_sha256` (the exact CourseContext bytes).

**Independent answer verification.** The LLM does not grade itself — for an integral it
supplies a machine-parseable `{variable, integrand, antiderivative}` and **`sympy`**
differentiates the claimed antiderivative and compares it to the integrand. A *refuted*
answer is rejected (no schema, nonzero exit); an uncheckable one is written with
`answer_verification.status = "unverified"` and **must not** be trusted as ground truth.

**Gated output.** The builder runs a full `validate_question_schema` (top-level
fields, enums, CourseContext references, nested structures, provenance, and
concept↔copied-record consistency). An invalid QuestionSchema is **not** published —
it's written to `<out>.rejected.json` and the CLI exits nonzero.

Concept match goes through a replaceable **`ConceptMatcher`** interface (`(prompt,
concepts) -> (primary_id, related_ids)`), so Sean's retrieval can be dropped in without
changing the builder. The default matcher asks the LLM to pick from the CourseContext's
concept
list, or you pass `--concept-id <id>` to set it explicitly (never a free guess).

### Validate / flag an existing file (no generation)

```bash
# runs the Validator + Flagger on a file, prints the report, exits 1 on any error
python -m course_context_pipeline.cli --validate-only \
    --from-json ../../../specs/examples/calc1.course-context.json
```

### Generation strategies

A whole CourseContext can exceed a model's per-response output cap (e.g.
`deepseek-chat` ≈ 8K tokens), which truncates the JSON mid-file. Pick a strategy
with `--strategy` (or the `--by-module` shortcut):

| Strategy | Calls | When to use |
|---|---|---|
| `single` (default) | 1 (whole file) | large-output models (Claude Sonnet, gpt-4.1) |
| `by_module` | 1 outline + 1 per module | small/cheap caps (DeepSeek, Ollama) — never truncates |

`by_module` generates the Course + module shells first, then fills each module
(its concepts, objectives, sources) in its own call, feeding earlier concept IDs
forward so cross-module prerequisites resolve, and finally assembles + validates the
whole file. Each individual call retries on a parse failure, and the whole pass is
**regenerated on validation errors** up to `max_attempts` — the same gate as `single`.

## Setup

```bash
cd research/syllabus-understanding/course-context-pipeline
pip install -r requirements.txt            # openai, pypdf, PyYAML, python-dotenv

# local, free: have Ollama running with a model pulled
ollama pull qwen3:8b        # (already present on this machine)
```

## Run (from the repo root)

```bash
cd research/syllabus-understanding/course-context-pipeline

# 1) See what intake extracts — no model call:
python -m course_context_pipeline.cli --dry-run

# 2) Full run with local Ollama (free):
python -m course_context_pipeline.cli

# 3) No LLM at all — re-emit a known-good CourseContext (for building Phases 2–3):
python -m course_context_pipeline.cli --from-json ../../../specs/examples/calc1.course-context.json
```

Output goes to `output/calc1.course-context.generated.json` by default.

## Switching provider (no code change)

```bash
# OpenAI
python -m course_context_pipeline.cli --base-url https://api.openai.com/v1 \
    --model gpt-4o --api-key-env OPENAI_API_KEY

# OpenRouter / DeepSeek / JHU Gateway: just change --base-url, --model, --api-key-env.

# DeepSeek, chunked (recommended for its ~8K output cap):
python -m course_context_pipeline.cli --by-module \
    --base-url https://api.deepseek.com/v1 --model deepseek-chat \
    --api-key-env DEEPSEEK_API_KEY --out output/calc1.deepseek-chat.json
```

Keys live in `.env` (copy from `.env.example`); never commit real keys.
See `config.example.yaml` for the full set of options.

## A note on local-model quality

`qwen3:8b` is small. Generating the *entire* Calc I CourseContext (6 modules, 33
concepts with objectives and sources) in one pass is hard for an 8B model —
expect a partial or lower-quality result. Phase 1's goal is a **working,
provider-agnostic pipeline**; swap in a stronger hosted model (or run per-module)
for quality once a key is available.

## Tests

Automated tests cover intake, JSON extraction, module assembly + source
de-duplication, basic structural validation, config precedence, and the
`--from-json` path. No network or model is used.

```bash
cd research/syllabus-understanding/course-context-pipeline
python -m pytest            # 28 tests, offline
```
