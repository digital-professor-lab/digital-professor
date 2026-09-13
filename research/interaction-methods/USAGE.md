# Interaction Prototype Usage

The interaction prototype is a research-stage localhost application. It consists of a FastAPI backend, a React/Vite frontend, and a Jupyter recognition demo. Run commands from the repository root unless a step says otherwise.

## Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer with npm
- A LaTeX installation only if you want to rebuild `main.pdf`
- An OpenAI API key for model-assisted tutoring and handwriting recognition

## Python environment

Create and activate the repository virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The root `requirements.txt` installs the notebook, PDF-processing, OpenAI, FastAPI, and development-server dependencies.

## Environment variables

Copy the environment template if `.env` does not already exist:

```bash
cp .env.example .env
```

Set the API key and desired default model in the root `.env`:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-4o
```

The optional `OPENAI_INPUT_COST_PER_1M` and `OPENAI_OUTPUT_COST_PER_1M` values enable per-request cost estimates. They should contain the current USD rates for the selected model. The backend exposes whether a key is configured but never sends the key itself to the browser.

## Run the web application

Start the backend from the repository root:

```bash
cd research/interaction-methods
PYTHONPATH=src ../../.venv/bin/python -m uvicorn webapp.backend.app:app --reload
```

The API runs at <http://127.0.0.1:8000>. Its interactive API documentation is available at <http://127.0.0.1:8000/docs>.

In a second terminal, install and run the frontend:

```bash
cd research/interaction-methods/webapp/frontend
npm install
npm run dev
```

Open <http://localhost:5173> in a browser. Vite proxies `/api` requests to the local FastAPI server.

Use the virtual environment's Python command shown above instead of a bare `uvicorn` command. This prevents a globally installed Python or FastAPI version from starting the server.

## Use the prototype

1. Open **Sources** and upload a syllabus.
2. Review the detected course name, code, and term.
3. Add lecture notes, homework, or student work through Sources or the attachment button in Chat.
4. Open **Provider Settings** to select an available model, enter token rates, or edit the tutoring, explanation, and review instructions for the browser session.
5. Open **Chat** and enter a question, equation, or code example.

Use `$...$` for inline TeX and `$$...$$` for display equations. Use single backticks for inline code and triple backticks for fenced code blocks.

The upload pipeline supports PDF, TXT, Markdown, TeX, PNG, JPEG, and WebP files. PDFs with usable embedded text are extracted locally. Image files and PDFs without usable embedded text are sent through visual handwriting recognition and therefore require a configured API key. Uploaded sources and chat messages are held in memory and reset when the backend restarts.

## Run the notebook

With the root virtual environment active, run:

```bash
jupyter lab notebooks/recognition_demo.ipynb
```

The notebook is divided into text/equation ingestion and handwritten recognition. API-backed cells skip themselves when `OPENAI_API_KEY` is unavailable.

## Build checks

Build the frontend:

```bash
cd research/interaction-methods/webapp/frontend
npm run build
```

Rebuild the research document from the repository root:

```bash
cd research/interaction-methods
pdflatex main.tex
pdflatex main.tex
```

LaTeX's intermediate files are ignored by Git; `main.tex` and `main.pdf` remain trackable.
