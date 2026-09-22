# Assessment prototype handoff

This folder is a runnable copy of the interaction-methods code, created on `jonathan/assessment-prototype` as the starting point for an assessment-first Digital Professor. The original research prototype remains under `research/interaction-methods/`.

## What was ported

- The three-tab browser interface, including chat, document upload, source exposure, and provider settings.
- Text, PDF, image, handwriting, and sketchpad input with reusable ingestion and recognition services.
- Tutor response rendering for mathematics and code, plus editable tutoring instructions.
- Recognition and response telemetry for latency, token usage, estimated cost, and correction feedback.
- Voice recording remains available from the source prototype but is optional for the first assessment workflow.

The assessment copy runs on separate local ports so it can be compared with the interaction prototype. From the repository root, start the backend with:

```bash
cd research/assessment-prototype
PYTHONPATH=src ../../.venv/bin/python -m uvicorn webapp.backend.app:app --reload --port 8001
```

In another terminal:

```bash
cd research/assessment-prototype/webapp/frontend
npm install
npm run dev
```

Open <http://localhost:5174>. The frontend proxies `/api` to port 8001. The root `.env` and `requirements.txt` are reused. Assessment telemetry is written to `research/assessment-prototype/logs/interaction_metrics.jsonl`.

In Sources, **Choose files** accepts multiple documents in one selection. Each file is uploaded and stored as a separate source; progress identifies the current file, and a failure for one file does not stop the remaining uploads. Each source file has a 100 MB limit.

The focused handwriting and course-grounded tutoring evaluation is prepared under [`evaluation/`](evaluation/README.md). Its case list and runner are ready; the handwritten images and human reference transcriptions still need to be supplied before the evaluation is run.

## Assessment workflow to implement next

1. Review the automatically classified syllabus and lecture notes. The syllabus parser now proposes a course name, course number, semester, and overview; the lecture-note parser now lists PDF outline topics with page numbers. Add editing and confirmation for the extracted structure.
2. Let the student select a section and request a quiz at a chosen difficulty.
3. Accept typed responses, uploaded work, or a sketchpad submission for each question.
4. Critique each response against a rubric and the relevant source material, explaining errors and giving a next-step hint.
5. Store quiz attempts and feedback so the student can revise and the team can evaluate learning outcomes.

The port preserves the working interaction machinery. It does not yet generate section quizzes or grade attempts; those will be built and evaluated on this branch.

## Source parsing behavior

The Sources tab defaults to **Detect automatically**. Upload processing lives in `webapp/backend/app.py`; the local classification and field-extraction rules live in `src/digital_professor/course_parsing.py`; the model fallback lives in `src/digital_professor/source_analysis.py`. The browser displays the returned `course` and `topics` fields but does not parse documents itself. Files are uploaded from the browser and copied to a temporary backend file; the original folder is irrelevant.

### Upload and classification

1. The backend accepts PDF, TXT, Markdown, TeX, and common image files. It extracts embedded text from documents; images and PDFs without usable embedded text go through the configured visual-recognition provider. The extracted text is also kept as source context for chat.
2. In automatic mode, a PDF with **more than 300 pages** is classified as a textbook. Otherwise, `classify_document` compares syllabus and lecture-note signals in the first 12,000 characters of **document text**. A filename containing `syllabus`, `lecture`, `notes`, or `slides` is a fallback when the text is inconclusive. A manual type selection in Sources overrides classification, including the page-count rule.
3. A classified syllabus gets local course-field extraction. Classified lecture notes get a PDF outline or heading-based topic list. A textbook gets a title from PDF metadata or its opening text. When classification is inconclusive or an expected field is missing, `source_analysis.py` asks the configured OpenAI model for a structured extraction from the uploaded text. This fallback requires `OPENAI_API_KEY`; if it fails, the upload remains available and the source card shows a warning.
4. The upload response includes the detected type and extracted fields, and the Sources tab displays each syllabus's results on its own card. The course summary uses the most recently uploaded syllabus.

