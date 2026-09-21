# Assessment prototype changelog

This log tracks work on `jonathan/assessment-prototype`. Version 0.1.0 is the first assessment-focused prototype, not a validated production release.

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
