# Interaction Prototype Usage

The interaction prototype is a research-stage local application. It consists of a FastAPI backend, a React/Vite frontend, and a Jupyter recognition demo. It can also be exposed temporarily over a local network for testing on a phone or tablet. Run commands from the repository root unless a step says otherwise.

## Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer with npm
- A LaTeX installation only if you want to rebuild `main.pdf`
- An OpenAI API key for model-assisted tutoring and handwriting recognition
- Tesseract 5 (optional) for the local non-LLM OCR baseline

## Python environment

Create and activate the repository virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The root `requirements.txt` installs the notebook, PDF-processing, OpenAI, FastAPI, and development-server dependencies.

To enable the optional Tesseract baseline on macOS:

```bash
brew install tesseract
```

On Debian or Ubuntu, install it with `sudo apt install tesseract-ocr`. Restart the backend after installing it so Provider Settings reports it as available.

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

## Test handwriting on a phone or tablet

Connect the computer and mobile device to the same Wi-Fi network. Start the backend normally from the repository root:

```bash
cd research/interaction-methods
PYTHONPATH=src ../../.venv/bin/python -m uvicorn webapp.backend.app:app --reload
```

In a second terminal, expose the Vite development server to devices on the local network:

```bash
cd research/interaction-methods/webapp/frontend
npm run dev -- --host 0.0.0.0
```

On macOS, find the computer's Wi-Fi IP address with:

```bash
ipconfig getifaddr en0
```

If that produces no output, try `ipconfig getifaddr en1`. On the phone or tablet, open `http://YOUR_MAC_IP:5173`, replacing `YOUR_MAC_IP` with the address from the command. For example, open `http://192.168.1.42:5173`.

In the application:

1. Open **Provider Settings** and select **OpenAI vision** or **Tesseract local baseline** as the handwriting recognizer.
2. Open **Chat** and tap the pencil button beside the message input.
3. Write with a finger, Apple Pencil, or another compatible stylus.
4. Adjust the pen width if needed, then tap **Upload to chat**.
5. Ask the Digital Professor to transcribe, interpret, check, or explain the uploaded work.

OpenAI vision generally gives better results for handwriting and mathematical notation. Tesseract provides a free local comparison baseline but works best on printed text and may not reconstruct equations as TeX. The API key stays in the backend environment on the computer and is not sent to the mobile device.

If the page does not load, check that both devices are on the same non-guest Wi-Fi network and allow incoming connections through the computer's firewall. Some university, corporate, guest, and client-isolated networks prevent devices from communicating with one another. This setup is intended only for trusted local-network testing; stop the Vite server when the test is complete.

## Test voice input

Voice input works on desktop browsers and mobile devices. In **Provider Settings**, choose a transcription model:

- `gpt-transcribe` for the current general high-accuracy option.
- `gpt-4o-transcribe` for a GPT-4o transcription comparison.
- `gpt-4o-mini-transcribe` for a smaller transcription model and the prototype default.
- `whisper-1` as the older Whisper baseline.

These choices use the OpenAI provider and the backend's `OPENAI_API_KEY`; the key is never placed in the browser. Model availability depends on the configured API account.

For a second provider, install the optional local faster-whisper baseline in the active virtual environment:

```bash
python -m pip install faster-whisper
```

Restart the backend, select **Local faster-whisper**, and choose `tiny`, `base`, or `small`. The first use downloads the selected model, so it takes longer and requires network access. Later requests run locally on the computer with no transcription API cost. Larger models usually require more memory and processing time. The prototype uses CPU execution with `int8` computation to keep the baseline portable.

To dictate a question:

1. Open **Chat** and tap or click the red microphone button beside the sketchpad button.
2. Allow microphone access when the browser requests it.
3. Speak the question, including any mathematical terms you want to test.
4. Tap or click the square stop button.
5. Wait for transcription. The recognized text is inserted into the chat box so it can be reviewed and corrected before sending.
6. Select another provider or model in **Provider Settings** and repeat the same recording to compare results. The composer reports the selected provider, model, and transcription time after each request.

The in-browser recorder normally produces WebM or M4A audio. The backend also accepts FLAC, MP3, MP4, MPEG, MPGA, M4A, OGG, WAV, and WebM, up to the prototype's 20 MB request limit.

