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
   headers in each knowledge source with the syllabus. Strong conflicts pause
   publication for explicit confirmation; confirmed exceptions become
   `override_confirmed`. Missing signals produce `partially_verified` rather
   than a guessed match.
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
| `GET /api/provider/catalog` | List supported provider profiles, endpoints, and server-side key-variable names. |
| `PUT /api/provider/settings` | Change non-secret runtime model, endpoint, pricing, and OCR settings. API-key fields are rejected. |
| `POST /api/course-setup/syllabus` | Stage one syllabus independently. A file that looks like a textbook is rejected with 422 at once. |
| `POST /api/course-setup/notes` | Stage one or more notes/textbook files independently. The syllabus file again, or a file that looks like a syllabus, is rejected with 422 at once. |
| `POST /api/course-setup/publish` | Parse, chunk, index, and publish the staged course; a suspected mismatch returns 409 until repeated with `?confirm_course_mismatch=true`. |
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
The student page does not display the Question Schema card, because it contains
the correct approach; developers see the same record in the Run log
(`/pipeline`). The Activity API still returns the record, so hiding it from a
student by role needs authentication, which is not implemented yet.

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

A different explicit number or a disjoint explicit title pauses staged
publication with HTTP 409 and returns the detected conflicts. The interface
requires an explicit confirmation before continuing. A confirmed publication
is marked `override_confirmed`, and the conflicting signals are retained in its
audit notes. The compatibility bulk-upload endpoint remains strict and returns
HTTP 422. A matching signal marks that source verified. A source with no
reliable identity signal remains usable but is listed as review recommended,
making the complete workspace partially verified. The check does not infer
course membership from topic similarity; that would risk silently accepting a
related but incorrect course.
The diagnostic switch controls optional payload summaries, retrieval sources
and links, model identity, latency, and token use. Turning diagnostics off does
not remove state required for session continuity. API keys never enter logs.

When token counts and per-million-token rates are available, logs include an
estimated request cost and running session estimate. These are estimates rather
than billing records. Timings distinguish retrieval, provider latency, OCR, and
the complete turn.

Turn-time failures create issue events when the session exists. Ingestion,
course/session lookup, and provider failures return structured HTTP errors.

## Upload checks

The staged course-setup endpoints classify each file from its first pages
(well under a second, the same rule as full ingestion) before anything is
built. A textbook uploaded as the syllabus, the syllabus uploaded again as
notes, a file that looks like a syllabus in the notes step, or a notes step
with no lecture notes or textbook is rejected with HTTP 422 and a message that
says where the file belongs. Before, these mistakes surfaced only after a full
course build. An unreadable file is left to full ingestion.

## Specification mapping

| Boundary | Demo implementation | Remaining work |
|---|---|---|
| Course Context/Ingestion | Classification, page/line normalization, chunks, metadata, partial runtime schema | Full `CourseContext`, validation, instructor review, persistent atomic publication |
| Retrieval | Retrieval V1 over ingested blocks: hybrid search with Week 3's code and thresholds, scope check, evidence check, `GroundingBundle` with page, line and source link; keyword index as fallback | Model-written tool calls and the per-action grounding policy (with the Tutoring Engine), Jev evidence judge, citation check, pgvector store, concept cards (the Engine already uses Jev to choose which textbook passage to cite; see Tutoring Engine) |
| Student Interaction | Immutable typed input, handwriting OCR/confirmation, evidence validation, prior links, coordination | Stylus canvas and recorded voice |
| Tutoring Engine | Opening turn, fixed-rule reading, math check for derivatives and indefinite integrals, one marking call with a checked record, gaps with evidence, `decide()` for the situation and counters, teaching chosen by the writer model, textbook passage attached to the reply, reply checks with a conditional guard and fallback sentences, state committed after delivery | Spec update for the simplified design, `start_question`, solution outline, redelivery and duplicate handling, timeouts, citation check, transfer problems, learner memory across questions |
| Delivery | Mock text presentation and terminal `DeliveryResult` | Product Delivery service, retries, accessibility, avatar |
| Session/Trace | Operational events and optional diagnostics | Durable store, retention, access controls, idempotency, restart recovery |

## Tutoring Engine

`digital_professor.tutoring.grounded_engine.GroundedDemoEngine` runs one turn.
This is `tutoring-policy@3.0`. It departs from `specs/tutoring-engine.md` on
purpose; the differences are listed below so the spec can be updated.

Division of work:

- **Code** keeps what has to be reliable: the math check, the learner state with
  its evidence, the checks on every reply, and the log. It works out the
  situation and keeps the counters. It does not choose how to teach.
