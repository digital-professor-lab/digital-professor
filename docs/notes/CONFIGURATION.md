# Configuring the Digital Professor demo

This guide explains every setting of the integrated demo: what it does, its
default, and when to change it. The first part is a step-by-step setup that
needs no programming knowledge. The reference table at the end lists every
variable.

All settings live in one file, `.env`, in the repository root. It is created
from the template `.env.example` and is **never** uploaded to GitHub (it is
listed in `.gitignore`). Restart the demo after changing it.

## 1. Quick start

You need Python 3.10 or newer and an OpenRouter API key.

1. **Install** (once). In a terminal, from the repository folder:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   python -m pip install -e "research/knowledge-retrieval/retrieval-tool[test]"
   ```

2. **Create your settings file.**

   ```bash
   cp .env.example .env
   ```

3. **Add the key.** Open `.env` in a text editor and paste the key after
   `OPENROUTER_API_KEY=`, with no quotes and no spaces. Save the file.
   (On a Mac, Finder hides files that start with a dot: press
   **Cmd + Shift + .** to show them.)

4. **Start the demo.**

   ```bash
   PYTHONPATH=src:research/knowledge-retrieval/retrieval-tool \
     uvicorn digital_professor.webapp.app:app --reload
   ```

5. **Open** <http://127.0.0.1:8000>, upload the syllabus, then the textbook or
   lecture notes, select **Start DP and build retrieval**, and start a tutoring
   session once the course shows as ready.

Without any key the demo still runs, but replies come from fixed sentences
instead of a language model.

## 2. Choosing the tutoring model

| Setting | Default | What it does |
|---|---|---|
| `DIGITAL_PROFESSOR_PROVIDER` | `openrouter` (in `.env.example`) | Which service is called: `openrouter`, `deepseek`, `anthropic`, `openai`, `ollama` (local) or `custom`. |
| `DIGITAL_PROFESSOR_MODEL` | `deepseek/deepseek-v4.1-flash-1017` | The exact model name at that service. |

**Recommended:** the default. It is DeepSeek V4.1 Flash, the model DeepSeek's
own API serves under the name `deepseek-chat`, reached through OpenRouter. It
answers a turn in one to two seconds.

Each service needs its own key in `.env`:

| Provider | Key variable | Example model name |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | `deepseek/deepseek-v4.1-flash-1017` |
| DeepSeek (direct) | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| Anthropic Claude | `ANTHROPIC_API_KEY` | a Claude model name, typed by hand |
| OpenAI | `OPENAI_API_KEY` | `gpt-4.1-mini` |
| Ollama (local) | none | the local model name |

Good to know:

- Several keys can sit in `.env` together. The **Provider settings** page in the
  demo switches between them while the demo runs, and **Test provider and load
  models** lists the model names available to the key. The page never shows or
  accepts a key.
- On OpenRouter, `deepseek/deepseek-chat` is an **older** DeepSeek model, not the
  one DeepSeek's API calls `deepseek-chat` today. Use the default name above.
- `deepseek/deepseek-v4-pro` (or `deepseek-v4-pro` on DeepSeek directly) writes
  more carefully but takes around 12 seconds per turn, because the Engine makes
  two or three model calls per turn.
- Claude is useful as a comparison model. Claude models reject a low
  "temperature" setting, so the demo sends none to them.
- `<PROVIDER>_BASE_URL` (for example `DEEPSEEK_BASE_URL`) points one service at
  its own address, such as a company-hosted DeepSeek. `DIGITAL_PROFESSOR_BASE_URL`
  overrides the address of the selected service.
- `DIGITAL_PROFESSOR_INPUT_COST_PER_MILLION` and
  `DIGITAL_PROFESSOR_OUTPUT_COST_PER_MILLION` (USD per million tokens) only add
  estimated costs to the logs. They do not affect billing.

## 3. Handwriting recognition (optional)

Students can photograph or upload handwritten work. A vision model reads it and
the student confirms the text before it is used.

| Setting | Default | What it does |
|---|---|---|
| `DIGITAL_PROFESSOR_HANDWRITING_MODEL` | `gpt-4o-mini` | The vision model. |
| `OPENAI_API_KEY` | empty | Key used for handwriting (it is called through the OpenAI client). |
| `OPENAI_BASE_URL` | OpenAI | Set to `https://openrouter.ai/api/v1` to use OpenRouter. |

