# Course Context — V1 Module Specification

| | |
|---|---|
| **Spec ID** | `course-context` |
| **Spec version** | `0.4.0` (draft for team review) |
| **Date** | 2026-10-12 |
| **Owner** | Course Context module (Ovunc) |
| **Data schema versions** | `1.0` (core fields) and `1.1` (adds a per-record `provenance` field the syllabus-to-JSON prompt emits, section 1.4) |
| **Question Schema version** | `1.0` (proposed, section 3) |
| **Consumers** | Sean (retrieval), Jonathan (student evidence), Tutoring Engine, Yining (presentation) |
| **Companion spec** | `course-context.validation-and-flagging.md` — the Validator and Review Flagger tools used in the pipeline (section 2.1) |
| **Companion files** | `course-context.example-calc1.md` (worked Calculus I example); `templates/` (course-context, question-schema, student-state, gap-record, tutoring-action); `examples/calc1.course-context.json`, `examples/calc1.question-schema.xcosx.json`; `diagrams/course-context-io.mmd` (+ `.svg`, `.png`) |

**Status labels.** Sections marked *Normative* are owned by the Course Context module. Sections marked *Proposed (cross-team)* describe records the Course Context module only consumes or helps define; they need agreement from the other owners before they are fixed. Keywords MUST, SHOULD and MAY are used as in RFC 2119.

**Changelog**

| Version | Date | Change |
|---|---|---|
| 0.4.0 | 2026-10-12 | Moved the worked Calculus I example (former §6) and its deviations appendix into a separate informative document, `course-context.example-calc1.md`, expanded there with the end-to-end tutoring trace (Student-State / Gap Record / Tutoring Action) from the design page. §6 is now a pointer; the former Appendix B (Files) becomes Appendix A. |
| 0.3.0 | 2026-10-12 | Re-added the Validate → Flag → Review steps to the pipeline (§2.1), now specified in the companion tool spec `course-context.validation-and-flagging.md` rather than inline. The validation rules and the review-flagging logic live there. §2.5 ties to the Review Flagger's worklist. |
| 0.2.0 | 2026-10-12 | Removed the Python tooling (validator and provenance annotator) and all rule-based validation content (V/W/Q rules). Dropped `review_status`/`review_notes` and the review-status workflow; schema 1.1 now adds only `provenance` (`source_backed`/`ai_inferred`), which the syllabus-to-JSON prompt emits directly. Section 2.5 kept as an advisory human-check list. |
| 0.1.0 | 2026-10-12 | First draft: Course Context requirements, syllabus-to-JSON workflow, Question Schema, shared tutoring concepts, downstream dependencies, Calculus I example, open questions. |

---

## 1. Course Context requirements *(Normative)*

Course Context is the structured, linked description of one course that the rest of the Digital Professor reads. It is produced once per course from course materials (section 2), reviewed by a human, and then consumed read-only.

### 1.1 Entity model and links

```mermaid
flowchart LR
    Course -- "module_ids / course_id" --> Module
    Module -- "concept_ids / module_id" --> Concept
    Concept -- "prerequisite_ids (acyclic)" --> Concept
    Concept -- "objective_ids / concept_id" --> LearningObjective
    Concept -- "source_ids" --> Source
    Concept -- "question_ids / concept_ids" --> AssessmentQuestion
    AssessmentQuestion -- "objective_ids" --> LearningObjective
```

The chain Course → Module → Concept → LearningObjective → AssessmentQuestion → Source is a reading order, not the storage layout. **Concept is the hub.** Objectives, sources and questions all attach to a Concept, and a question reaches its sources only through its concepts. Prerequisites are Concept → Concept links, not a separate record type.

| Link | Stored as | Reverse stored as | Cardinality |
|---|---|---|---|
| Course → Module | `Course.module_ids` (teaching order) | `Module.course_id` | 1..n |
| Module → Concept | `Module.concept_ids` | `Concept.module_id` | 1..n |
| Concept → Concept (prerequisite) | `Concept.prerequisite_ids` | none | 0..n, acyclic |
| Concept → LearningObjective | `Concept.objective_ids` | `LearningObjective.concept_id` | 1..n |
| Concept → Source | `Concept.source_ids` | none | 0..n (SHOULD be at least 1) |
| Concept ↔ AssessmentQuestion | `Concept.question_ids` | `AssessmentQuestion.concept_ids` | many-to-many, 0..n per concept |
| AssessmentQuestion → LearningObjective | `AssessmentQuestion.objective_ids` | none | each objective MUST belong to one of the question's concepts |
| AssessmentQuestion → Source | derived: `concept_ids` → `Concept.source_ids` | not stored | |

Where a link is stored in both directions, the two sides MUST agree.

### 1.2 Field requirements for V1

`MUST` means present and non-empty. `MUST*` means present, and an empty array is allowed (the course is a skeleton for that field). `MAY` means optional.

**Envelope**

| Field | Type | Req | Notes |
|---|---|---|---|
| `schema_version` | string | MUST | `1.0` or `1.1` |
| `Course` | object | MUST | exactly one |
| `Module`, `Concept`, `LearningObjective`, `Source`, `AssessmentQuestion` | arrays | MUST | at least one `Module` and one `Concept` |
| `assumptions` | array | SHOULD | generator-logged inferences, shape in section 2.4. Consumers MUST NOT fail when it is absent. |