- **The language model** does the teaching. It reads the student, decides how
  much help to give and in what form, and writes the reply. One rule is not its
  to decide: the student does the solving.

One turn:

1. **Opening.** When the first message is the problem itself, nothing is marked
   and the tutor only gets the student started. It gives no hint.
2. **Read.** Fixed phrase rules settle clear messages (a plain help request, a
   demand for the answer, a bare math answer, an acknowledgment). Anything else,
   including a help request that carries an idea ("I don't know, maybe by
   parts?"), is read by the marking call.
3. **Math check.** SymPy proves an answer correct or wrong for derivatives,
   indefinite integrals, definite integrals and limits. When the Question Schema
   carries no check, one is read from the wording of the question. For a
   one-number answer only the stated final value is compared. Tangent lines,
   optimisation and word problems have no computed check; the marking model
   decides. Student text is never evaluated as code.
4. **Marking.** One model call returns the message type and, for an attempt, a
   verdict (`ON_TRACK`, `D0`-`D7`, `CORRECT`, `UNCLEAR`), what the student has
   right, where the first problem is, and proposed gap updates. The record is
   validated; an invalid record is requested once more and then given up on.
5. **Gaps.** A proposed update is accepted only with a verbatim quote from the
   student, is capped at `partial` after help, and can reopen a gap on an error.
6. **`decide()`.** Pure code. It returns the situation (`open`, `help`,
   `attempt`, `unclear`, `concept`, `wrap_up`, `after_solved`, `redirect`, or a
   fixed `safety`, `park`, `switch`) and updates the counters: help requests,
   turns without progress, wrong answers without work, solved or not.
7. **Course passages.** Fetched from the second time the student is stuck (two
   help requests, two wrong attempts, or one of each), for a question about an
   idea, and once the problem is solved; the same search is not repeated within
   a question. Lists of terms
   or exercises, proofs, and passages that work the student's own problem are set
   aside. A passage that stops at a heading is continued with the text after it.
   When nothing found states the idea itself, a second search asks for the
   statement. Jev then scores the candidates (see "Jev passage judge" below).
8. **Reply.** The writer model gets a short persona, the one hard rule, and the
   facts: the situation, the marking findings, the help given so far, how often
   the student asked for help, and the passages. It never gets the reference
   answer. It returns what it did (`MOVE: ...`), the reply, and optionally the
   passage the student should read (`READ: n`), which is attached under the
   reply once.
9. **Reply checks.** Code: no final answer (verified by the math check), no hint
   in the opening reply, no method name before the student is stuck a second
   time (unless the student used the name), a hard length limit. A guard model
   reads the reply only when it contains math the student has not written. It
   rejects a reply that gives the final answer or a step of this problem, and a
   reply in which the tutor's own math is wrong: it lists each mathematical
   statement, recomputes it, and compares. This also runs after the problem is
   solved. One rewrite, then a fixed fallback sentence.
10. **Pending turn.** The new state replaces the old one only when Delivery
    reports that the reply was presented.

The most help given so far (questions only, pointed, named the method or taught
the rule, worked a similar example) is recorded from the move the writer chose.
It decides whether a correct answer counts as unaided, and it is told to the
writer as a fact. It is not a limit.

A correct answer solves the question at once. Whether to ask a last "why" is the
writer's judgment, except that an answer with no work is asked how it was found.
Six turns without progress, or twenty turns, end in a fixed pause message.

Model calls per turn, measured with a hosted chat model: 1 for the opening and
for a solved question, 2 for most turns, 3 when an attempt is answered with new
math. A rewrite adds up to 2. `DIGITAL_PROFESSOR_REPLY_GUARD=0` removes the guard.

Differences from `specs/tutoring-engine.md` (spec update pending):

- No action cards, ladders or help levels. Code does not choose the move or cap
  the help; the writer model does, inside one hard rule enforced by the checks.
- New verdict `ON_TRACK`; new opening turn; the marking findings are passed to
  the writer.
- The phases are `WORKING`, `SOLVED`, `PARKED`. There is no solved-check phase,
  no transfer problem and no `REMEDIATING` phase.
- The guard model is conditional, and the "at most one question" check is gone.
- The reader and the assessor share one call.

The first time a student is stuck the tutor points (at the kind of expression,
a feature, or the step that needs another look). The method name and the
textbook passage come the second time. The rule is `decide.may_name_method`.

The writer replies in the student's language when the student writes in another
script (Chinese, Japanese, Korean, Russian, Arabic). A message that is only math
keeps the language of the conversation.

The check on the tutor's own math is made by a language model. It caught the
errors it was tried on, but it is not a proof.

Not implemented: `start_question`, `solution_outline`, redelivery and duplicate
handling, timeouts and the turn deadline, the citation check, transfer problems,
learner memory across questions. The safety phrase list and the safety message
are development placeholders.

### Jev passage judge

Before the tutor cites a textbook passage, `tutoring/passage_judge.py` asks Jev
(`typesafe/jev-1.13` through OpenRouter) one yes/no question per candidate:
"does this passage state <method> itself?", answered as a probability. Up to
six candidates are scored. Passages scoring 0.70 or more come first, in the
rule order; partial ones follow by score; passages under 0.35 are not offered,
because citing no page beats citing the wrong one. When Jev finds no passage
that states the rule, the second search for the statement runs.

- Only textbook text and the method name are sent. Student messages never are.
- Answers are cached in `.cache/jev/jev_answers.jsonl`, so a passage is scored
  once. A scored call takes about 0.2 s.
- Any failure (no key, timeout, bad answer) returns no scores and the rules
  decide, as before. The turn never fails because of Jev.
- The scores are written to the turn's `retrieval` trace (`jev`). Dropped
  passages carry the reason `Jev: does not state ...`.
- Jev runs when `OPENROUTER_API_KEY` (or `TYPESAFE_API_KEY`) is set.
  `DP_JEV=off` disables it; tests run with it off.

Measured on the retrieval tool's labelled set (`scripts/eval_evidence_judge.py`,
28 pairs): 25/28 correct and no passage wrongly accepted, against 18/28 and 8
wrongly accepted for the rules alone. In a live Chain Rule session it ranked
the statement of the rule (0.98) above the motivation, proof and examples
(0.03 to 0.14).