To use the OpenRouter key for handwriting as well: set the model to
`openai/gpt-4o-mini`, paste the OpenRouter key into `OPENAI_API_KEY`, and set
`OPENAI_BASE_URL=https://openrouter.ai/api/v1`. This also sends the `openai`
tutoring profile to OpenRouter, so use it only when OpenRouter is the service
you tutor with.

## 4. Jev passage judge (optional)

When the tutor points a student to the textbook, it attaches one passage under
its reply. Jev, a small judging model, checks which candidate passage actually
**states** the rule (for example the Chain Rule itself) rather than a proof, an
example or an introduction, and that passage is attached.

| Setting | Default | What it does |
|---|---|---|
| `DP_JEV` | on when `OPENROUTER_API_KEY` is set | `off` uses the built-in rules only. |
| `JEV_MODEL` | `typesafe/jev-1.13` | The Jev model on OpenRouter. |
| `DP_JEV_CACHE` | `.cache/jev/jev_answers.jsonl` | Saved answers, so a passage is never scored (or paid for) twice. |

- **Only textbook text and the method name are sent to Jev.** Student messages
  never are.
- If Jev is slow or unavailable, the built-in rules choose, as before. A turn
  never fails because of Jev.
- `TYPESAFE_API_KEY` can be used instead of an OpenRouter key.

## 5. Course material and retrieval

The demo searches the uploaded course material to find passages for the tutor.

**Retrieval V1 (recommended).** It uses the Week 3 search code and two embedding
models (BGE and Qwen). It is optional; without it the demo uses a simpler
keyword index. To install it (once, needs internet):

```bash
bash research/knowledge-retrieval/retrieval-tool/scripts/setup_week3.sh
python -m pip install -e "research/knowledge-retrieval/retrieval-tool[postgres,embeddings]"
```

