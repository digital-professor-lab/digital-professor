# Student Interaction V1

This folder contains Jonathan's isolated V1 Student Interaction implementation.
Keeping its Python package, tests, HTTP adapter, and frontend here reduces file
conflicts while teammates develop other modules on their own V1 branches.

## Contents

- `src/digital_professor/interaction/`: typed `StudentSubmission` and
  `StudentEvidence` pipeline, ports, coordinator, and mock integrations.
- `webapp/backend/`: FastAPI adapter for one typed tutoring turn.
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

## Run the typed-turn browser demo

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