## Syllabus scope for textbooks

**Off by default.** With `DP_TEXTBOOK_SCOPE=on`, a textbook is ingested only
where the syllabus uses it (`course_context/syllabus_scope.py`). Without it the
whole textbook is ingested, as in Retrieval V1. The syllabus topic list ("Chapter 1",
"4.5 The Chain Rule", ...) is matched against the PDF's own table of contents,
**by title first**: section numbers differ between editions (the JHU 110.106
syllabus follows the 4th edition, where the Chain Rule is 4.5; in the 3rd-edition
PDF it is 4.4, and 4.5 is trigonometric derivatives). A number is used only for an
entry with no title, or when the numbered section shares a word with the title. A
match on a subsection takes its whole section. Sections a line refers to
("with formal definition from 3.6") are included when their title fits.

Only the scoped pages are read and segmented; the others stay empty, so page
numbers and highlight links still match the original file. With the reference
course this ingests 320 of 841 pages: 1,136 blocks instead of 3,023, and about
60% less embedding work and vector memory.

The whole document is ingested, as before, when the file has fewer than 100
pages, has no table of contents with numbered sections, when fewer than 60% of
the syllabus entries are found, or when the scope would cover almost the whole
book. The reason, and every syllabus entry with the textbook section it matched,
is stored on the document (`IngestedDocument.scope`); the course list shows a
one-line note. A question outside the syllabus scope finds no textbook passage.
It is off by default because a whole-book course answers questions outside the
syllabus and the embedding cache makes rebuilding the same book cheap.

## Course retrieval

`digital_professor.retrieval.course_retrieval` connects knowledge preparation
to retrieval.

1. **At publication.** `build_course_retrieval(workspace)` takes the blocks that
   ingestion produced, drops chapter and section titles (they become the section
   path of the blocks under them), writes one embedding input per block in Week 3's
   `Course / Section / Content` form (split at 384 BGE tokens with 25 words of
   overlap), embeds the inputs with BGE and Qwen, and builds a Retrieval V1
   service for the course. Vectors are cached per file version under
   `.cache/retrieval_index/`, so publishing the same files again does not embed
   them again.
2. **At a turn.** The Engine calls `search(...)` as before and also passes the
   turn identifiers, the question, the student's message and, when the Question
   Schema was built for this question, its technique and concept names. The index
   builds one `RetrievalRequest`, the service returns a `GroundingBundle` or a
   `RetrievalStop`, and the passages are mapped back to ingested blocks so sources
   and highlight links work unchanged.
3. **In the trace.** The `retrieval_result` event carries the bundle's own
   status (`supported`, `partial`, `no_support_found`, `failed`, or the stop
   reason), its warning codes and the index in use. `GET /api/status` reports the
   index of each published course under `retrieval`.

Search and selection are Week 3's `_search_with_vectors`, unchanged, run by
`retrieval_tool.backends.IngestedCourseBackend`. It differs from the Week 3
pgvector run in three stated ways: vectors are held in memory, the keyword
channel is SQLite FTS5 instead of PostgreSQL full-text search, and Week 3's
course-name rules for its two pilot courses are switched off.

