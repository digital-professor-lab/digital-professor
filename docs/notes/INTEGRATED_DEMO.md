# Integrated Demo Implementation Notes

This development demo follows the boundaries in `specs/`. It does not replace
the canonical specifications.

## End-to-end workflow

1. A course administrator uploads a syllabus and lecture notes or a textbook.
2. Course Context/Ingestion classifies each file, extracts normalized page
   lines, assigns a content version, and creates bounded passages that retain
   document, page, and line identity.
3. The application publishes the in-memory course only when it has a syllabus
   and at least one searchable knowledge source. Chat remains disabled until
   retrieval indexing completes and the API reports `ready_for_query=true`.
   Before publication, it compares explicit course numbers and course-title
   headers in each knowledge source with the syllabus. Strong conflicts reject
   the batch; missing signals produce `partially_verified` rather than a guessed
   match.
4. A student selects the course and enters a question.
5. Course Context builds a partial runtime `QuestionSchema`, with explicit
   provenance and `requires_human_review=true` for fields that lack an
   instructor-authored solution.
6. Interaction preserves each typed submission and creates validated factual
   `StudentEvidence`.
7. Retrieval searches only the selected course and returns source locations and
   a `highlight_url`.
8. The Tutoring Engine uses current evidence, prior conversation, and retrieved
   passages to select one action. It calls the configured provider when a valid
   key is available and uses a deterministic grounded response otherwise.
9. Mock Delivery reports presentation before the Engine accepts the result.
10. The next POST reuses the session and links the new submission to the prior
    submission, evidence, and action.
11. The browser stores only the session identifier. After refresh it requests a
    session snapshot and rebuilds the transcript and source links. Server
    restart recovery is not implemented yet.
12. A handwriting upload runs through OCR and a review screen. The recognized
    text cannot become evidence until the student confirms it and resolves every
    meaning-changing ambiguity.

## API

| Method and path | Responsibility |
|---|---|
| `GET /api/status` | Report process and feature status without exposing secrets. |
| `POST /api/provider/test` | Test the configured OpenAI-compatible provider. |
| `PUT /api/provider/settings` | Change non-secret runtime model, endpoint, pricing, and OCR settings. API-key fields are rejected. |
| `POST /api/course-setup/syllabus` | Stage one syllabus independently. |
| `POST /api/course-setup/notes` | Stage one or more notes/textbook files independently. |
| `POST /api/course-setup/publish` | Parse, chunk, index, and publish the staged course. |
| `POST /api/courses` | Compatibility endpoint used by automated tests for combined ingestion. |
| `GET /api/courses` | List in-memory published courses. |
| `GET /api/courses/{course_id}` | Show course metadata, topics, and source versions. |
| `PATCH /api/courses/{course_id}` | Correct an extracted course name. |
| `GET /api/courses/{course_id}/sources/{document_id}` | Display and highlight normalized source lines. |
| `POST /api/sessions` | Freeze a course and partial runtime Question Schema. |
| `POST /api/sessions/{session_id}/turns` | Run one linked tutoring turn. |
| `GET /api/sessions/{session_id}` | Restore the student-facing transcript and source links after refresh. |
| `GET /api/sessions/{session_id}/activity` | Read bounded input/output/decision/source summaries derived from timestamped backend records. |
| `POST /api/sessions/{session_id}/handwriting/recognitions` | Preserve and transcribe an image or PDF without routing unconfirmed work. |
| `POST /api/sessions/{session_id}/handwriting/confirmations` | Create confirmed evidence and continue the tutoring turn. |

## Logging contract

Operational events always retain event time, handoff name, and issue status.
They are backend-only and written as JSON under
`logs/YYYY-MM-DD/<session-id>/<time>_<event>_<id>.json`. Generated Question
Schema records use the same timestamped backend store. There is intentionally
no raw-log browser endpoint; only the bounded Activity projection is exposed.

Each completed turn also writes a `turn_activity` record containing the exact
original input, any recognition output, the student-confirmed input, delivered
output, a bounded decision summary, and source locations. For handwriting, the
original upload remains addressed by its artifact reference while OCR and
confirmed notation remain separate. Original handwriting bytes are also copied
to the session's ignored backend `artifacts/` directory with a SHA-256 checksum;
they are never returned through the Activity API. The Activity view reads these files and
truncates long display fields; it does not return the full trace or model
chain-of-thought.

