# Changelog

This file records prototype and research milestones. Dates describe when work was added to this repository rather than formal software releases.

## 2026-09-13

### Voice transcription interaction

- Added microphone recording to the chat composer for desktop, phone, and tablet input.
- Added a mobile audio-capture and file-selection fallback for browsers that block direct recording.
- Added backend audio transcription with `gpt-transcribe`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, and `whisper-1` comparison options.
- Added an availability-gated local faster-whisper provider with `tiny`, `base`, and `small` model choices for API-free baseline comparisons.
- Added transcription model and elapsed-time feedback while keeping recognized text editable before it is sent to the tutor.
- Documented desktop and mobile voice testing, microphone permissions, accepted formats, and secure-context limitations.

## 2026-09-11

### Local web application prototype

- Added a browser interface with Sources, Provider Settings, and Chat tabs.
- Added syllabus-first onboarding and conservative course-name, course-code, and term detection.
- Added uploads for syllabi, course documents, and handwritten work.
- Added a local FastAPI adapter for document ingestion, visual recognition, source management, and tutoring requests.
- Added mathematical response rendering, ambiguity disclosure, comprehension checks, latency, token usage, and estimated request cost to the chat experience.
- Added an Office Hours entry marked as coming soon.
- Kept the first application test local through Vite and FastAPI development servers.
- Populated the model selector from the models available to the configured API key.
- Added multi-document attachments directly to the chat composer.
- Added fenced and inline code rendering and corrected KaTeX rendering for dollar-sign and backslash-style math delimiters.
- Added an in-chat sketchpad that exports drawings as PNG handwriting sources.
- Added a selectable local Tesseract OCR baseline with availability reporting, timing metadata, and zero API cost.
- Added automatic visual-recognition fallback for image-only PDFs, including handwritten PDFs attached from Chat.
- Moved tutoring, explanation, and review behavior into a separate configurable skills file and exposed session overrides in Provider Settings.
- Increased response, list, heading, and display-equation spacing for readability.
- Expanded the future Office Hours concept to include a live digital avatar, real-time text and voice, optional video, transcripts, and a shared work surface.

### Future work

- Convert the local prototype into a public-facing website after the interaction flow, privacy controls, authentication, persistence, deployment configuration, and evaluation criteria are established.
- Add cross-model recognition comparisons using identical source inputs and result schemas.
- Add source-page citations, editable syllabus metadata, and persistent course workspaces.
- Develop Office Hours as a live tutoring mode after the asynchronous chatbot is evaluated.

## 2026-09-10

### Recognition and tutoring notebook

- Added a two-part notebook demo for text/equation ingestion and handwritten recognition.
- Added reusable PDF extraction, page rendering, equation detection, structured recognition, and tutoring machinery under `research/interaction-methods/src/digital_professor`.
- Kept the executable interaction prototype under `research/interaction-methods/` while the project remains in its research phase; the root `src/` directory remains reserved for the developmental product.
- Added editable equation/question tutoring with worked explanations, stated assumptions, and comprehension checks.
- Added request metadata for elapsed time, token usage, and configurable cost estimates.
- Added local environment and Python dependency templates.

### Interaction research

- Added research on voice, speech recognition, text, document understanding, handwriting, mathematical notation, images, tablets, and video interaction.
- Compared relevant libraries, APIs, models, technical feasibility, and supporting papers.
- Proposed a three-tab chatbot prototype with syllabus-first setup and a deferred Office Hours experience.
- Documented a possible future manager-worker agent expansion and related mathematical training datasets.
