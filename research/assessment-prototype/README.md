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

## Assessment workflow to implement next

1. Ingest a syllabus and course notes, then propose editable course sections with links to the source pages.
2. Let the student select a section and request a quiz at a chosen difficulty.
3. Accept typed responses, uploaded work, or a sketchpad submission for each question.
4. Critique each response against a rubric and the relevant source material, explaining errors and giving a next-step hint.
5. Store quiz attempts and feedback so the student can revise and the team can evaluate learning outcomes.

The port preserves the working interaction machinery. It does not yet generate section quizzes or grade attempts; those will be built and evaluated on this branch.
