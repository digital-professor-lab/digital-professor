# Retrieval Policy Update

Same frozen Week 3 version-2 dataset; all six arms use the new explicit-request guards. This is a post-hoc diagnostic comparison, not independent validation.

Soft limits reduce priority by 5% for each selection above the preferred count, but never discard a candidate solely because its file reached that count. This is a concentration heuristic, not an evidence-completeness judge.

| Mode / file preference | Complete@6 | Group recall@6 | Fixed | Regressed | False Not found |
| --- | ---: | ---: | --- | --- | --- |
| hard_2 | 0.870 | 0.920 | none | none | none |
| hard_4 | 0.957 | 0.973 | Q02, Q16, Q43, Q46 | none | none |
| hard_5 | 0.957 | 0.973 | Q02, Q16, Q43, Q46 | none | none |
| soft_2 | 0.957 | 0.973 | Q02, Q16, Q43, Q46 | none | none |
| soft_4 | 0.957 | 0.973 | Q02, Q16, Q43, Q46 | none | none |
| soft_5 | 0.957 | 0.973 | Q02, Q16, Q43, Q46 | none | none |

## Explicit Not found cases

- Q24: not_found / outside_course_scope
- Q25: not_found / lecture_record_unavailable
- Q49: not_found / unconfirmed_semester_scope
- Q50: not_found / student_record_unavailable

## Limits

Not found guards match explicit requests for excluded courses/semesters and unavailable lecture/student records. They do not certify general semantic answerability. Found means passages were returned, not that they prove an answer. Sources remain unverified; top-6 and the context budget can still omit necessary evidence.
