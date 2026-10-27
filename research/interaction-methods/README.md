# Student Interaction V1

This folder contains Jonathan's isolated V1 Student Interaction implementation.
Keeping its Python package, tests, HTTP adapter, and frontend here reduces file
conflicts while teammates develop other modules on their own V1 branches.

## Contents

- `src/digital_professor/interaction/`: typed and handwritten
  `StudentSubmission` and `StudentEvidence` pipelines, recognition and
  downstream ports, coordinator, and mock integrations.
- `webapp/backend/`: FastAPI adapter for typed and handwritten tutoring turns.
- `webapp/frontend/`: React interface adapted from the lightweight prototype.
- `tests/`: pipeline and HTTP contract tests.

The Tutoring Engine and Delivery implementations are explicit mocks. This
iteration verifies the Interaction contracts and handoffs without taking over
diagnosis, tutoring decisions, or presentation responsibilities.

## Install component dependencies

Activate the repository virtual environment, then run from the repository
root:

```bash
python -m pip install -r research/interaction-methods/requirements.txt
```

Install frontend dependencies:

```bash
cd research/interaction-methods/webapp/frontend
npm install
cd ../../../..
```

## Run tests

From the repository root:

```bash
PYTHONPATH=research/interaction-methods/src \
  python -m pytest research/interaction-methods/tests -q
```

## Configure handwriting recognition

Copy the component environment example and add an API key:

```bash
cp research/interaction-methods/.env.example research/interaction-methods/.env
```

`OPENAI_HANDWRITING_MODEL` selects the vision-capable recognition model. The
recognizer processes PNG, JPEG, WEBP, and PDF uploads. V1 limits an upload to
20 MB and processes at most five PDF pages in one recognition request. The
original upload remains separate from the recognized and corrected text.

## Run the browser demo

Start the API from the repository root:

```bash
PYTHONPATH=research/interaction-methods/src \
  .venv/bin/uvicorn webapp.backend.app:app \
  --app-dir research/interaction-methods --reload
```

In a second terminal:

```bash
cd research/interaction-methods/webapp/frontend
npm run dev
```

Open `http://127.0.0.1:5173`. Submit an initial typed attempt and then a
revision. The interface displays evidence validation, the structured action,
delivery status, and the handoff trace. Markdown, code, and LaTeX are rendered.

To test handwriting, choose **Upload handwriting** and select a supported image
or PDF. Review the transcription before continuing. When a symbol could change
the mathematical meaning, resolve every highlighted ambiguity. The system then
creates `RecognitionCorrection` records, constructs validated
`StudentEvidence`, and uses the same downstream coordinator as typed input.

## Handwriting contract and downstream boundary

The implementation follows `specs/student-interaction.md` and
`specs/interfaces.md`:

1. Preserve the original image, PDF, or canvas export as an immutable artifact.
2. Record provider/model provenance, processed pages, ordered page/region
   steps, alternatives, ambiguity, and recognition latency.
3. Keep raw provider output only when diagnostic logging is enabled.
4. Block meaning-changing ambiguity until the student supplies a focused
   resolution or edits the transcription.
5. Preserve recognition and correction references in `StudentEvidence`.
6. Send only validated evidence to the Tutoring Engine boundary.

Sean's retrieval component remains downstream of this boundary. It should
receive the stable `course_id`, `question_id`, `turn_id`, and the minimum
confirmed evidence summary needed for retrieval. It should not receive the raw
handwriting artifact or unresolved recognition as trusted mathematical text.
The owner of `RetrievalRequest` generation is still an open team decision in
the specification, so this component does not create a competing retrieval
implementation. Once that decision is made, a Retrieval port can be inserted
between evidence validation and the existing Tutoring Engine handoff without
changing the handwriting records.