**Course**

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | string | MUST | lowercase slug, e.g. `calc1` |
| `title` | string | MUST | |
| `level` | string | MUST | SHOULD be one of `undergraduate introductory`, `undergraduate advanced`, `master's`, `doctoral` |
| `duration_weeks` | integer ≥ 1 | MUST | usually inferred, see 2.3 |
| `assumed_background` | string | MUST | what students know on arrival |
| `module_ids` | string[] | MUST (≥ 1) | in teaching order |

**Module**

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | string | MUST | `<course>.<NN>-<slug>`, `NN` = teaching order from `01` |
| `course_id` | string | MUST | |
| `title` | string | MUST | |
| `goal` | string | MUST | one sentence |
| `weeks` | string | MUST | `"3"` or `"3-4"` |
| `concept_ids` | string[] | MUST (≥ 1) | |

**Concept**

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | string | MUST | `<module id>.<slug>` |
| `module_id` | string | MUST | |
| `name` | string | MUST | |
| `summary` | string | MUST | one or two sentences |
| `key_definitions` | string[] | MUST* | only the terms that need a precise statement |
| `prerequisite_ids` | string[] | MUST* | Concept IDs in the same or an earlier module. Empty when the only prerequisite is assumed background; log that in `assumptions`. |
| `objective_ids` | string[] | MUST* | SHOULD have at least 1 |
| `difficulty_notes` | `{misconception, mitigation}`[] | MUST* | exactly those two keys per entry |
| `source_ids` | string[] | MUST* | SHOULD have at least 1 |
| `question_ids` | string[] | MUST* | |

**LearningObjective**: `id` (MUST), `concept_id` (MUST), `text` (MUST), `bloom_level` (MUST, one of `remember`, `understand`, `apply`, `analyze`, `evaluate`, `create`).

**Source**: `id` (MUST), `type` (MUST, one of `syllabus`, `textbook`, `lecture_notes`, `reading`, `other`), `citation` (MUST), `section` (MUST), `text_chunk` (MUST, non-empty; see 2.3 and open question 2).

**AssessmentQuestion**

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | string | MUST | `<concept id>.q<n>` |
| `concept_ids` | string[] | MUST (≥ 1) | |
| `objective_ids` | string[] | MUST* | each must belong to one of `concept_ids` |
| `type` | string | MUST | `homework`, `quiz`, `midterm`, `final`, `project`, `participation-prompt` |
| `difficulty` | string | MUST | `recall`, `application`, `analysis` |
| `prompt` | string | MUST | |
| `solution` | string | MUST | full worked answer |
| `rubric` | string | MUST | short grading guide |
| `common_wrong_answers` | string[] | MUST* | |
| `requires_figure` | boolean | MUST | `true` means the instructor must supply the figure the prompt describes; no image is ever generated |

**Additive field, schema 1.1** (every record, including `Course`): `provenance` (MUST in 1.1). Definition in 1.4. Core 1.0 fields are unchanged, so a 1.1 file reduces to a valid 1.0 file by deleting this field and setting `schema_version` back.

**Minimum viable Course Context.** One Course, at least one Module, at least one Concept per Module. Each Concept SHOULD have at least one LearningObjective. Questions, sources and difficulty notes may be empty arrays. The Question Schema builder degrades gracefully on such a skeleton (section 3.3).

### 1.3 IDs and linking

| Entity | ID pattern | Example |
|---|---|---|
| Course | `<slug>` | `calc1` |
| Module | `<course>.<NN>-<slug>` | `calc1.06-integral-applications` |
| Concept | `<module id>.<slug>` | `calc1.06-integral-applications.by-parts` |
| LearningObjective | `<concept id>.lo<n>` | `calc1.06-integral-applications.by-parts.lo1` |
| AssessmentQuestion | `<concept id>.q<n>` | `calc1.06-integral-applications.by-parts.q1` |
| Source | `<source slug>.<locator>` | `neuhauser.s7-2` |

- IDs MUST be lowercase, dot-delimited, and unique within a file. Consumers SHOULD treat them as opaque strings and follow links instead of parsing them. Only the ad hoc question ID (3.3) depends on the pattern.
- `Source.id` is independent of module and concept because one source can back several concepts. It is unique per file only (open question 3).
- A prerequisite link means: a student must already be able to use the listed concept to work on this one. The target MUST be in the same or an earlier module, and the graph MUST be acyclic. In the Calculus I file there are 60 prerequisite links, 26 of them crossing module boundaries.
- Question IDs for questions that are not in the bank are defined in 3.3.

### 1.4 Provenance (schema 1.1)

`provenance` says where a record's content came from. The syllabus-to-JSON prompt emits it per record as it generates the file (section 2.2); it is not added by a separate step.

| `provenance` | Meaning |
|---|---|
| `source_backed` | every non-structural value on the record is stated in, or mechanically copied from, supplied course material |
| `ai_inferred` | at least one non-structural value was generated by the model beyond what the material states |

