# Project Changelog

This changelog records major project-level changes. It begins with the first V1
implementation work; earlier research artifacts remain available in the Git
history and under `research/`.

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
