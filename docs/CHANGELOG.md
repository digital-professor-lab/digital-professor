# Project Changelog

This changelog records major project-level changes. It begins with the first V1
implementation work; earlier research artifacts remain available in the Git
history and under `research/`.

## 2026-11-20 — Jev passage judge, upload checks, OpenRouter default

### Added

- Jev passage judge. Before the tutor cites a textbook passage, Jev
  (`typesafe/jev-1.13` through OpenRouter) scores up to six candidates for
  "does this passage state <method>?". Passages that state it (score ≥ 0.70)
  come first; passages under 0.35 are not offered. Only textbook text and the
  method name are sent, never student messages. Answers are cached in
  `.cache/jev/`. Any Jev failure falls back to the existing rules.
  `DP_JEV=off` disables it. Labelled set in the retrieval tool: 25/28 correct,
  no wrongly accepted passage (rules alone: 18/28, 8 wrongly accepted).
- Upload checks at the staged course-setup endpoints: a textbook uploaded as the
  syllabus, the syllabus uploaded again as notes, or a notes step with no
  lecture notes or textbook is rejected at once with HTTP 422 and a plain
  message, instead of after a full course build.
- `docs/notes/CONFIGURATION.md`: every setting, with defaults and examples.

### Changed

- Syllabus-scoped textbook ingestion is now **off by default**; the whole
  textbook is ingested, as in Retrieval V1. Set `DP_TEXTBOOK_SCOPE=on` to use it.
- `.env.example` starts with OpenRouter and DeepSeek V4.1 Flash
  (`deepseek/deepseek-v4.1-flash-1017`, the model DeepSeek serves as
  `deepseek-chat` / `deepseek-flash`), so the demo keeps the model it was
  developed with when it reaches DeepSeek through OpenRouter.
- The student page no longer shows the Question Schema card, which contains the
  correct approach. The same record remains in the developer Run log
  (`/pipeline`) and in the backend log files. `test_v1_webapp` passes again.

### Not changed

- The Tutoring Engine's decision, reply and check logic is unchanged from the
  2026-11-19 polish.

## 2026-11-19 — Syllabus-scoped textbook ingestion, Claude provider

### Added

- A textbook is ingested only for the sections the syllabus lists, matched by
  title against the PDF's table of contents (section numbers differ between
  editions). Pages outside the scope are not read; page numbers are unchanged.
  Reference course: 320 of 841 pages, 1,136 blocks instead of 3,023. Falls back
  to the whole document, with the reason recorded, when the scope cannot be
  trusted. `DP_TEXTBOOK_SCOPE=off` disables it.
- Provider profile `anthropic` (Claude through Anthropic's OpenAI-compatible
  endpoint, key `ANTHROPIC_API_KEY`). No temperature is sent to Claude models.
- `<PROVIDER>_BASE_URL` sets one provider's endpoint, for example a
  company-hosted DeepSeek deployment.

## 2026-11-19 — Course-match record, tutoring polish

### Fixed

- Course-material consistency: the fast pre-publish check (first pages only) now
  returns its result, and the published course records it
  (`verified` / `partially_verified` / `override_confirmed`, with notes). Before,
  every course was recorded as `verified`. The one-shot `POST /api/courses`
  rejects a mismatch with HTTP 422 again; confirming an override goes through the
  staged `/api/course-setup` flow.
- `sympy` is listed in the environment smoke-test mapping.

### Changed

- A student who sounded frustrated earlier in the question and then gives a
  bare correct answer is not asked how they got it; the tutor confirms warmly and
  may offer to go over it.
- Attached textbook passages: common PDF extraction artifacts are repaired for
  display ("T o find" → "To find", "( f ◦ g)" → "(f ◦ g)", "f ′" → "f′"), and a
  title repeated at the start of the quote is dropped.
- The tutoring policy docstring describes policy 3.0 (levels are recorded, not
  a cap).
- Tests write run logs to a temporary folder (`DIGITAL_PROFESSOR_LOG_DIR`), not
  the developer's `logs/`.

### Known open item

- The Activity log shows the Question Schema card (including the correct
  approach) to anyone using the page, so `test_v1_webapp` still fails on
  "Question Schema". Who should see that card is a team decision.

## 2026-11-17 — Tutoring Engine: fixes from a scenario evaluation

