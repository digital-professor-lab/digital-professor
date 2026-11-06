# Integrated Demo Test Results

**Date:** 2026-11-06  
**Branch at validation:** `jm/JDP-55_init-implementation`  
**Status:** Development changes are on the Jira-linked initial implementation
branch and remain subject to peer review.

## Automated results

| Check | Result |
|---|---|
| Root product and contract suite | 84 passed, 6 third-party deprecation warnings |
| Course Context research regression | 28 passed |
| Retrieval research regression | 100 passed, 26 expected optional-integration skips |
| Python compile check | Passed |
| Browser JavaScript syntax check | Passed |
| `git diff --check` | Passed |

The warnings come from PyMuPDF/SWIG and Starlette/AnyIO dependencies. No project
test failed.

## Behaviors verified

- A syllabus and multiple notes can be staged through separate requests, then
  parsed and published together as text or real PDFs.
- Ingestion preserves content versions, page numbers, and normalized line ranges.
- A course is rejected when no syllabus or searchable knowledge source exists.
- A runtime Question Schema is created with explicit partial/review-required status.
- Two POST requests reuse one session and link submission, evidence, and action IDs.
- A session snapshot restores only the student-facing transcript and sources.
- The application reports setup-required before ingestion and ready-for-query
  only after course parsing and retrieval indexing complete.
- Runtime provider settings change model, endpoint, pricing, and OCR model while
  the API rejects attempts to submit an API key.
- Tutoring policy selects a phase/action, creates pending Learner State, and
  commits it only after successful delivery.
- The local deterministic tutoring policy remains usable when no paid provider
  key is configured.
- Retrieved source links open the page and highlight the cited line range.
- Operational handoffs remain recorded with diagnostic logging disabled.
- Timestamped backend diagnostic files include sources, issues, model/token
  data, compute time, and configured cost estimates without cluttering the UI.
- Question Schema and internal handoff records are absent from browser APIs.
- Extracted course names can be corrected after publication.
- Inline TeX/code rendering and animated typing feedback are present in the UI.
- The responsive chat uses available viewport space and exposes handwriting as
  an attachment control.
- Activity summaries are reconstructed from timestamped backend files, and an
  exact TeX equation survives original, recognized, and displayed-input fields.
- Explicitly mismatched course numbers reject a notes batch; matching numbers
  verify it; missing identity signals remain visible as partially verified.
- Both initial and follow-up chat prompts state the `$equation$` and backtick
  code conventions.
- Handwriting remains blocked after OCR until the student confirms the transcription.
- Confirmed handwriting enters the same evidence, retrieval, Engine, and Delivery path.
- Missing API keys return a structured provider-test failure without exposing secrets.

## Not validated with a live provider

No `OPENAI_API_KEY` was configured in the root environment during this run.
Therefore, the live provider authentication call, paid tutoring generation, and
paid handwriting OCR were not executed. The deterministic test providers verify
request shape, chaining, accounting, uncertainty confirmation, and failure
behavior without network use or cost.

After adding a key to `.env`, manually verify:

1. **Provider Settings → Test configured API key** succeeds.
2. One tutoring response records the selected model, token counts, latency, and
   estimated cost when pricing variables are configured.
3. One handwritten image produces a transcription, confirmation screen, and
   confirmed tutoring turn.
4. Refreshing the browser restores the same active session and transcript.

## Known limits

- Browser refresh recovery depends on the same backend process remaining alive.
- Course, index, session, and log repositories are in memory.
- Cost values are estimates based on manually configured token rates.
- OCR uses an OpenAI vision model; other handwriting providers need adapters.
- The full Course Context validation, production Retrieval tool loop, Tutoring
  Engine policy, and Delivery service remain future integration work.
