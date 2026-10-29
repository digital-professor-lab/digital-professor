# Course Context — Stage A pipeline

Turns a course **syllabus** into a structured **CourseContext JSON** (Course,
Module, Concept, LearningObjective, Source), per
[`specs/course-context.md`](../../../specs/course-context.md) §2 (Stage A).

**Provider-agnostic & configurable:** the syllabus, prompt, output path, and the
LLM (`base_url` / `model` / key) all come from config or CLI flags — nothing is
hardcoded. Default LLM is **local Ollama** (free, no key).

## Pipeline (Phase 1)

```
intake → generate → (basic structural check / regenerate) → write CourseContext JSON
```

Full validation + review flagging (Phase 2) and the QuestionSchema builder
(Phase 3) are separate steps; the hook points are already in `pipeline.py`.

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
forward so cross-module prerequisites resolve, and finally assembles + checks the
whole file. Per-call parse failures retry up to `max_attempts`.

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