`GET /api/status` (open <http://127.0.0.1:8000/api/status>) shows which index each
course uses and, if it fell back to keywords, why.

| Setting | Default | What it does |
|---|---|---|
| `DP_RETRIEVAL_MODE` | `auto` | `auto`: Retrieval V1 when installed, otherwise keywords. `tool`: require Retrieval V1. `keyword`: keywords only. |
| `DP_RETRIEVAL_MODELS` | both | Use only some embedding models, for example `bge_base_en_v1_5`. |
| `WEEK3_KB` | not set | A Week 3 `knowledge_base` folder whose downloaded models should be reused. |
| `HF_HOME` | Hugging Face default | Where embedding models are stored. |
| `HF_HUB_OFFLINE` | not set | `1` stops model downloads once the models are present. |
| `DP_RETRIEVAL_ROOT` | `retrieval-tool/.week3` | Location of the Week 3 search code, if not in the default folder. |
| `DP_TEXTBOOK_SCOPE` | `off` | `on`: ingest only the textbook sections the syllabus lists. |
| `DP_KEEP_COURSES` | not set | `1`: save published courses and restore them after a restart (local development). |
| `DP_COURSE_CACHE` | `.cache/courses` | Where saved courses are kept. |

**Whole book or syllabus scope?** By default the whole textbook is ingested, so
the tutor can also answer questions outside the syllabus. With
`DP_TEXTBOOK_SCOPE=on` only the sections the syllabus lists are read: for the
Calculus I reference course, 320 of 841 pages, about 60% less embedding work.
Questions outside the syllabus then find no textbook passage. Embeddings are
saved under `.cache/retrieval_index/`, so publishing the same book again is fast
either way.

## 6. Tutoring Engine switches (for experiments)

Leave these unset for normal use.

| Setting | Default | What it does |
|---|---|---|
| `DIGITAL_PROFESSOR_REPLY_GUARD` | `1` | `0` turns off the guard model that re-checks replies containing new math. The code checks still run. |
| `DIGITAL_PROFESSOR_ENGINE_RETRIEVAL` | `1` | `0` stops the Engine from searching the course material. |
| `DIGITAL_PROFESSOR_LOG_DIR` | `logs` | Folder for run logs. |

## 7. What is stored, and what is sent where

| Location | Contents | Uploaded to GitHub? |
|---|---|---|
| `.env` | Your keys and settings | Never |
| `logs/<date>/<session>/` | One file per step of each session (inputs, decisions, outputs, sources) | Never |
| `.cache/courses/` | Saved courses (with `DP_KEEP_COURSES=1`) | Never |
| `.cache/retrieval_index/` | Saved embeddings | Never |
| `.cache/jev/` | Saved Jev answers | Never |

| Service | Receives |
|---|---|
| Tutoring model | The question, the student's messages, the conversation, textbook passages |
| Jev | Textbook passages and the method name only |
| Handwriting model | The uploaded image or PDF of the student's work |

Whether student text may be sent to a hosted model for real students is still a
team decision; the demo is for development with test data.

## 8. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Replies are fixed sentences such as "How would you start this one?" every time | No key, or the key is in the wrong variable. Check `.env`, then restart. |
| "No key found in OPENROUTER_API_KEY" | The key line is empty or has quotes or spaces. |
| The provider test fails | Wrong model name for that service, or the key has no credit. |
| `/api/status` says the course uses the keyword index | Retrieval V1 is not installed; see section 5. |
| Building a course takes minutes | The first build embeds the whole book. Later builds of the same file reuse saved embeddings. |
| "looks like a textbook ... not a syllabus" when uploading | The file was put in the wrong step. The syllabus goes in step 1, the textbook in step 2. |
| No textbook passage under the reply | Passages are attached from the second time the student is stuck. If none states the rule, none is attached on purpose. |
| Handwriting fails | No vision model key; see section 3. |

## 9. Reference: every variable

| Variable | Default | Section |
|---|---|---|
| `DIGITAL_PROFESSOR_PROVIDER` | `openai` in code, `openrouter` in `.env.example` | 2 |
| `DIGITAL_PROFESSOR_MODEL` | `gpt-4.1-mini` in code, `deepseek/deepseek-v4.1-flash-1017` in `.env.example` | 2 |
| `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DIGITAL_PROFESSOR_API_KEY` | empty | 2 |
| `DIGITAL_PROFESSOR_API_KEY_ENV` | the profile's key variable | 2 |
| `DIGITAL_PROFESSOR_BASE_URL`, `<PROVIDER>_BASE_URL` | the profile's address | 2 |
| `DIGITAL_PROFESSOR_INPUT_COST_PER_MILLION`, `DIGITAL_PROFESSOR_OUTPUT_COST_PER_MILLION` | empty | 2 |
| `DIGITAL_PROFESSOR_HANDWRITING_MODEL` | `gpt-4o-mini` | 3 |
| `DIGITAL_PROFESSOR_HANDWRITING_INPUT_COST_PER_MILLION`, `..._OUTPUT_COST_PER_MILLION` | empty | 3 |
| `OPENAI_BASE_URL` | OpenAI | 3 |
| `DP_JEV` | on with an OpenRouter key | 4 |
| `JEV_MODEL` | `typesafe/jev-1.13` | 4 |
| `DP_JEV_CACHE` | `.cache/jev/jev_answers.jsonl` | 4 |
| `TYPESAFE_API_KEY` | empty | 4 |
| `DP_RETRIEVAL_MODE` | `auto` | 5 |
| `DP_RETRIEVAL_MODELS` | both models | 5 |
| `DP_RETRIEVAL_ROOT` | `retrieval-tool/.week3` | 5 |
| `WEEK3_KB`, `HF_HOME`, `HF_HUB_OFFLINE` | not set | 5 |
| `DP_TEXTBOOK_SCOPE` | `off` | 5 |
| `DP_KEEP_COURSES` | not set | 5 |
| `DP_COURSE_CACHE` | `.cache/courses` | 5 |
| `DIGITAL_PROFESSOR_REPLY_GUARD` | `1` | 6 |
| `DIGITAL_PROFESSOR_ENGINE_RETRIEVAL` | `1` | 6 |
| `DIGITAL_PROFESSOR_LOG_DIR` | `logs` | 6 |
| `DIGITAL_PROFESSOR_SKIP_DOTENV` | not set | Tests only: do not read `.env`. |
