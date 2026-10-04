# Hybrid course-material retrieval

`search.py` is the first working retrieval pipeline for the two-course knowledge base. It searches PostgreSQL/pgvector and returns source passages with file names, line ranges, and a ready-to-use LLM context or prompt. It does **not** call an answer model.

## Retrieval flow

1. Accept an English question. Search both courses unless a course ID is supplied.
2. Encode the question with the pinned BGE and Qwen models. BGE uses its recommended retrieval instruction; Qwen uses the model's built-in `query` prompt. The stored document vectors remain unchanged.
3. Retrieve vector neighbors from both pgvector tables and exact/broad matches from PostgreSQL English full-text search.
4. Fuse ranked candidate lists with reciprocal rank fusion. Map concept-card hits back to their evidence passages and collapse overlapping segments of the same passage.
5. Apply course/scope and known-issue filters, rank source passages, softly discourage concentration in one file, and assemble a bounded context from the original LaTeX with source markers.

The default scope is `pilot_course_or_general`. Second-semester number-theory material marked `second_semester_scope_unconfirmed` and Calculus II material marked outside the Calculus I pilot are opt-in. Any passage overlapping an unresolved review issue is excluded by default. All source files remain marked `unverified`; that state appears in results and the LLM prompt. `textbook_reference` means an AI-prepared textbook-based breakdown, not the complete original textbook.

The numeric `score` is only a ranking value. It is not an answer-confidence probability. The pipeline can identify relevant course outlines that still lack enough detail to answer a question; the LLM prompt explicitly requires an insufficient-evidence response in that case.

## Current refined policy (October 1, 2026)

The second refinement supersedes the initial update below. See [the refinement comparison](refinement_report.md), [the report schema](retrieval_report.schema.json), and `request_policy.py`.

- Request policy is based on requested scopes and required source types. It distinguishes explicit exclusions, background study, mixed scopes, conflicting course filters and unspecified semesters. Source availability is checked for the selected course, rather than borrowing another course's source types.
- Reports add `schema_version="1.1"` and a structured `scope_assessment`: decision, category, reason, requested/allowed scopes, required/available source types, matched rule text, explanation and next action. `needs_clarification` differs from `not_found`. Empty evidence distinguishes no matches from candidates that could not fit the context budget. A small runtime contract checks status/evidence consistency; the standalone JSON Schema describes the interchange structure.
- The four-passage soft preference remains. Explicit compare/contrast and application questions also get up to two focused search queries. Up to two pieces of evidence per facet are reserved alongside the original strongest result, subject to the same six-passage and excerpt budgets. Comparison facets blend normalized fusion (60%) with character-ngram TF-IDF relevance (40%) to improve matching of focused technical terms. This heuristic does not read benchmark labels or certify evidence completeness.
- `score` remains the fusion ranking score; `selection_score` and `selection_reason` describe selection, and `query_matches` records facet support. `facet_candidate_counts` is separate from original-query candidate counts. None of these scores is a confidence probability.
- The 50-question post-hoc rerun found all required gold groups for 46/46 answerable questions, with zero source-integrity/scope errors and no positive questions blocked. All four challenge questions were blocked with specific explanations. Six new wordings of the two known cases achieved 5/6 completeness, so wording robustness remains limited. This is not independent-topic, teacher-verified or answer-level validation.

```bash
week3/knowledge_base/.venv/bin/python week3/knowledge_base/retrieval/evaluate_refinement.py
week3/knowledge_base/.venv/bin/python week3/knowledge_base/retrieval/evaluate_paraphrases.py
week3/knowledge_base/.venv/bin/python -m unittest discover -s week3/knowledge_base/retrieval -p 'test_*.py' -v
```

Use `--no-query-decomposition` to compare full-question retrieval with the same policy. Extra queries add local embedding/database work. Ambiguous or unsupported topics without explicit scope/source signals may still return related passages. `found` means returned evidence, not a verified answer.

## Initial policy update (October 1, 2026; historical comparison)

The default is now `max_per_document=4, document_limit_mode="soft"`. Four is a preference, not a cap: when a file has already supplied four passages, each further selection incurs a 5% priority discount. Strong same-file evidence can still be selected. The original fusion `score` is retained; final list order also reflects the soft selection preference. Top-k (6), the excerpt budget (12,000 characters), course filters and known-issue filters remain binding. This heuristic does not judge whether all necessary evidence is present.

Every report now adds `status` (`found` or `not_found`), `message`, and `not_found_reason`. Explicit requests for Calculus II or unconfirmed second-semester material return `Not found` unless the matching opt-in is enabled. Requests for instructor words/lecture recordings or personal student grades return `Not found` when the catalog lacks `lecture_record` or `student_record` sources. These are narrow request-pattern guards, not a general semantic answerability detector. Empty final evidence also returns `Not found`. Rejected questions skip embedding generation. `found` means passages were returned, not that they prove the requested answer.