Browser microphone capture requires a secure context. It works on `localhost`, but a phone or tablet opening the computer's plain HTTP LAN address may block direct microphone access. When browser recording is unavailable, the microphone control opens the device's audio capture or file picker instead. Record with the device recorder or Voice Memos and select that audio file for transcription. For uninterrupted in-page recording on a mobile device, serve the prototype through a trusted HTTPS development URL.

On iPhone or iPad, confirm microphone permission under **Settings > Privacy & Security > Microphone** and in the browser's site settings. On a computer, confirm microphone permission in the browser and operating-system privacy settings. If a recording fails, reload the page after granting permission and verify that the selected transcription model is available to the API account.

## Use the prototype

1. Open **Sources** and upload a syllabus.
2. Review the detected course name, code, and term.
3. Add lecture notes, homework, or student work through Sources or the attachment button in Chat.
4. Open **Provider Settings** to select an available model, enter token rates, or edit the tutoring, explanation, and review instructions for the browser session.
5. Enable **Expose sources in answers** when the demonstration should show citations to uploaded material.
6. Select OpenAI vision or the optional local Tesseract baseline for handwriting recognition.
7. Open **Chat** and enter a question, equation, or code example. Use the pencil button to draw directly in the sketchpad and upload the canvas as a handwriting source.
8. Review the answer's **Sources** section, then rate recognized source content with **Good** or **Needs correction**.

Use `$...$` for inline TeX and `$$...$$` for display equations. Use single backticks for inline code and triple backticks for fenced code blocks.

The upload pipeline supports PDF, TXT, Markdown, TeX, PNG, JPEG, and WebP files. PDFs with usable embedded text are extracted locally. Image files and PDFs without usable embedded text are sent through the selected visual recognizer. OpenAI vision requires a configured API key. Tesseract runs locally with zero API cost, but it is primarily a printed-text baseline and does not reliably reconstruct handwritten mathematics as LaTeX. Uploaded sources and chat messages are held in memory and reset when the backend restarts.

### Source citations

In **Provider Settings**, enable **Expose sources in answers** to show citations for uploaded material used in a response. Citation entries display the source filename, a page number when preserved by ingestion, and a short explanation of how the source supports the answer. The backend accepts only citations whose source IDs match the current workspace. Disable the setting to keep citations out of the displayed response while retaining course material as tutor context.

### Evaluation metrics

The backend records metadata-only research events at:

```text
research/interaction-methods/logs/interaction_metrics.jsonl
```

The runtime log is ignored by Git. It does not contain document contents, recognized text, chat questions, or tutor answers. Each JSON Lines event can include:

- Interaction type and modality
- Provider, model, and recognition method
- Page count and elapsed time
- Input, output, and total tokens when the provider returns them
- Estimated request cost when token rates are configured
- Mean equation-recognition confidence as a model-derived quality proxy
- A student-supplied recognition quality rating
- Character edit distance and normalized correction rate between a voice transcript draft and the text ultimately sent
- Whether sources were exposed and how many valid citations were returned

Click **Good** or **Needs correction** on a source card to add a human quality rating. Voice correction effort is recorded automatically when a transcription is edited and then submitted. Metrics for the current backend session are also available from `GET /api/evaluation/metrics`, and a 1--5 rating can be submitted programmatically to `POST /api/evaluation/feedback` with an `interaction_id` and `quality_rating`.

Inspect the session metrics in a browser at <http://127.0.0.1:8000/api/evaluation/metrics>, or from a terminal:

```bash
curl -s http://127.0.0.1:8000/api/evaluation/metrics | python -m json.tool
```

Watch persistent events arrive during a demonstration with:

```bash
tail -f research/interaction-methods/logs/interaction_metrics.jsonl
```

Submit a 1--5 quality rating directly when testing the API:

```bash
curl -X POST http://127.0.0.1:8000/api/evaluation/feedback \
  -H 'Content-Type: application/json' \
  -d '{"interaction_id":"SOURCE_OR_TRANSCRIPTION_ID","quality_rating":4}'
```

Recognition confidence is only a proxy produced by the recognition model. It is not ground-truth accuracy. Formal evaluation should compare recognized output with a reference transcription and calculate character or word error rates.

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