`DP_RETRIEVAL_MODE` selects the index: `auto` (default) uses Retrieval V1 when
the package, the Week 3 code and the embedding models are present and otherwise
the keyword index, with the reason in `/api/status`; `tool` requires Retrieval
V1; `keyword` forces the keyword index. `DP_RETRIEVAL_MODELS` narrows the
encoders (for example `bge_base_en_v1_5`). `WEEK3_KB` points at a Week 3
`knowledge_base` folder whose model cache should be used.

Current limits:

- The Engine fetches passages from the second time the student is stuck and
  offers them to the writer. The model does not write the tool call. The same search is not
  repeated within a question.
- A concept question is searched in the student's own words, with the method
  of the problem added for context when a lesson plan was built.
- The retrieval tool's own evidence check runs with rules only; its Jev judge,
  which would see student text, stays off because sending student text to an
  external model is an open team decision. The Engine's passage judge (above)
  sends textbook text only.
- Uploaded files are served as unreviewed original sources
  (`review_status = unverified`, `source_provenance = source_document`).
- Concept cards, which Week 3 embedded next to passages, are not built yet.

## Provider configuration

Every setting, with its default and an example, is listed in
[`CONFIGURATION.md`](CONFIGURATION.md).

`.env.example` starts with OpenRouter and `deepseek/deepseek-v4.1-flash-1017`.
That is the model DeepSeek's own API serves as `deepseek-chat` (reported as
`deepseek-flash`, DeepSeek V4.1 Flash). OpenRouter's `deepseek/deepseek-chat` is
an older model; in a test session it hinted at the method in its opening reply. With one
OpenRouter key the demo also reaches Jev and, optionally, handwriting OCR
(`openai/gpt-4o-mini`).

Copy `.env.example` to `.env`, select a model, and put the secret in the named
environment variable. The browser can test the configuration but cannot read or
write the secret. Restart the backend after changing `.env`.

Model selection uses `DIGITAL_PROFESSOR_MODEL`. Cost estimates use
`DIGITAL_PROFESSOR_INPUT_COST_PER_MILLION` and
`DIGITAL_PROFESSOR_OUTPUT_COST_PER_MILLION`. Handwriting uses
`DIGITAL_PROFESSOR_HANDWRITING_MODEL` and its two handwriting pricing variables.
Pricing must be updated manually when the provider changes it. Legacy
`OPENAI_HANDWRITING_*` names remain accepted as fallbacks.

The Provider Settings screen can override every non-secret setting for the
running backend. Only the actual key remains in `.env`. The checked-in
`.env.example` documents the allowed variables; `.env` itself stays ignored.

Provider profiles currently cover OpenAI, OpenRouter, DeepSeek, Anthropic Claude,
Ollama, and a custom OpenAI-compatible endpoint. Keys for several providers can
sit in `.env` together; the picker switches between them. `<PROVIDER>_BASE_URL`
(for example `DEEPSEEK_BASE_URL`) points one provider at its own endpoint, such
as a company-hosted deployment. Claude is reached through Anthropic's
OpenAI-compatible endpoint (`https://api.anthropic.com/v1/`), which Anthropic
intends for testing and comparing models. Recent Claude models reject a
temperature below 1, so none is sent to a model whose name contains `claude`
(the Course Context generator sends 1.0). The endpoint may not support model
listing, so type the Claude model name if the list stays empty. A successful provider test loads every model
identifier returned by that provider's `/models` endpoint. The exact selected
identifier is stored as the model/version. Provider support for tutoring does
not imply handwriting support: OCR additionally requires compatible image input
and structured Responses behavior.

## Mobile capture and progress

The responsive client uses `100dvh`, safe-area padding, touch-sized controls,
mobile-sized form fields, and horizontally scrollable navigation. The
handwriting attachment menu exposes a rear-camera input (`capture="environment"`)
and a separate image/PDF picker. Desktop drag-and-drop accepts PNG, JPEG, WebP,
and PDF files over the conversation or composer. Every path enters the same
preservation and confirmation pipeline. The OCR result is an editable
Markdown/LaTeX field with a live KaTeX preview; changing it never replaces the
preserved original artifact. Main content views scroll independently while the
desktop sidebar remains fixed.

Chat rendering supports `$...$` inline math and `$$...$$` display math. The
provider prompt requests these delimiters for mathematical responses, while
the local policy and student input use the same renderer.

Progress bars cover source uploads, course preparation, provider tests, tutoring
turns, and handwriting. They print the current stage in text for accessibility.
The synchronous V1 API does not stream true server percentages, so values below
100% are bounded stage estimates; success or failure is only printed after the
server responds.

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
