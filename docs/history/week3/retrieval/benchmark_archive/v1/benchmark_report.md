# Fifty-Question Retrieval Benchmark

Run time (UTC): 2026-09-25T02:29:30.493738+00:00

Frozen dataset SHA-256: `b0151e5bfae7a36a444c5987b27a6577c2cd7ef4bd09ae634df637aab283cc0f`

The same 50 English questions were run through five configurations. Labels are source-anchored silver labels, not instructor-approved relevance judgments. See [the framework](evaluation_framework.md) and [the full question set](benchmark_50.jsonl).

## Main results

| Arm | Group recall@6 | Complete@6 | Any@6 | MRR | Route@3 | Hard complete@6 | Batch seconds | DB p95 seconds | Single p95 seconds* |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bge_vector | 0.865 | 0.783 | 1.000 | 0.817 | 1.000 | 0.667 | 4.39 | 0.004 | 0.95 |
| qwen_vector | 0.919 | 0.870 | 1.000 | 0.759 | 1.000 | 0.667 | 4.32 | 0.006 | 1.31 |
| bge_hybrid | 0.905 | 0.848 | 1.000 | 0.700 | 1.000 | 0.750 | 1.52 | 0.029 | 0.65 |
| qwen_hybrid | 0.905 | 0.848 | 1.000 | 0.734 | 1.000 | 0.583 | 3.33 | 0.027 | 2.02 |
| two_model_hybrid | 0.919 | 0.870 | 1.000 | 0.779 | 1.000 | 0.667 | 3.42 | 0.029 | 2.38 |

The batch time includes local model loading, batched query encoding, and 50 sequential database searches. DB p95 covers retrieval/assembly only; it excludes embedding. *Single p95 is the interpolated 95th percentile of only three sequential single-question runs per arm; it is indicative, not a production SLA. Batch times are affected by model-cache warm-up and fixed run order.

## Depth and safety

| Arm | Group recall@1 | Group recall@3 | Complete@1 | Complete@3 | Scope/issue leaks | Source integrity failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bge_vector | 0.460 | 0.797 | 0.348 | 0.696 | 0 | 0 |
| qwen_vector | 0.378 | 0.838 | 0.283 | 0.761 | 0 | 0 |
| bge_hybrid | 0.351 | 0.743 | 0.326 | 0.674 | 0 | 0 |
| qwen_hybrid | 0.351 | 0.770 | 0.326 | 0.674 | 0 | 0 |
| two_model_hybrid | 0.419 | 0.838 | 0.348 | 0.739 | 0 | 0 |

## Per-course and difficulty slices

| Arm | Calculus complete@6 | Number Theory complete@6 | Easy | Medium | Hard |
| --- | ---: | ---: | ---: | ---: | ---: |
| bge_vector | 0.783 | 0.783 | 1.000 | 0.667 | 0.667 |
| qwen_vector | 0.826 | 0.913 | 1.000 | 0.889 | 0.667 |
| bge_hybrid | 0.826 | 0.870 | 1.000 | 0.778 | 0.750 |
| qwen_hybrid | 0.826 | 0.870 | 1.000 | 0.889 | 0.583 |
| two_model_hybrid | 0.826 | 0.913 | 1.000 | 0.889 | 0.667 |

## Source role, multi-evidence, and context packing

| Arm | Syllabus group recall | Context group recall | Textbook-reference group recall | Multi-evidence complete@6 | Budget skips | File-cap skips | <6 results |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bge_vector | 1.000 | 0.750 | 0.868 | 0.600 | 0 | 363 | 6 |
| qwen_vector | 1.000 | 1.000 | 0.912 | 0.760 | 0 | 426 | 12 |
| bge_hybrid | 1.000 | 1.000 | 0.897 | 0.720 | 0 | 308 | 6 |
| qwen_hybrid | 1.000 | 1.000 | 0.897 | 0.720 | 0 | 378 | 12 |
| two_model_hybrid | 1.000 | 1.000 | 0.912 | 0.760 | 0 | 348 | 4 |