**Weakest-link rule.** A record's `provenance` is the weakest of its non-structural fields (IDs and link arrays do not count). A Concept whose `name` comes from a syllabus line but whose `summary` was written by the model is `ai_inferred`.

Field-level detail lives in `assumptions[]` (section 2.4): each entry names the record and field the model inferred and why. A record named by an exact-ID `assumptions` entry MUST NOT be `source_backed`.

For the Calculus I file this makes all 32 Source records `source_backed` and every other record `ai_inferred` — under the weakest-link rule, every non-Source record in a syllabus-only file has at least one model-written field.

### 1.5 Source materials for V1

**V1 input is one syllabus** (PDF or pasted text) and nothing else.

| | Requirement |
|---|---|
| MUST contain | course title; an ordered list of units or topics |
| SHOULD contain | textbook citation; chapter or section references; unit durations |
| Not used in V1 | lecture notes, textbook text, past exams, problem sets |

The one-page Calculus I syllabus (AS.110.106, Johns Hopkins) supplied exactly this: the title, the textbook (Neuhauser and Roper, *Calculus for Biology and Medicine*, 4th ed.), six unit headings with durations written as `2-`, `2`, `3-`, `2+`, `2`, `1+` weeks, and 31 section references (Chapter 1, 2.1 to 7.3). Everything else in the Course Context file is model-written from general calculus knowledge.

**What this means.** A syllabus-only file is a skeleton with plausible content on it. Structure, order and citations are source-backed; summaries, definitions, objectives, prerequisites, difficulty notes, questions and solutions are not. That is why the `provenance` field, the `assumptions` log, and the human checks in 2.5 carry most of the trust signal in V1. Adding lecture notes later would let `Source.text_chunk` hold real excerpts and let summaries and difficulty notes become source-backed. The schema already has room for it (`Source.type = lecture_notes`).

---

## 2. Syllabus-to-JSON workflow *(Normative)*

### 2.1 Pipeline

| # | Step | Input | Output | Who |
|---|---|---|---|---|
| 1 | Intake | syllabus | text the generator can read | person running the pipeline |
| 2 | Generate | syllabus | one JSON object, schema 1.1 (core fields + `provenance` per record) | `syllabus-to-json-prompt.md`, single pass, no questions asked |
| 3 | Validate | generated JSON | pass, or a list of rule violations | Validator (`course-context.validation-and-flagging.md` §3). A file with any error is regenerated, not hand-repaired; capped at a few attempts. |
| 4 | Flag | validated JSON | a review worklist | Review Flagger (`course-context.validation-and-flagging.md` §4); it does not change the file |
| 5 | Review | worklist + file | edits, if any | a human, working the worklist against the fields in 2.5 |
| 6 | Publish | reviewed JSON | the version consumers read | committed to version control; consumers read it read-only |

Steps 3–5 are specified in the companion tool spec, [`course-context.validation-and-flagging.md`](course-context.validation-and-flagging.md); a file with any validation error is regenerated and re-checked, and only a passing file is flagged and reviewed. A human edit in step 5 SHOULD be re-validated before publishing.

### 2.2 What the current prompt does

`syllabus-to-json-prompt.md` is the non-interactive form of the earlier interactive course-breakdown prompt. It reads the material once, asks nothing, and outputs only one JSON object.

| Prompt phase | Fills | Behaviour |
|---|---|---|
| 1. Course-level facts | `Course` | infers title, level, duration and assumed background; folds class format into how concepts are written and assessment philosophy into question `type` values (the schema has no field for either) |
| 2. Modules | `Module` | one per unit, in teaching order, mapped to weeks |
| 3. Concepts and objectives | `Concept`, `LearningObjective` | one concept per independently right-or-wrong idea; Bloom verbs for technical material, discussion verbs for seminar material |
| 4. Prerequisites and difficulty | `prerequisite_ids`, `difficulty_notes` | prerequisites point at earlier concepts; hard concepts get `{misconception, mitigation}` pairs |
| 5. Sources and questions | `Source`, `AssessmentQuestion` | one Source per cited section; 2 to 3 questions per concept over at least two difficulty levels; figures are described, never drawn |
| 6. Assumptions, provenance and assembly | reverse links, `assumptions`, `provenance` | back-fills every `*_ids` array, logs each inference, sets each record's `provenance` (1.4), and checks that every ID resolves |

Its standing rules: output only the JSON; never invent a field other than `assumptions`; never leave a required field null or `"TBD"`.

**Changes this spec needs in the prompt** (not yet made):

| # | Change | Why |
|---|---|---|
| P-1 | Emit `provenance` on every record: `source_backed` only when every non-structural value is copied from the syllabus, otherwise `ai_inferred` (1.4, weakest-link rule) | the prompt now owns provenance; there is no separate annotation step |
| P-2 | If the material has no ordered topic list, output `{"schema_version": "1.0", "error": {"code": "INSUFFICIENT_INPUT", "detail": "<why>"}}` instead of inventing a course | today the prompt can only invent |
| P-3 | `Source.text_chunk` is the verbatim syllabus line, without a label prefix | open question 2 |
| P-4 | Document that `assumptions[].id` may end in `.*` and that `field` may be a non-schema topic such as `format (no schema field)` | the Calculus I file already does both |