Classification and extraction can still be uncertain when a scan is unreadable, important pages are outside the configured page limit, or the model cannot verify a field. The manual selector is the current type-correction path; editing extracted fields in the UI is future work. Model fallback adds latency and token cost; its request metadata is recorded with the upload.

### Syllabus fields

- **Course number:** Search the first 80 nonempty text lines for the first `###.###` or `AA.###.###` match, such as `553.762` or `EN.553.762`. Matching ignores case; the returned code is lowercase.
- **Course name:** Look on the course-number line first, then one line above, one below, two above, and two below. Remove the number and semester from each candidate. Use the first plausible title, excluding obvious administrative lines such as instructor or office information. Preserve its original capitalization.
- **Semester:** Search the same opening lines for a full term (`Fall`, `Summer`, `Winter`, `Spring`) or an abbreviation (`Fa`, `Su`, `Wi`, `Sp`, `F`, `S`, `W`) followed by a four-digit year beginning with `20`. Optional punctuation between term and year is accepted. Return lowercase text, such as `spring 2026` or `f 2026`; abbreviations are not expanded.
- **Course overview:** Look for an `Overview`, `Course overview`, `Description`, `Course description`, or `About the course` heading in the first 100 nonempty lines. Join subsequent lines into a paragraph until a known next section or page-number line, stopping after roughly 2,500 characters. If no heading is found, the field remains empty.

These are independent extractions: a missing semester, for example, does not prevent the course name or overview from appearing. The parser uses case-insensitive matching without lowercasing the displayed name or overview.

### Lecture-note topics

- For a PDF with an embedded bookmark/table-of-contents outline, `extract_topics` reads the **entire PDF outline** using PyMuPDF. It keeps each title, hierarchy level, and physical PDF page number, and assigns a generated outline number such as `2.3`.
- If there is no PDF outline, it scans extracted text for TeX `\section`/`\subsection`/`\subsubsection`, Markdown `#`/`##`/`###`, or numbered headings such as `2.1 Duality`. It records page numbers when extraction supplies `[PAGE n]` markers. This fallback is intentionally basic and may miss unnumbered headings or mistake numbered body text for a topic.
- The PDF's displayed page count is its full length. Text ingestion for chat and fallback heading detection is still limited by `DP_MAX_PAGES` in the root `.env` (five by default), so a bookmark-free PDF may yield only a partial topic list.

### Textbook titles

For automatic classification, the backend counts physical PDF pages with PyMuPDF before applying the **over 300 pages** rule. `extract_textbook_name` first checks the PDF title metadata, ignoring obvious generic values such as `Untitled` or `PDF`; if that is unavailable, it searches plausible lines near the beginning of the extracted text. If no title is found, the model fallback tries to identify one. The returned `textbook_name` appears on that source's card. The initial chat context still includes only the first `DP_MAX_PAGES` pages; full-book retrieval is future work.

### Adjusting and checking the rules

Edit `COURSE_NUMBER`, `SEMESTER`, `OVERVIEW_HEADING`, and `SECTION_HEADING` in `course_parsing.py` to broaden syllabus patterns. Change the marker lists in `classify_document` to refine detection, `_nearby_course_name` to change the title search, or `extract_topics` to add course-specific chapter rules. Keep uncertain matches visible for human review rather than silently treating them as verified course structure.

Run the focused parser tests with:

```bash
cd research/assessment-prototype
PYTHONPATH=src ../../.venv/bin/python -m unittest discover -s tests -v
```

The sample PDFs in `resources/assessment_prototype/` are useful manual checks: `762_syllabus.pdf` should yield `Nonlinear Optimization II`, `553.762`, and `spring 2026`; `762_notes.pdf` currently yields 68 bookmark topics across 59 pages. Course-specific topic rules and an editing/confirmation step can be added when the assessment workflow is defined.