Six rounds of scripted student conversations (about 130 turns, 35 scenarios: easy,
medium, hard, adversarial, then re-runs) with the hosted chat model and the real
course textbook.

### Changed

- Math check: definite integrals and limits are checked by computation; `sec^2(x)`
  style notation and trailing `!` parse.
- A message with several equations or steps joined by words is read as working,
  not as a final answer.
- A reply that quotes the correct part of a wrong answer ("the 2cos(2x) part is
  right" after "-2cos(2x)") is treated as giving the answer away.
- The writer points only to the error the marking found; it is told not to
  invent others.
- Replies in the student's language; Chinese help requests are recognised.
- A student who solved it with their own work is not asked a further question.
- A right answer with a mathematically wrong reason leaves the method item partial.
- A move label left inside the reply is removed; the opening line is varied.
- Help given is inferred from the reply as well as from the move label.
- A passage is continued only into the next page; no passage is attached to a
  wrap-up.

## 2026-11-17 — Tutoring Engine: teaching left to the model (policy 3.0)

A real session with vector retrieval showed two things: the attached textbook
passage was the proof of the rule instead of its statement, and replies were
still stiff because code capped the help level by level.

### Changed

- The four help levels are no longer a limit. The writer model decides how much
  help to give and in what form. Code keeps one hard rule (the student does the
  solving), the opening turn (no hint), and a hold on the method name while the
  student is still finding their own way.
- The writer prompt is a short persona, the one rule and the facts of the turn,
  instead of per-situation instructions.
- A correct answer solves the question at once; the solved-check phase is gone.
- A help request that carries an idea ("maybe by parts?") is read and marked by
  the model, and the tutor may use the student's own word for a method.
- Passages: the search uses the method name only; proofs are not offered as
  reading; a passage whose opening names the method comes first; a second search
  asks for the statement when none was found; printed names are cut to a title.
- The guard model rejects only the final answer or a step of the problem.
- The method name and the textbook passage are held back until the second time
  the student is stuck; the first time, the tutor points.
- The guard model also checks the tutor's own math (it recomputes each statement
  the tutor makes), including after the problem is solved.

## 2026-11-16 — Tutoring Engine simplified (policy 2.0)

Review of a real session showed that the first implementation hinted at the
method in its first reply, read correct progress as being stuck, did not use the
retrieved passages in its replies, and sounded formulaic. Code was deciding not
only how much to disclose but also exactly how to teach.

### Changed

- Code now decides only the situation and the help level (0 ask, 1 point,
  2 teach, 3 show). The writer model chooses the teaching move inside the level
  and writes freely. The action cards and ladders are removed.
- The first message, when it is the problem itself, is an opening turn: nothing
  is marked and the tutor does not hint.
- New verdict `ON_TRACK` (right so far, not finished), which counts as progress.
- The marking step's findings (what is right, where the first problem is) are
  passed to the writer. The reference answer still is not.
- The math check also covers derivatives, and reads the check from the wording
  of the question when the Question Schema carries none.
- From help level 2 the reply sends the student to a textbook passage by page,
  and that passage is attached under the reply. Lists of terms or exercises and
  passages that work the student's own problem are not shown.
- Reply checks: a deterministic check for method and structure words before the
  level allows them; the guard model runs only when a reply teaches a rule or
  contains new math.
- The explanation check after a correct answer is asked once.
- Typical turn: 1 to 3 model calls (was 2 to 5).
- `/pipeline` shows the help level, the move the model chose and the passage
  attached.

### Boundaries

- The behaviour now differs from `specs/tutoring-engine.md`; the differences are
  listed in `docs/notes/INTEGRATED_DEMO.md` ("Tutoring Engine"). The spec has not
  been updated yet.
- Transfer problems and learner memory across questions are not implemented.

## 2026-11-15 — Tutoring Engine brought in line with the spec

### Added

- `digital_professor.tutoring`: `policy.py` (turn types, diagnosis codes, action
  cards, ladders, fixed texts, settings), `state.py` (question state and gaps),
  `math_check.py`, `judge.py` (reading and marking with a checked JSON record,
  reconciliation table), `decide.py` (the spec's `decide()`), `reply.py` (writer
  prompt, reply checks, guard, fallback) and `grounded_engine.py` (one turn).
- Diagnosis codes D0-D10 and the twelve shared action types now mean what
  `specs/tutoring-engine.md` says, in the prompt, in `decide()` and in the logs.