### 2.3 Source-backed or AI-inferred, for a syllabus-only run

| Content | Status | Basis |
|---|---|---|
| `Course.title` | source-backed | syllabus header (the abbreviation "Bio. & Soc. Sci." is expanded) |
| `Course.level`, `assumed_background` | inferred | no level or prerequisites are stated |
| `Course.duration_weeks` | inferred | unit durations sum to about 12; the file says 14 |
| `Module.title` | source-backed | unit headings |
| `Module.weeks` | partly | order and counts are stated; the `+` and `-` markers were read as a choice |
| `Module.goal` | inferred | |
| `Concept.name` and the split into concepts | partly | section titles are stated; splits such as Chapter 1 into two concepts, a separate 3.6 concept, and 4.2 versus 4.3 are inferred and logged |
| `Concept.summary`, `key_definitions`, `LearningObjective.*`, `prerequisite_ids`, `difficulty_notes` | inferred | general calculus knowledge; no course text was supplied |
| `Source.citation`, `Source.section` | source-backed | textbook line and section references |
| `Source.text_chunk` | reference only | the syllabus line that cites the section, not textbook text |
| `AssessmentQuestion.*` | inferred | prompts, solutions, rubrics and wrong answers are all model-written; question `type` follows an assumed recall → quiz, application → homework, analysis → midterm mapping |

Under the weakest-link rule, **every non-Source record in a syllabus-only file is `ai_inferred`.** `provenance` therefore separates Source records from the rest; the `assumptions` log (2.4) is the field-level detail that distinguishes the rest (open question 1).

### 2.4 Representing missing, ambiguous and unsupported information

| Situation | The generator MUST | Recorded as |
|---|---|---|
| **Missing**: not in the material but reasonably inferable (level, background) | give one best value, never blank or `TBD` | an `assumptions` entry naming the record and field |
| **Ambiguous**: several readings (`2+ weeks`, `Chapter 1` with no section list) | pick one reading and say which and why | an `assumptions` entry naming the chosen reading |
| **Unsupported**: cannot be known from a syllabus (real textbook text) | not fabricate it | `text_chunk` holds the verbatim syllabus line; the source is treated as reference-only |
| **Not in the schema**: class format, assessment philosophy | fold it into existing fields | an `assumptions` entry with `field` set to a non-schema topic |
| **A blanket policy**: e.g. all difficulty notes come from teaching experience | state it once | a wildcard entry (`id` ends in `.*`) |
| **Insufficient input**: no ordered topic list | not invent a course | the P-2 error object |

`assumptions` entry shape: `{ "entity": "Module", "id": "calc1.04-diff-applications", "field": "weeks", "assumption": "Weeks 8-10.", "reason": "The syllabus says '2+ weeks'; three weeks was assumed to cover the plus." }`

The Calculus I file has 19 entries: 16 name one record and 3 are wildcards (`Concept.difficulty_notes`, `AssessmentQuestion.type`, `AssessmentQuestion.solution`).

### 2.5 What a human should double-check

V1 has no formal review status; the following is an advisory checklist. Before any student-facing use, a human should double-check these fields, hardest-consequence first. The Review Flagger (`course-context.validation-and-flagging.md` §4) turns this list, plus the `assumptions` log, into a per-file worklist so the reviewer knows which records to look at.

| Priority | Fields | Why |
|---|---|---|
| **Check first**, before any student-facing use | `AssessmentQuestion.solution`, `rubric`, `common_wrong_answers` | the engine treats them as ground truth; a wrong solution mis-tutors |
| | `Concept.prerequisite_ids` | drives the prerequisites in every Question Schema, and so the gap diagnosis |
| | `Concept.difficulty_notes` | become the misconceptions in every Question Schema |
| | `Course.assumed_background` | sets what the tutor assumes about every student |
| | `Course.duration_weeks`, `Module.weeks` when inferred | a wrong guess is possible; nothing in V1 logic depends on them |
| | `AssessmentQuestion.requires_figure = true` | the instructor must supply the figure (one question in Calculus I: `calc1.02-limits.continuity.q1`) |
| **Worth checking** | `Concept.summary`, `key_definitions`; `LearningObjective.text`, `bloom_level`; `Module.goal`; `Course.level`; the logged concept splits; question `type` and `difficulty` labels; question `prompt` | wrong but not harmful in the way a wrong solution is |
| **No check needed** | IDs, link arrays, enums, structure | self-consistent by construction: links resolve and ID patterns hold |
| **Spot-check** | `Source.citation`, `Source.section` | source-backed, from the syllabus |

---

## 3. Question Schema *(Normative for creation and content; delivery contract is Proposed with the Tutoring Engine)*

### 3.1 What it is

A Question Schema is the **target** for one question: what a fully correct solution requires. It is built from Course Context plus the specific question, handed to the Tutoring Engine at the start of a session, and never edited afterwards. The Tutoring Engine is the decision maker: it compares the Question Schema with a running estimate of the student (section 4) and picks the next tutoring action. Everything the engine needs to know about *the question* is in this one record. Which team hosts the builder is open (question 11); this section specifies its inputs, outputs and rules.

