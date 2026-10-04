# Retrieval Evaluation Framework, Version 1.0

## Decision and scope

This framework evaluates **retrieval of supplied course materials**, not generated answer correctness. The benchmark compares five arms on the same 50 English questions and PostgreSQL catalog: BGE vector-only, Qwen vector-only, BGE plus full-text search, Qwen plus full-text search, and the production two-model plus full-text hybrid. Questions are balanced by course and difficulty. Source files are AI-prepared and unverified, so labels are **source-grounded silver labels** pending instructor adjudication. A good score means the system found the specified supplied evidence; it does not certify that the course material is academically correct.

The design follows the separation of retrieval/process and response/system evaluation in [Microsoft Foundry's RAG evaluators](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators), the positive/negative retrieval tests and precision/recall/MRR guidance in the [Azure retrieval evaluation guide](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-information-retrieval), the structural risks described in the [Azure chunking guide](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-chunking-phase), and the accuracy/latency/cost pillars in [NVIDIA's enterprise RAG guide](https://docs.nvidia.com/enterprise-reference-architectures/enterprise-rag-retrieval-scaling-and-sizing-guide/latest/summary.html). These sources inform the design; the numeric gates below are local pilot choices, not claimed industry standards.

## Frozen dataset and controls

- 50 questions: 25 Calculus I and 25 Number Theory I; each course has 8 easy, 9 medium, and 8 hard questions.
- Easy questions target one localized definition, method, or objective. Medium questions need a relationship or two evidence units. Hard questions need synthesis across units, detect a scope boundary, or test refusal on missing evidence.
- 46 answerable questions have one or more **required evidence groups**. A group contains one or more acceptable passage IDs (OR); all groups must be found for a complete answer (AND). Four questions are challenge cases: two out-of-scope and two absent-information questions.
- The first question set and evidence anchors were written and validated against source snapshots before the first model run. A coverage audit then found that 68 of 74 evidence groups targeted textbook-reference files. That complete run and its dataset are archived in `benchmark_archive/v1/`. Version 2 changes questions and anchors to cover 46 textbook-reference, 16 context, and 13 syllabus groups; this revision was frozen before version-2 model runs. Its metrics must not be compared to version-1 metrics as if the dataset were unchanged. The dataset SHA-256, model revisions, vector input SHA-256, retrieval settings, environment, and run time are recorded with results.
- The exact same questions, filters, candidate limit (40), top-k (6), and context limit (12,000 characters) run in every arm. The two vector-only arms isolate embedding behavior; the two single-model hybrid arms hold the lexical channel fixed while changing the embedding; the two-model hybrid measures the deployed pipeline.
- No answer-model judgments or stochastic LLM-as-judge scores enter the primary metrics. Instructor review of the questions and a pooled relevance judgment set is a required later step.

## Primary measures

| Dimension | Operational definition | Desired direction |
| --- | --- | --- |
| Required-group recall@k | Across answerable questions, number of gold evidence groups represented by a retrieved passage by rank k / total gold groups. | Higher |
| Complete-evidence@k | Fraction of answerable questions with **every** required evidence group present by rank k. This is the main content-interruption measure for multi-part questions. | Higher |
| Any-evidence@k and MRR | Fraction with at least one gold group at k; reciprocal rank of the first gold passage, averaged over answerable questions. | Higher |
| Course routing@k | Fraction of answerable questions with the expected course among the first k results. Cross-course retrieval stays enabled. | Higher |
| Scope/issue leakage | Count of default results carrying a non-pilot scope or overlapping an unresolved source review issue. | Zero |
| Citation/source integrity | Fraction of returned excerpts whose passage ID, file, line span, scope, and text match the database and whose nonblank LaTeX lines occur in order within the source snapshot span. | 100% |
| Context preservation | Fraction of returned excerpts reproduced in full in the assembled context, plus gold-group coverage **inside the final context**. A hit dropped by the context budget is a miss. | Higher |
| Negative-query unsupported retrieval | For absent-information questions, count returned passages and whether any contains the specifically requested unavailable fact. Because the current retriever has no abstention threshold, irrelevant returned passages are reported rather than mislabeled as true abstentions. | Lower |
| Latency and footprint | Batch wall time, encoding versus retrieval time where measurable, result-context characters, and indicative single-query wall time on this machine. | Lower, subject to accuracy |

Report @1, @3, and @6 for positive retrieval; slice by course, difficulty, source role, and multi-evidence versus single-evidence. Report failures by question ID and expected passage IDs. A mean alone can hide hard-question failures. The 50 questions are too few to justify a precise production SLA; confidence intervals and repeated runs are desirable before a release decision.

## Secondary and deferred measures

Precision@k and nDCG@k require **complete relevance judgments for the pooled top-k candidates**, not merely one preselected anchor per question. Treating every unlisted passage as irrelevant would unfairly penalize correct alternative evidence. This run therefore reports candidate lists and label gaps, but does not claim a validated precision or nDCG score. After blind, instructor-led pooling, label each candidate 0 (irrelevant), 1 (topically related), 2 (partially answering), or 3 (direct, sufficient evidence); then compute precision@k at grade >=2 and nDCG@k. Keep adjudication independent of system identity and rank. This mirrors the ground-truth-label requirement and “holes” concern in [Foundry document retrieval evaluation](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators).

Generated-answer groundedness, correctness, completeness, citation use, instruction-injection resistance, concurrency throughput, and production cost are **not measured** by a retrieval-only pipeline. They require an answer model, a human-reviewed answer key, adversarial cases, and production-like load. See the [Azure end-to-end RAG evaluation guide](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-llm-evaluation-phase) for why retrieval and answer evaluation should be documented separately.

## Pilot gates and interpretation

The proposed internal pilot gates are required-group recall@6 >= 0.85, complete-evidence@6 >= 0.75 overall and >= 0.60 on hard answerable questions, course routing@3 >= 0.95, zero scope/known-issue leakage, and 100% citation/source integrity. These gates are deliberately explicit so failures cannot be hidden by a single aggregate score. **Even passing them does not authorize student-facing use while source status remains unverified.** A negative query that returns apparently relevant but nonanswering snippets is a design issue requiring a calibrated abstention/coverage check before launch.

The benchmark must be rerun after source, chunking, embeddings, filtering, fusion, or context-budget changes. Preserve the old and new run artifacts so each change has an attributable effect.
