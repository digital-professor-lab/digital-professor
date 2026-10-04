# Cross-Course Knowledge Base and Retrieval: Implementation Plan

## Goal and initial scope

Students and instructors can ask questions without first specifying a course. The system finds relevant evidence across each course's syllabus, course context, and textbook reference, then supplies a small, traceable evidence set to an answer model. Student work submitted with a question remains part of that request and is not automatically added to the shared course library.

The initial pilot uses two courses and three LaTeX files per course. It supports text questions and already-transcribed problem statements. Handwriting recognition, specialized mathematical-expression search, and complex multi-chapter reasoning are later extensions.

## Knowledge-base structure

| Logical layer | Contents | Purpose |
| --- | --- | --- |
| Source files | Original supplied LaTeX files, checksums, and versions | Preserve complete context and enable reprocessing |
| Section passages | Text and formulas split along the LaTeX section hierarchy | Provide citable source evidence |
| AI-derived concept cards | Concept names, aliases, short descriptions, and links to passages | Navigate across courses; never replace source evidence |
| Course catalog | Courses, source roles, section trees, scope, access, and versions | Filter, group, and govern the material |

These are logical layers rather than a requirement for four separate databases. A reference implementation stores source files in file storage and catalog relationships in PostgreSQL; full-text and vector indexes can be added over the concept cards and section passages. Another existing search service can be substituted if it preserves the same data contract.

### Minimum fields

- Document: `document_id, course_id, source_type, title, version, review_status, original_path, checksum`.
- Passage: `passage_id, document_id, course_id, section_path, locator, raw_latex, readable_text, parent_section_id, embedding_version`.
- Concept card: `concept_id, names_and_aliases, short_summary, course_ids, linked_passage_ids, review_status`.

The locator must identify a real position in the supplied source file. If a course summary lacks original textbook page numbers, cite the summary's section or line; do not invent textbook page numbers. Distinguish verified lecture records from AI-generated course context.

### Ingestion sequence

1. Register each course and its three source roles; record versions and file checksums.
2. Parse LaTeX headings, text, formulas, and tables. Retain the raw LaTeX alongside a readable representation. Expand or alias custom macros when needed.
3. Split primarily at section and paragraph boundaries while keeping definitions, formulas, and conditions together. Link small passages to their parent sections.
4. Link AI-derived concept cards to specific passages. Mark cards without a reliable source link for review.
5. Have instructors spot-check the section tree, formula preservation, and concept links before publishing an index version.

## Future online retrieval flow

**Input:** `question, user_id, optional_course_id, task_type, optional_transcribed_work`.

**Output:** `answer, status, selected_courses, citations[], evidence_ids[], ambiguity_note`.

1. Determine which courses the user may access. Preserve the original question and extract clear course names, section numbers, formulas, and key terms.
2. Search both concept cards and source passages across eligible courses using full-text and vector search. Do not rely only on cards or force a single course decision before searching.
3. Merge and deduplicate candidates; group by course, concept, source type, and section.
4. Judge which passages actually answer the question. Expand to a parent section or adjacent passage when the short match lacks essential context. Add a reranker only when evaluation shows a measurable benefit.
5. Select evidence according to the question. Syllabus is primary for course scope; verified context is needed for claims about instruction; textbook material is primary for definitions and methods. Do not fill a fixed quota from all three source types.
6. If multiple courses provide different valid interpretations, explain the ambiguity or ask for a course choice. If essential evidence is missing, return an insufficient-evidence state.
7. Send selected passages, source identifiers, the user question, and response constraints to the answer model. Validate every cited identifier and record the index version used.

The answer model receives an evidence package with `passage_id, course, source_type, section_path, excerpt`, rather than several unlabeled passages selected solely by vector similarity. Candidate and evidence counts should be tuned with an evaluation set, not fixed in advance at “top three.”

## Implementation milestones

| Stage | Work | Deliverable | Exit criterion |
| --- | --- | --- | --- |
| A. Sources and test set | Select two courses; confirm file status and scope; collect instructor questions | Source inventory, data contract, 20–30 initial test questions | Each question has an expected course and acceptable evidence; include unanswerable and ambiguous cases |
| B. Ingestion | Parse LaTeX, split sections, link concept cards, version outputs | Browsable course catalog and ingestion report | Sample passages map back to the correct source lines; formulas and hierarchy are preserved |
| C. Retrieval | Implement full-text and vector candidate generation, course grouping, ranking, and section expansion | `retrieve(question)` service and evidence list | Instructors can find the intended evidence; wrong-course and unauthorized evidence is excluded |
| D. Answering | Connect the existing model call to dynamic evidence, source rules, and citation validation | End-to-end cited answer demo | Important claims trace to evidence; ambiguity and insufficient-evidence cases behave correctly |
| E. Improvement | Categorize failures in parsing, recall, ranking, source selection, and generation | Evaluation report and prioritized repairs | Add query rewriting, reranking, or formula search only for demonstrated failure modes |

The existing Week 2 prototype's task selection, source-role policy, and output validation can be reused. Its fixed single-lesson packet would be replaced by dynamically retrieved evidence. The Week 3 workflow demo remains an architecture illustration, not a measured retrieval implementation.

## Evaluation

**Evaluate retrieval separately:** instructors label the expected course and necessary sections. Measure whether required evidence appears near the top, how early the first correct result appears, wrong-course contamination, and false matches for unanswerable questions.

**Evaluate answers separately:** check whether important claims have supporting evidence, citations open to the stated source, source roles are respected, and AI-authored summaries are not presented as original textbook or lecture records.

**Record operating metrics:** stage latency, embedding requests, answer-model input size, cost per question, index version, and user feedback. Set launch thresholds only after a baseline exists.

## Inputs requiring project-team confirmation

1. The pilot files' actual status: original text, AI summary, or instructor-reviewed material.
2. Which courses each student or instructor can access, including any semester or class separation.
3. The expected question and material languages, which affect aliases and embedding evaluation.
4. Instructor availability to label the initial questions and source passages.

These decisions do not prevent the catalog build, but they affect retrieval implementation and acceptance criteria.