### 3.2 Template

Fields marked ✔ are in the team's original template; fields marked **+** are additions proposed here, each with the reason.

| Field | Type | Req | Populated from | Note |
|---|---|---|---|---|
| `question_schema_version` | string | MUST | | **+** |
| `question_id` | string | MUST | bank: `AssessmentQuestion.id`; runtime: ad hoc ID (3.3) | **+** it appears in the design page's worked trace but not in its template list |
| `origin` | `bank` or `runtime` | MUST | | **+** says whether the question was in the bank or built on the fly |
| `course_id` | string | MUST | `Course.id` | ✔ |
| `module_id` | string | MUST | `Concept.module_id` of the primary concept | ✔ |
| `concept_ids` | string[] | MUST (≥ 1) | question's concepts, or the matched concepts; primary first | **+** the template had a module but not the concept being tested |
| `prompt` | string | MUST | bank: `AssessmentQuestion.prompt`; runtime: exactly as the student typed it | ✔ |
| `learning_objectives` | `{id, text, bloom_level}`[] | MUST | `LearningObjective` records of `concept_ids`, copied verbatim | ✔ |
| `prerequisite_concepts` | `{concept_id, name, relevance, provenance, derived_from}`[] | MUST* | **direct** `prerequisite_ids` of `concept_ids`; `name` copied; `relevance` written by the builder | ✔ |
| `correct_approach` | `{technique, justification}` | MUST | bank: `AssessmentQuestion.solution` plus `Concept.summary`; runtime: solved by the builder | ✔ |
| `alternative_approaches` | `{technique, justification, provenance, derived_from}`[] | MUST* | builder | **+** the task brief asks for "valid approaches" (plural); `correct_approach` stays the canonical one |
| `reference_solution` | string | MUST | bank: `AssessmentQuestion.solution`; runtime: builder, machine-checked | **+** the engine and the evidence layer need an answer to judge against. MUST NOT be shown to the student. |
| `common_misconceptions` | `{description, cue, mitigation?, provenance, derived_from}`[] | MUST* | `description` and `mitigation` copied verbatim from `Concept.difficulty_notes[i]`; `cue` always written by the builder (Course Context stores no cues) | ✔ |
| `source_reference` | `{concept_ids, source_ids, sibling_question_ids, citation, grounding}` | MUST | `Concept.source_ids`; `grounding` is `reference_only` or `excerpt` | ✔ structured instead of a free-text string |
| `provenance` | enum (1.4) | MUST | weakest link over every element | **+** |
| `built_from` | `{course_context_schema_version, content_sha256}` | MUST | the exact Course Context file used | **+** reproducibility: a session can be replayed against the same data |

`derived_from` is either `runtime` (written by the builder with no Course Context record behind it) or `<record id>#<field path>`, for example `calc1.06-integral-applications.by-parts#difficulty_notes[0]`.

### 3.3 How a Question Schema is created

Input: a course and a question (a bank ID or free text). Output: a Question Schema, or an error.

1. **Resolve the course** by `course_id`.
2. **Bank lookup.** Ask retrieval (Sean) whether the question is the same problem as an `AssessmentQuestion.prompt`. The same *pattern* is not a match. A hit gives `origin = bank`; copy the fields from Course Context and skip to step 6.
3. **Concept match.** Ask retrieval for the concept the question tests (primary, plus at most two related). If nothing matches, return `NO_CONCEPT_MATCH`; the builder never guesses a concept.
4. **Assemble from Course Context.** Objectives and misconception text are copied verbatim. Prerequisites are the concept's direct `prerequisite_ids`. Sources come from `Concept.source_ids`. The nearest bank question on the same concept is recorded as a sibling.
5. **Write and check the runtime parts.** The builder writes `correct_approach`, `alternative_approaches`, `reference_solution`, each `cue`, each prerequisite `relevance`, and any misconception that has no Course Context record. It MUST check the final answer independently where that is machine-checkable (for an integral, by differentiating the result). If the check fails, return an error and no schema.
6. **Identify and freeze.** Runtime questions get the ID `<primary concept id>.adhoc-<8 hex>`, where the 8 hex digits are the start of the SHA-1 of the prompt after Unicode NFKC normalisation, lower-casing and removal of all whitespace. Notation is not canonicalised in V1, so `\int x\cos(x) dx` and `∫ x cos(x) dx` get different IDs. Set `provenance` and `built_from`, then freeze the record.

**Degrading on a skeleton Course Context:** with no difficulty notes the misconception list may be empty or contain only runtime items; with no questions there is no sibling; with no sources `source_ids` is empty.

### 3.4 How it reaches the Tutoring Engine *(Proposed with the Tutoring Engine owner)*

- **One document per question, delivered once** when a session starts or the student moves to a new question. It is self-contained: the engine does not call back into Course Context mid-session. IDs are kept for traceability only.
- **Read-only.** If tutoring uncovers something the schema lacks, such as a new misconception, it goes into the Student-State, not into the Question Schema.
- **Interface:** `build_question_schema(course_id, question) → QuestionSchema | Error`. Transport (function call, service, file) is not decided.
- **What the engine uses each field for:**