- Learner state: gaps drive the choice of move, can reopen with a recorded reason,
  are capped at `partial` after help, and are committed with the phase only after
  the reply is presented.
- Reply checks before sending: no final answer (verified by the math check), at
  most one question, length limit, then a guard model; one rewrite, then a
  fallback template.
- The Engine searches the course material only for moves that state course content.
- `tests/tutoring/` (92 tests).

### Changed

- `GroundedDemoEngine` moved from `runtime.py` to `tutoring/grounded_engine.py`.
- The math check no longer evaluates student text: every name is checked against
  a short list before parsing.
- Tests never read the developer's `.env` (`DIGITAL_PROFESSOR_SKIP_DOTENV`).
- Six tests in `tests/interaction/test_integrated_demo.py` were updated to the
  spec's behaviour (first help request gets a fixed question; three model roles).
- `/pipeline` shows the new steps: reading, marking, checklist, decision,
  retrieval or its reason for not running, writing, reply checks.

### Boundaries

- Not implemented from the spec: `start_question`, `solution_outline` and first
  error step, `choose_action`, redelivery and duplicate handling, timeouts, the
  citation check, `DEMO_SIMILAR` and `TRANSFER` content (the Question Schema
  builder does not produce it yet).
- The math check covers indefinite integrals only.
- Three stated deviations from the spec are listed in
  `docs/notes/INTEGRATED_DEMO.md` ("Tutoring Engine").

## 2026-11-12 — Retrieval V1 connected to uploaded course material

### Added

- Added `digital_professor.retrieval.course_retrieval`: at publication the
  ingested blocks are indexed for Retrieval V1 (embedding inputs, BGE and Qwen
  vectors, per-file vector cache); at a turn one `RetrievalRequest` returns a
  `GroundingBundle` or `RetrievalStop`.
- Added `IngestedCourseBackend` to `retrieval_tool`: Week 3's search and
  selection code over ingested blocks instead of the Week 3 files.
- Retrieval V1 passages from ingested files now carry page, line range and
  highlight link instead of the development-only legacy locator.
- `retrieval_result` trace events and `GET /api/status` report the retrieval
  status, warning codes and the index in use.
- Added `tests/retrieval/` (18 tests) covering ingestion to grounded turn.

### Changed

- Week 3's package can be loaded next to the product package of the same name
  (`digital_professor`); it is imported under an alias and its files are not
  modified.
- `DemoApplication.publish_course` builds the index through
  `build_course_retrieval`; the keyword index remains the fallback and the
  default in tests.

### Boundaries

- The grounding policy per tutoring action, model-written tool calls, the Jev
  judge and the citation check are not connected yet; they depend on the
  Tutoring Engine work.
- The keyword channel is SQLite FTS5 and vectors are in memory. Results are not
  comparable with the Week 3 pgvector benchmark.

## 2026-11-10 — Mobile capture, provider profiles, and progress

### Added

- Added responsive mobile layout behavior using the dynamic viewport, safe-area
  spacing, touch-sized controls, horizontal navigation, and iOS-safe form sizes.
- Added separate **Take a photo** and **Choose image or PDF** handwriting paths;
  both preserve the original artifact and enter the existing confirmation flow.
- Added visible, text-labeled progress bars for source uploads, course
  preparation, tutoring turns, provider testing, and handwriting recognition.
- Added explicit OpenAI, OpenRouter, DeepSeek, Ollama, and custom
  OpenAI-compatible provider profiles with provider-specific base URLs and
  server-side key-variable names.
- Added dynamic model/version discovery through the configured provider's model
  list and retained manual exact-identifier entry.
- Added integration coverage for the provider catalog, every provider profile,
  model/version loading, mobile capture markup, and progress controls.

### Boundaries

- Progress before completion is a client-side stage estimate because current
  requests are synchronous; it is not a streamed backend percentage.
- Handwriting requires more than text-generation compatibility: the selected
  provider and model must support image input and structured Responses output.
- The local mobile workflow is intended for a trusted LAN and is not a public
  deployment or a substitute for authentication and HTTPS.

## 2026-11-06 — Stateful integrated demo

### Added

- Added multi-file syllabus and lecture-note ingestion with document versions,
  normalized pages, stable line ranges, and bounded passages.
- Added course-scoped retrieval over uploaded material and source-view links
  that highlight the page lines used for a response.