## Course-material consistency

The syllabus is the authority for the expected course name and number. In the
first 25 extracted lines across up to five pages of each notes/textbook source,
ingestion checks:

1. An explicit course number, normalized without punctuation or case.
2. If no number is available, an explicit short title line containing a course,
   class, or lecture-notes marker.

A different explicit number or a disjoint explicit title is a hard conflict and
returns HTTP 422 before the course is published. A matching signal marks that
source verified. A source with no reliable identity signal remains usable but
is listed as review recommended, making the complete workspace partially
verified. The check does not infer course membership from topic similarity;
that would risk silently accepting a related but incorrect course.
The diagnostic switch controls optional payload summaries, retrieval sources
and links, model identity, latency, and token use. Turning diagnostics off does
not remove state required for session continuity. API keys never enter logs.

When token counts and per-million-token rates are available, logs include an
estimated request cost and running session estimate. These are estimates rather
than billing records. Timings distinguish retrieval, provider latency, OCR, and
the complete turn.

Turn-time failures create issue events when the session exists. Ingestion,
course/session lookup, and provider failures return structured HTTP errors.

## Specification mapping

| Boundary | Demo implementation | Remaining work |
|---|---|---|
| Course Context/Ingestion | Classification, page/line normalization, chunks, metadata, partial runtime schema | Full `CourseContext`, validation, instructor review, persistent atomic publication |
| Retrieval | Course-scoped lexical search, passage identity, source links | Retrieval tool loop, embeddings, reranking, evidence/citation checks |
| Student Interaction | Immutable typed input, handwriting OCR/confirmation, evidence validation, prior links, coordination | Stylus canvas and recorded voice |
| Tutoring Engine | Persistent process session, history, grounded action, delivery acknowledgement | Phase/gap/help policy, math and reply checks, safety and fallback cards |
| Delivery | Mock text presentation and terminal `DeliveryResult` | Product Delivery service, retries, accessibility, avatar |
| Session/Trace | Operational events and optional diagnostics | Durable store, retention, access controls, idempotency, restart recovery |

## Provider configuration

Copy `.env.example` to `.env`, select a model, and put the secret in the named
environment variable. The browser can test the configuration but cannot read or
write the secret. Restart the backend after changing `.env`.

Model selection uses `DIGITAL_PROFESSOR_MODEL`. Cost estimates use
`DIGITAL_PROFESSOR_INPUT_COST_PER_MILLION` and
`DIGITAL_PROFESSOR_OUTPUT_COST_PER_MILLION`. Handwriting uses
`OPENAI_HANDWRITING_MODEL` and its two handwriting pricing variables. Pricing
must be updated manually when the provider changes it.

The Provider Settings screen can override every non-secret setting for the
running backend. Only the actual key remains in `.env`. The checked-in
`.env.example` documents the allowed variables; `.env` itself stays ignored.

## Initial Tutoring Engine policy

The demo Engine now owns a small versioned policy rather than choosing every
response as the same generic action:

- A new attempt receives a `probe` action in the `ELICIT` phase.
- The first explicit help request selects `hint`, enters `SUPPORT`, and raises
  help level to 1.
- Further help requests select `explain` and raise help level up to 3.
- Student reasoning containing an explanation cue selects
  `check_understanding` in `CHECK`.
- Other follow-ups select `retry` in `PRACTICE`.

For each action the Engine creates a pending `LearnerState`. It applies phase,
help level, and the new current state only after Delivery returns `presented` or
`partially_presented`. The state explicitly reports low confidence because this
demo does not yet verify mathematical correctness. The full card policy, gap
closure, math checks, transfer, safety, expiry, and fallback behavior remain in
the next implementation stage.

## Safe extension points

- Replace `DocumentIngestionService` while preserving normalized source
  locations consumed by Retrieval.
- Replace `CourseRetrievalIndex` with the production Retrieval service while
  preserving passage IDs, versions, locations, and grounding status.
- Replace `GroundedDemoEngine` with the full Tutoring Engine while retaining
  `TutoringEnginePort`.
- Replace `MockDelivery` with the Delivery module while retaining terminal
  `DeliveryResult` behavior.
- Replace `DemoApplication` dictionaries with durable repositories without
  moving tutoring decisions into the API layer.