The [policy comparison](policy_update_report.md) keeps the original benchmark untouched. Six hard/soft settings (2, 4, 5) were compared on the same frozen 50 questions. Soft-4 recovered four previously incomplete questions: 44/46 complete (95.7%), with no previously successful question regressing; all four challenge questions returned `Not found`, and none of the 46 answerable questions was rejected. Two answerable questions remain incomplete. Same-set, post-hoc improvements need independent questions and instructor review before broader conclusions.

```bash
week3/knowledge_base/.venv/bin/python week3/knowledge_base/retrieval/evaluate_policy_update.py
cd week3/knowledge_base/retrieval
../.venv/bin/python -m unittest test_search_policy -v
```

## Command line

Start Docker as described in [the database guide](../postgres/README.md). From the project root:

```bash
week3/knowledge_base/.venv/bin/python week3/knowledge_base/retrieval/search.py "What does the Fundamental Theorem of Calculus say about accumulation?" --format prompt
```

`--format json` (the default) includes the ranked results and assembled context. `--format context` prints just the numbered source excerpts. `--format prompt` prints a full, citation-aware prompt to send to an answer model.

Inspect a saved [JSON search result](examples/sample_search.json) and its [LLM prompt](examples/sample_llm_prompt.txt) for one number-theory question.

Useful controls:

```bash
--course-id calc1
--course-id number_theory_1
--model bge_base_en_v1_5
--model qwen3_embedding_0_6b
--include-unconfirmed
--include-outside-course
--include-flagged
--top-k 6
--context-chars 12000
--vector-only
--max-per-document 4
--document-limit-mode soft
```

Repeat `--model` to use both explicitly; both are used by default. The `--include-flagged` option is for manual investigation of known source errors and adds issue details to the result. It should not be used for ordinary student answers.
`--vector-only` disables the keyword channels and is primarily useful for embedding-model comparisons.
`--max-per-document` is the preferred per-file count in soft mode (default 4). `--document-limit-mode hard` restores a strict cap; combine it with `--max-per-document 2` to compare the former selection policy. Explicit-request guards remain enabled in both modes.

## Python integration

```python
from retrieval.search import Retriever, format_llm_prompt

with Retriever() as retriever:
    report = retriever.search_many(["How do fractional ideals work?"], top_k=6)[0]

source_passages = report["results"]
answer_prompt = format_llm_prompt(report)
```

Import the module from `week3/knowledge_base` on `PYTHONPATH`. The `results` list contains stable passage IDs, course IDs, source type, section path, file name, snapshot path, line range, scope/review status, known issues, match signals, and original LaTeX. `context` is the corresponding source-marked string. One process can batch several questions with `search_many`; query models are loaded once per batch. The database password is read from the private local `postgres/.env` file.

## Verification

Run the small cross-course smoke test:

```bash
week3/knowledge_base/.venv/bin/python week3/knowledge_base/retrieval/evaluate_retrieval.py
```

The [evaluation report](evaluation_report.md) records ranked file/line citations for five sample questions. The test checks expected course presence in the top three, citation paths, and exclusion of the known issue. It is not a relevance benchmark; an instructor-labeled question set is needed before treating retrieval or generated answers as reliable.

## Fifty-question benchmark

The [evaluation framework](evaluation_framework.md) defines retrieval coverage, multi-evidence completeness, source continuity, safety, and latency. [Dataset version 2](benchmark_50.jsonl) contains 50 English questions with source-anchored silver labels; its [manifest](benchmark_manifest.json) fixes the hash. The [full report](benchmark_report.md), [machine-readable results](benchmark_results.json), and `benchmark_runs/` preserve all five arms: each embedding model alone, each plus keyword search, and both together with keyword search.

```bash
week3/knowledge_base/.venv/bin/python week3/knowledge_base/retrieval/build_benchmark.py
week3/knowledge_base/.venv/bin/python week3/knowledge_base/retrieval/run_benchmark.py
week3/knowledge_base/.venv/bin/python week3/knowledge_base/retrieval/diagnose_failures.py
week3/knowledge_base/.venv/bin/python week3/knowledge_base/retrieval/ablate_file_cap.py
```

The [failure diagnosis](failure_diagnostics.md) traces missed evidence to candidate retrieval or final selection. The [post-hoc file-cap ablation](file_cap_ablation.md) records the earlier hard-4 experiment; the later [policy update](policy_update_report.md) evaluates the new soft default. Historical benchmark outputs describe the prior implementation. Rerunning the full benchmark replaces its outputs with results for the current policy; use the separate policy comparison to preserve them. The earlier, textbook-heavy dataset and its complete run are preserved in `benchmark_archive/v1/`. None of these results substitutes for instructor review or answer-level evaluation.
