# Assessment prototype changelog

This log tracks work on `jonathan/assessment-prototype`. Version 0.1.0 is the first assessment-focused prototype, not a validated production release.

## Unreleased — 2026-09-22

### Focused evaluation preparation

- Added a fixed 10-case handwriting template and eight 762-course tutoring scenarios, including questions whose source pages are outside the current chat-text window.
- Added the ten one-page handwritten PDF samples and visual reference transcriptions. h09 tests multicolor stylus ink and h10 tests variable-width calligraphy; references still need independent human review before provider scoring.
- Added a local evaluation runner for source uploads and tutoring requests, full-text recognition checks, review sheets, settings snapshots, and a summary of accuracy, grounding, consistency, failures, and latency.
- The intended baseline is the configured `OPENAI_MODEL` (`gpt-4o` if unset), OpenAI vision handwriting recognition, source citations enabled, and unchanged tutoring/explanation/review skills from `src/digital_professor/skills.json`. `DP_MAX_PAGES` defaults to `5`; `DP_RENDER_DPI` defaults to `180`. Temperature is not explicitly set, so the provider default applies. Optional input/output token rates in `.env` determine whether cost estimates are available.
- Each run records the **effective** model, skills, page limit, render DPI, recognition provider, citation setting, cost-rate settings, and cold/warm phase in a JSON settings snapshot. This distinguishes the actual evaluation configuration from the defaults above; no API key is written.
- Completed one cold and one warm batch per modality on the prepared set: 46 successful requests. All runs used `gpt-4o`, OpenAI vision for handwriting, five-page chat text, 180 DPI, and provider-default temperature; price rates were unset. Draft AI-assisted review scores and the interpretation are in [`evaluation/RESULTS_DRAFT.md`](evaluation/RESULTS_DRAFT.md). Independent human review and repeated cold runs remain pending.

## 0.1.0 — 2026-09-21

### First version

- Ported the local three-tab web app and reusable interaction services into `research/assessment-prototype/`, separate from the interaction-methods research prototype.
- Added a Sources workflow that accepts multiple files in one selection, processes each as an individual source, shows per-file progress, and continues when one upload fails.
- Added content-first classification for syllabi and lecture notes, with a manual type override and structured model extraction when local rules cannot resolve a document or its fields.
- Added syllabus extraction for course name, course number, semester, and course overview. Each syllabus displays its own extracted fields.
- Added lecture-note topic extraction from PDF bookmarks, with heading-based and model-assisted fallbacks.
- Added a Textbook type. PDFs over 300 pages are classified as textbooks in automatic mode; the app displays a title from PDF metadata, opening text, or model extraction.
- Preserved text, image, handwriting, sketchpad, voice, chat, source citations, provider settings, and interaction telemetry from the earlier prototype.
- Added focused parser and upload tests. The current sample syllabus and notes pass local checks, but this is not yet a broad accuracy evaluation.

### Next milestones

1. Run a large-scale verification set covering multiple syllabi, textbooks, lecture notes, and other documents with varied layouts, filenames, page counts, and scan quality. Record classification accuracy, field/topic extraction quality, failure cases, correction effort, latency, and cost; refine the rules and model fallback from those results.
2. After that verification, evaluate how well the LLM parses actual lecture notes into usable sections and detailed topics, including notes without PDF bookmarks. Compare extracted structure against a human-reviewed outline.
3. Use the verified course structure to build the quizzing and assessment framework: select a section, generate questions, accept typed or uploaded student work, provide rubric-based critique, and retain attempts for evaluation.
