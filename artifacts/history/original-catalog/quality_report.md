# Ingestion Quality Report

This build creates a document catalog, section passages, and source-linked concept cards. It does not generate embeddings or implement retrieval.

| Course | Source type | Section nodes | Passages | Concept cards |
| --- | --- | ---: | ---: | ---: |
| calc1 | syllabus | 10 | 12 | 6 |
| calc1 | context | 29 | 24 | 7 |
| calc1 | textbook_reference | 19 | 117 | 94 |
| number_theory_1 | syllabus | 18 | 16 | 9 |
| number_theory_1 | context | 25 | 23 | 13 |
| number_theory_1 | textbook_reference | 29 | 29 | 87 |

## Provenance and scope

- All six files have Claude-based names and appear to be AI-authored or AI-organized course materials. Their review status is `unverified`.
- `textbook_reference` is a textbook-based course breakdown or design package, not the complete original textbook. Citations may point only to this supplied file and its sections or lines.
- The `context` files alone do not prove that a particular instructor covered specific material in class.
- Calculus II content in the calculus context and the textbook-based look-ahead is marked `outside_pilot_course_*` and must not be treated as Calculus I evidence by default.
- The second-semester number theory context is marked `second_semester_scope_unconfirmed`; instructor confirmation is needed.

## Validation

- All six snapshots match the SHA-256 checksums of the input files.
- SQLite foreign-key validation passes; every concept card links to a source passage.
- Formulas remain in `raw_latex`; `readable_text` is only a preview and must not replace the original when citing.
- Sections and passages retain source-file line numbers for instructor review.

- `Number_Content_Claude.tex` has a trailing `t` after `\end{document}`. It does not affect body parsing; the input file was not modified.
- Review issue `number_theory_cyclotomic_split_count` at `Number_Claude_Interactive.tex:171`: The draft states that 2 gives three unramified primes of residue degree 3 in Q(zeta_7). Since [Q(zeta_7):Q] = 6 and 2 has order 3 modulo 7, the expected number is 6/3 = 2, not 3. The source was not edited.