Role recall uses the first annotated source role for each required group; one group may have acceptable alternatives. Budget and file-cap skips count rejected candidates, not necessarily lost gold evidence.


## Production-arm failures

- **Q11** (calc1, medium): required groups first found at ranks [2, None]; retrieved passages: pass_ae947d97398aa4ae, pass_1887ae1399f483e7, pass_f71cd171e2a80e28, pass_23fdd4b2075dbfa8, pass_c29f4b54a65141d6, pass_3d950206ca145b5d.
- **Q16** (calc1, medium): required groups first found at ranks [3, None]; retrieved passages: pass_a944a6476809fb0d, pass_a4d8e9b45d05e148, pass_0d4823a870862d5b, pass_b1ea7da0cc5090da, pass_8bbaeebc4a5fbcac, pass_c29f4b54a65141d6.
- **Q18** (calc1, hard): required groups first found at ranks [2, None]; retrieved passages: pass_c29f4b54a65141d6, pass_68edaab41e209872, pass_ca8208b6f1998122, pass_02b1aed7998fbcaa.
- **Q23** (calc1, hard): required groups first found at ranks [None, 3]; retrieved passages: pass_ae947d97398aa4ae, pass_3d950206ca145b5d, pass_af178a2e01fd8290, pass_c42d73788db8c80f, pass_f71cd171e2a80e28, pass_a9534ac83d4c9332.
- **Q43** (number_theory_1, hard): required groups first found at ranks [None, 2, 1]; retrieved passages: pass_19c974fb8f89c01f, pass_642e1c7e1d536f82, pass_82491cef89faf92b, pass_eb3af25e10a50c8d, pass_9677bb898534fbb9, pass_f46db0cf49729a5c.
- **Q46** (number_theory_1, hard): required groups first found at ranks [None, 1]; retrieved passages: pass_c74fda829b6931cd, pass_5954b54d5c510397, pass_f46db0cf49729a5c, pass_c42bb5b895ef5c57, pass_56d546085febf549, pass_684cdaf19ceed9cc.

## Pilot gate check

- group_recall_at6 >= 0.85: PASS
- complete_at6 >= 0.75: PASS
- hard_complete_at6 >= 0.60: PASS
- course_routing_at3 >= 0.95: PASS
- scope_and_issue_leaks = 0: PASS
- citation_integrity_failures = 0: PASS

The production arm passes 6/6 retrieval pilot gates. These gates do not override the unverified status of the source materials.

## Negative and scope challenges

- `bge_vector`: 0/2 excluded anchors leaked; 2/2 absent-information questions still returned snippets.
- `qwen_vector`: 0/2 excluded anchors leaked; 2/2 absent-information questions still returned snippets.
- `bge_hybrid`: 0/2 excluded anchors leaked; 2/2 absent-information questions still returned snippets.
- `qwen_hybrid`: 0/2 excluded anchors leaked; 2/2 absent-information questions still returned snippets.
- `two_model_hybrid`: 0/2 excluded anchors leaked; 2/2 absent-information questions still returned snippets.

The current retrieval code does not have a calibrated abstention threshold. Returning a topical passage for an absent fact is not evidence that the fact exists. The answer prompt asks the LLM to say when evidence is insufficient, but answer behavior has not been tested. This is a release blocker despite the quantitative retrieval gates above passing.

## Interpretation and limits

- Gold groups were selected from supplied passages before running the models. Other valid passages may exist; the numbers measure source-anchor coverage, not exhaustive human relevance.
- Content interruption is measured by missing required evidence groups and by exact source/context integrity. A correct answer may still need facts absent from these course outlines.
- Precision@k and nDCG are deliberately withheld until a blind, pooled relevance review labels all top candidates.
- This is a local, sequential, batched run on a two-course, 476-vector corpus. It is not a concurrency, large-corpus, or end-to-end answer-generation benchmark.
- Recommended next work: instructor adjudication of the 50 questions and sources, a calibrated insufficient-evidence/abstention policy, and answer-grounding tests after the LLM is connected.
