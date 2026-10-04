# Retrieval refinement: scope contract and query coverage

This is a post-hoc comparison on the frozen 50-question silver-label set, not independent-topic or answer-generation validation.

| Configuration | Complete@6 | Complete in final context | Group recall@6 | Mean context characters | Regressions vs full-6 |
| --- | ---: | ---: | ---: | ---: | --- |
| full_6 | 0.957 | 0.957 | 0.973 | 8869 | none |
| facets_6 | 1.000 | 1.000 | 1.000 | 8879 | none |
| full_8 | 0.957 | 1.000 | 0.973 | 11430 | none |

## What changed

- Scope policy distinguishes excluded scope, mixed/ambiguous scope, filter conflicts and missing source types. Explicit exclusions and background study are not treated as requested scopes.
- Report 1.1 carries rule matches, reasons, requested/allowed scopes, source requirements and next actions. Found does not imply sufficient evidence. Blocked/clarification outputs carry no answer excerpts.
- Explicit compare/contrast and theorem-plus-application questions produce up to two focused queries. Original top evidence and up to two results per facet compete within the existing top-6/budget limits. Comparison facets additionally blend character-ngram lexical relevance with fusion to preserve technical terms and word forms.
- Fusion score is retained separately from selection score; query matches and selection reasons expose the new behavior.

## Limits

The remaining Q11/Q18 gold anchors had ranked seventh under full-query selection. Facet retrieval recovered both without reading labels at runtime. This does not verify textbook correctness or final answer quality. Rules do not identify every unsupported topic or every phrasing; instructors and new-topic holdouts are still needed. Extra facet queries incur additional embedding and database work.