- Added a partial runtime Question Schema for student-originated questions.
- Added stateful sessions that link follow-up submissions to prior evidence and
  tutoring actions.
- Added OpenAI-compatible `.env` configuration and provider authentication test.
- Added required handoff events plus optional source, issue, latency, model, and
  token diagnostics.
- Added course setup, tutoring chat, provider settings, source display, and a
  bounded Activity projection to the browser application.
- Added browser-refresh session recovery using a stored session identifier and
  a server-side transcript snapshot.
- Added configurable token pricing, per-request/session cost estimates, and
  retrieval/model/turn timing in diagnostic logs.
- Connected handwriting image/PDF OCR to the session, with mandatory student
  review before confirmed evidence reaches the Tutoring Engine.
- Added a startup gate that completes ingestion and retrieval indexing before
  the chat accepts a question.
- Added runtime UI settings for provider, model, endpoint, pricing, and OCR
  model while keeping the API key exclusively in ignored `.env` state.
- Added policy-driven tutoring phases, help escalation, pending Learner State,
  and state commit only after successful Delivery acknowledgement.
- Separated syllabus upload from multi-file notes upload and added an explicit
  course preparation request.
- Added editable extracted course names, safe inline TeX/code rendering, source
  links, typing feedback, and animated chat messages.
- Moved Question Schema records and handoff diagnostics out of the student UI
  into timestamped backend files under `logs/<date>/<session>/`.
- Expanded tutoring chat to the available viewport and moved handwriting upload
  into an attachment button in the composer.
- Added a sidebar Activity log derived from backend records, with bounded input,
  output, decision, and source summaries.
- Added exact original-input, recognition-output, and confirmed-input fields to
  turn records so mathematical notation is not silently normalized.
- Added a course-material consistency gate: explicit course-number/title
  conflicts pause publication for human confirmation, confirmed exceptions are
  recorded as `override_confirmed`, and missing identity signals produce a
  visible partially-verified review state.
- Restored the chat composer hint for `$equation$` math and backtick code.
- Added handwriting drag-and-drop to the conversation and composer, using the
  same artifact-preserving OCR path as camera and file selection.
- Added editable recognized LaTeX with a live KaTeX preview, `$$...$$`
  display-math rendering, and model instructions to format math as LaTeX.
- Made main content independently scrollable while keeping the desktop sidebar
  fixed, including when the handwriting review editor expands.

### Specification conformance audit

Audited against `specs/architecture.md`, `interfaces.md`,
`student-interaction.md`, `course-context.md`, `rag-retrieval.md`, and
`tutoring-engine.md` on 2026-11-06. This is an integration slice following the
module boundaries; it is not a claim that every normative V1 behavior is done.

| Area | Current conformance | Remaining specification work |
|---|---|---|
| Architecture and ownership | Interaction captures and validates evidence; Course Context parses sources; Retrieval returns course passages; the Engine interprets evidence and selects actions; Delivery only presents the selected action. | Add authenticated instructor provisioning, durable stores, version activation, authorization, and structured failures at every boundary. |
| Shared records | Required common-envelope and identity fields are exercised for `StudentSubmission`, `StudentEvidence`, `LearnerState`, `TutoringAction`, and `DeliveryResult`. IDs and evidence links pass through unchanged. | Implement and validate the complete `CourseContext`, `QuestionSchema`, `RetrievalRequest`, `GroundingBundle`, `QuestionStart`, Engine handoff/ack, and compatibility/version lifecycle. |
| Student Interaction | Typed input is preserved exactly. Handwriting preserves the original artifact, recognition, correction, confirmation, provenance, page information, and blocks ambiguous work before Engine handoff. Follow-up attempts link to prior evidence/actions. | Validate TeX syntax without repairing it; add the direct stylus canvas and bounded recorded-voice path; return canonical structured timeout/downstream-failure records instead of only HTTP failures. |
| Course Context/Ingestion | Provisioning completes before questions; documents retain versions and normalized page/line mappings; explicit cross-course conflicts block publication and uncertain identity is review-marked. | Replace heuristic extraction with the complete instructor review/validation and atomic published-version workflow. The current UI has no administrator identity or access control. |
| Retrieval and grounding | Search is course-scoped, source locations are stable, `no_support_found` remains distinct, and highlighted source links use the retrieved page/line range. | Replace lexical always-search behavior with the specified policy-driven Retrieval tool loop, request/bundle schemas, scope and evidence checks, reranking, citation validation, stops, and failure taxonomy. |
| Tutoring Engine | Only confirmed evidence reaches the Engine. It owns a small versioned phase/help policy, creates pending Learner State, chooses a `TutoringAction`, and commits state after successful Delivery. | Implement the normative deterministic decision table, complete phases/gaps/ladders/cards, question tiers, information walls, math/assessment checks, reply checks, safety behavior, retries, expiry, idempotency, and property vectors. |
| Delivery | The coordinator forwards an unchanged action to mock text Delivery and records a terminal `DeliveryResult`. | Implement the Delivery module contract, accessibility/channel adaptations, retry classes/budgets, redelivery semantics, and avatar integration. |
| Logging and preservation | Operational continuity records persist when diagnostics are off; optional model/source/cost details obey the session toggle. Exact typed input and separate OCR/confirmed values are stored in timestamped backend records. Secrets are excluded. | Add retention/deletion policy, encryption, access control, redaction, durable session recovery, and institutional privacy review before real student data. |
| Browser demo | Course-gated setup, multi-turn POSTs, refresh restoration, math/code rendering, handwriting confirmation, source navigation, and bounded Activity summaries are connected. | Add authentication, multi-user isolation, backend restart recovery, accessibility validation, and production deployment controls. |