| Question Schema field | Engine use | Compared with (Student-State slot) |
|---|---|---|
| `correct_approach.technique`, `alternative_approaches` | is the student's method a valid one | `observed_approach` |
| `prerequisite_concepts[].concept_id` | which prior concepts to probe | `prerequisite_status[]` |
| `common_misconceptions[].cue` | triggers for a diagnosis; `mitigation` seeds hints | `suspected_misconception` |
| `learning_objectives` | what a transfer or check-understanding question must cover | `evidence_of_understanding_level` (the design page's Gap Record targets level 5, but its Question Schema carries no level; V1 treats the target as engine policy) |
| `reference_solution` | judging answers, verifying results | not compared |
| `provenance` | engine policy on AI-inferred content (open question 6) | not compared |
| `source_reference`, `prompt` | passed on for display | not compared |

- **What the engine does not get:** the rest of the knowledge base, other questions' solutions, other modules.

---

## 4. Shared tutoring concepts *(Proposed, cross-team)*

The records below follow the team's design page (`digital-professor-design.html`). Their fields, the decision logic and the status vocabulary are cross-team design topics. The Course Context module owns only the Question Schema (section 3) and the Course Context data it is built from.

### 4.1 Records and how they relate

| Record | Role | Written by | Changes | Key fields |
|---|---|---|---|---|
| **Question Schema** | the target | Course Context builder | never during a session | section 3.2 |
| **Student-State** | the running estimate of the student | student-evidence layer | every turn | `observed_approach`, `stated_reasoning`, `prerequisite_status[{concept, status, evidence}]`, `components_correct`, `suspected_misconception`, `interventions_attempted`, `evidence_of_understanding_level` (0 to 5), `gap_notes` |
| **Gap Record** (also called Gap/Diagnosis) | the running difference between target and estimate | derived each turn | recomputed every turn | `question_id`, `open_gaps[{target_slot, requirement, status, evidence}]`, `closed_gaps[]`, `off_target_context`, `resolved_when` |
| **Tutoring Action** | the decision for this turn | Tutoring Engine | one per turn | `action`, `target_gap`, `goal`, `constraints[]`, `rationale` |

Blank templates for these records (and the Question Schema) are in `templates/`: `student-state.template.json`, `gap-record.template.json`, `tutoring-action.template.json`.

```mermaid
flowchart LR
    QS["Question Schema<br/>target, read-only"] --> CMP{"compare<br/>target slots only"}
    SS["Student-State<br/>estimate, updated every turn"] --> CMP
    CMP --> GR["Gap Record<br/>open, partial, closed"]
    GR --> ENG["Tutoring Engine<br/>takes the top open gap"]
    ENG --> TA["Tutoring Action<br/>action, target_gap, goal, constraints"]
    TA --> UI["Interaction layer"]
    UI --> ST(["Student responds"])
    ST --> EV["Student evidence"]
    EV --> SS
```

Only slots that have a counterpart in the Question Schema are compared. The rest of the Student-State is session context that is carried but never scored.

| Question Schema slot | Student-State slot | Gap status (proposed mapping) |
|---|---|---|
| `correct_approach.technique` and `alternative_approaches` | `observed_approach` | match: closed; mismatch or unknown: open; tentative: partial |
| `prerequisite_concepts[i]` | `prerequisite_status[concept_id]` | `unknown` open; `partially demonstrated` partial; `confirmed (assisted)` partial; `confirmed` closed; `contradicted` open again |
| `common_misconceptions[i]` | `suspected_misconception` | watch-for until a cue is seen, then open until resolved |
| (proposed: target level 5, engine policy) | `evidence_of_understanding_level` | partial below 5, closed at 5 |
| none | `stated_reasoning`, `components_correct`, `interventions_attempted`, `gap_notes` | off-target context, never scored |

The session is resolved when `open_gaps` is empty.

### 4.2 How gaps change across turns

From the 13-turn trace on the design page (the student first applies u-substitution to ∫x cos x dx):

| Gap | Start | Turn-by-turn |
|---|---|---|
| technique (`observed_approach`) | open | T1 mismatch (u-substitution), still open; T6 partial (integration by parts proposed tentatively, beside a wrong alternative); **T7 closed** |
| P1 u-substitution mechanics | open | **T3 closed** (student solves the contrast integral alone) |
| P2 structural test for substitution | open | T4 partial; T5 confirmed with assistance (given by explanation); still partial at the end ("not yet independent") |
| P3 by-parts formula and the choice of u and dv | open | T8 partial (formula right, choice backwards); T10 confirmed with assistance (needed the T9 hint); still partial at the end |
| M1 pattern-matching misconception | not yet raised | T2 raised (tentative, from the retrieval cue); **T7 closed** |
| evidence level (target 5) | open (level 0) | T7 level 1; T12 level 4; waiting on the T13 transfer questions |

What this shows:
- **Gaps close in steps.** `open → partial → closed`, and help changes the step: an assisted success is partial, an independent one is closed.
- **A gap can be raised mid-session by a cue.** M1 was in the Question Schema as a watch-for item and became a live gap at T2 when the student's first answer matched its cue.
- **Evidence can surface something the schema never held.** At T9 a narrower misconception appeared (applying parts without checking that the new integral is simpler). It has no Question Schema counterpart, so under the page's rules it stays in the Student-State as off-target context and is handled through the P3 gap.
- **Updates can go backwards.** The status vocabulary allows `contradicted`, which reopens a gap. The trace never needed it. A failed transfer question at T13 would reopen P2 or P3.
- **The session is not over at T13.** P2, P3 and the evidence level are still not closed, so `open_gaps` is not empty.
- **The page is inconsistent on one point.** The Gap Record entering Turn 9 lists P2 as closed ("T5, assisted"), while the final table marks P2 "Partial, not yet independent". The mapping above resolves it as partial (open question 8).

### 4.3 Ownership

| Owned by Course Context | Shared, cross-team (not owned here) |
|---|---|
| Course Context schema and review rules; Question Schema content and build rules | Student-State fields; Gap Record; Tutoring Action; the 12-action vocabulary; status vocabulary and mapping; the decision logic; the target evidence level |

---

## 5. Downstream dependencies *(Normative for what Course Context provides)*

| Consumer | Needs | Reads these fields | Course Context guarantees | Open |
|---|---|---|---|---|
| **Sean** (retrieval) | course IDs, concept IDs, source references, retrieval scope | `Course.id`; `Concept.id`, `module_id`, `name`, `summary`, `key_definitions`; `Source.id`, `citation`, `section` | IDs are stable and unique within a file; links resolve; one file is one course, so **scope is a course**, narrowing to a module via `Module.concept_ids`, then to a concept plus its prerequisites via `prerequisite_ids`. The index loader derives `course_id` and `module_id` on each chunk by following links. | `Source.text_chunk` is reference-only for syllabus-only files and MUST NOT be embedded as content (open question 2). `Source.id` is unique per file, so multi-course stores key on `(course_id, source_id)`. Sean also supplies the concept and sibling-question match used in 3.3. |
| **Jonathan** (student evidence) | question information and the context attached to student evidence | `question_id`, `prompt`, `concept_ids`, `learning_objectives`, `prerequisite_concepts`, `correct_approach`, `alternative_approaches`, `common_misconceptions[].cue`, `reference_solution`; for bank questions `AssessmentQuestion.rubric` and `common_wrong_answers` via `question_id` | Concept IDs in `prerequisite_status[]` are Course Context IDs, not free text, so evidence attaches to a record the rest of the system can find. | runtime questions have no rubric or wrong-answer list; the cues are what exists |
| **Tutoring Engine** | target objectives, prerequisites, valid approaches | `learning_objectives`, `prerequisite_concepts`, `correct_approach`, `alternative_approaches`, `common_misconceptions`, `provenance` | a self-contained, read-only Question Schema per question (3.4) | what to do with AI-inferred content (open question 6); transport |
| **Yining** (presentation) | course and question context for display | `Course.title`, `Module.title`, `Concept.name`; `Source.citation`, `section`; `prompt`; `learning_objectives[].text`; `requires_figure` | a display-safe subset. `reference_solution`, `correct_approach` and `AssessmentQuestion.solution` MUST NOT be rendered to a student. | math notation (open question 9); how a `requires_figure` question shows without its figure |

---

## 6. Worked example: Calculus I *(Informative)*

The full worked Calculus I example — the Course Context file, the Question Schema for ∫ x cos(x) dx, where each field came from, the end-to-end tutoring trace, and the known deviations from this spec — now lives in its own document: [`course-context.example-calc1.md`](course-context.example-calc1.md). It is *informative*: it illustrates this spec on real data but defines nothing new.

---

## 7. Input/output and dependency diagram

![Course Context inputs, outputs and dependencies](diagrams/course-context-io.svg)

Source: [`diagrams/course-context-io.mmd`](diagrams/course-context-io.mmd) (Mermaid; edit the source, then re-render with `mmdc -i course-context-io.mmd -o course-context-io.svg`). A PNG is in the same folder.

Colours: green is the Course Context module (this spec); orange is another team's component; blue is an input or the student; red is the instructor. The Question Schema builder is specified here, but which team hosts it is open (question 11).

| Arrow | Contract |
|---|---|
| Syllabus → prompt → validate → flag → Course Context JSON | 1.5, 2.1, `course-context.validation-and-flagging.md` |
| Instructor review → Course Context JSON | 2.5: a human works the review worklist and edits |
| Course Context JSON → Sean | section 5, first row |
| Sean + Course Context JSON + student question → Question Schema builder | 3.3 steps 2 to 4 |
| Question Schema → Tutoring Engine, Jonathan, Yining | 3.4 and section 5 |
| Jonathan → Tutoring Engine | Student-State updates, section 4 |
| Tutoring Engine → Yining → student | Tutoring Action, section 4 |
| Tutoring Engine ⇢ Instructor review (dotted) | runtime-inferred items proposed for the knowledge base (open question 5); manual in V1 |

---

## 8. Unresolved design questions and recommended V1 choices

| # | Question | Owner | Recommended V1 choice |
|---|---|---|---|
| 1 | **Provenance is too coarse.** Record-level `provenance` makes every non-Source record `ai_inferred` in a syllabus-only file, so it barely discriminates. | Course Context | Keep record-level provenance. Treat the `assumptions[]` log (field-level detail) and the 2.5 human-check list as the trust signal. Revisit per-field provenance when lecture notes arrive. |
| 2 | **`Source.text_chunk` holds no source text** for syllabus-only courses (all 32 are a labelled syllabus line), so a consumer can mistake it for a textbook excerpt. | Course Context, Sean | Store the verbatim syllabus line without the label (P-3). Add a `textbook_ref` value for `Source.type` in 1.2 for reference-only records. Until then Sean treats a `Syllabus entry:` or `Syllabus reference:` prefix as reference-only and does not embed it. |
| 3 | **ID policy.** The trace uses `calc1.module-F…`; the file uses `calc1.06-…`. Regeneration could rename IDs and orphan Student-State history. `Source.id` is not namespaced by course. | Course Context, all consumers | Course Context IDs are canonical; update the trace. Regeneration MUST keep existing IDs (matched by syllabus section) and MUST NOT silently overwrite records a human has edited. Runtime questions use `adhoc-<hash8>`. Multi-course stores key sources on `(course_id, source_id)`. |
| 4 | **Concept granularity.** The tutoring flow tracks finer pieces (P1, P2, P3) than the concepts in Course Context. | Course Context, Tutoring Engine, Jonathan | Keep concept-level IDs in the Question Schema and the Student-State. Carry the finer piece as `relevance` text. Split concepts only if concept-level tracking proves too coarse. |
| 5 | **Content the tutor needs but Course Context lacks** (M1, a technique-selection objective). | Course Context, instructor | The builder adds runtime items marked `derived_from: runtime`. The instructor promotes useful ones into Course Context by hand. An automated queue is V1.1. |
| 6 | **Serving AI-inferred content to students.** In a syllabus-only file almost everything is `ai_inferred` and unchecked. | Tutoring Engine, instructor | A V1 pilot MAY serve `ai_inferred` content. The engine receives `provenance`. The "check first" fields (2.5) are double-checked before any use beyond the pilot. |
| 7 | **One approach or several.** The template has a single `correct_approach`; the brief says "valid approaches". | Course Context, Tutoring Engine | Keep `correct_approach` as the canonical one and add optional `alternative_approaches` (3.2). A student method matching either counts as valid. |
| 8 | **Naming and status mapping for shared records.** "Gap Record" or "Gap/Diagnosis"; whether an assisted success is closed or partial (the design page does both). | Tutoring Engine, Jonathan | Use "Gap Record". Map assisted success to partial (4.1). |
| 9 | **Math notation.** Course Context stores plain text (`x^2`, `∫`); students and the trace use LaTeX. Bank matching cannot be string equality. | Yining, Sean | V1 stores text as generated and the student's prompt exactly as typed. Yining renders both. Retrieval does the matching. No notation normalisation in V1. |
| 10 | **No concept match** for a student's question. | Sean, Tutoring Engine | The builder returns `NO_CONCEPT_MATCH`. The engine falls back to generic elicitation with no target, and the miss is logged for review. |
| 11 | **Who hosts the Question Schema builder.** The design page has the retrieval layer populate the Question Schema; this spec defines the record and the rules. | Course Context, Sean | Course Context owns the fields and build rules and provides the builder. Sean's retrieval supplies the lookups (bank match, concept match) and may host the call. |

---

## Appendix A. Files

| File | Purpose |
|---|---|
| `specs/course-context.md` | this specification |
| `specs/course-context.example-calc1.md` | worked Calculus I example (Course Context, Question Schema, end-to-end tutoring trace) — moved out of §6 |
| `specs/course-context.validation-and-flagging.md` | spec for the Validator and Review Flagger tools (pipeline steps 3–5) |
| `specs/templates/course-context.template.json` | blank Course Context template, schema 1.1 (all fields, placeholders) |
| `specs/templates/question-schema.template.json` | blank Question Schema template, version 1.0 (all fields, placeholders) |
| `specs/templates/student-state.template.json` | blank Student-State template (§4, proposed / cross-team) |
| `specs/templates/gap-record.template.json` | blank Gap Record / Diagnosis template (§4, proposed / cross-team) |
| `specs/templates/tutoring-action.template.json` | blank Tutoring Action template (§4, proposed / cross-team) |
| `specs/templates/README.md` | how to use the templates and the placeholder convention |
| `specs/examples/calc1.course-context.json` | Course Context for Calculus I, schema 1.1 |
| `specs/examples/calc1.question-schema.xcosx.json` | Question Schema for ∫ x cos(x) dx |
| `specs/diagrams/course-context-io.mmd`, `.svg`, `.png` | input/output and dependency diagram |
| `design-example/syllabus-to-json-prompt.md` and `syllabus_breakdown_template.json` | the prompt and the original schema-1.0 field list; the current full templates are in `specs/templates/` |