Automated contract and behavior checks currently report **87 passed** with six
third-party deprecation warnings. The tests establish the implemented slice;
they do not waive the remaining normative items above.

### Current limitations

- Course extraction and runtime Question Schemas use a transparent heuristic
  demo path and still require full validation and instructor review.
- Search is lexical and in-memory; the production Retrieval tool loop,
  embeddings, reranking, and citation validation remain future work.
- Tutoring uses a bounded grounded prompt rather than the full Engine state
  machine, policy cards, math checks, and safety flow.
- Delivery remains mock chat, and all state resets when the server restarts.
- Recorded voice, a direct stylus canvas, and production avatar delivery are not
  implemented in the root product.
- API failures are structured HTTP responses but are not yet all represented by
  the shared cross-module failure records required by the specifications.

## 2026-11-05 — Initial integrated V1 product slice

### Added

- Created the root `src/digital_professor/` product package with separate
  Interaction, Course Context, Retrieval, and Tutoring boundaries.
- Connected typed or confirmed handwritten `StudentEvidence` to a frozen
  Calculus `QuestionSchema`.
- Connected the initial deterministic Tutoring Engine to Retrieval V1's local
  fixture backend.
- Added minimal `LearnerState`, grounded `TutoringAction`, mock Delivery,
  `DeliveryResult` recording, and end-to-end trace events.
- Added root integration tests and executable checks for the shared records in
  `specs/interfaces.md`.

### Current limitations

- Tutoring decisions are limited to deterministic probe/explain behavior.
- Retrieval uses the development fixture rather than a published course index.
- Delivery is mocked, and the research browser prototype is not yet the root
  product client.

## 2026-11-05 — Shared components merged

- Merged the revised Retrieval specification and Retrieval V1 prototype.
- Merged the Course Context Stage A pipeline and its offline tests.
- Added the final V1 Tutoring Engine specification.
- Reconciled component ownership: Interaction captures evidence and coordinates
  handoffs; Retrieval supplies course evidence; the Tutoring Engine interprets
  learner state and chooses actions; Delivery presents approved actions.

## 2026-10-27 — Handwriting interaction V1

- Added handwriting upload and stylus-canvas input to the Interaction research
  prototype.
- Preserved original artifacts separately from recognition output.
- Added ambiguity detection, student confirmation, correction records, and
  routing only after validated evidence is available.
- Added Jira-linked PR conventions, peer review, and a reusable PR template.

## 2026-10-23 to 2026-10-24 — Simple V1 interaction implementation

- Added repository setup instructions, a Python virtual-environment workflow,
  and an environment smoke test.
- Added the shared architecture and interface specifications.
- Implemented the first typed Student Submission and Student Evidence pipeline.
- Added mock Tutoring Engine and Delivery ports to demonstrate one complete
  tutoring handoff without assigning their responsibilities to Interaction.
- Added AI-assisted coding guidelines, `.gitignore`, and draft code-ownership
  practices.
