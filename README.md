# Digital Professor

**Company:** Entagile

**Team:** Jonathan Ma, Sean Song, Ovunc Eker, Yining Li

Digital Professor is a course-aware tutoring system that captures student work,
grounds assistance in instructor-provided course material, tracks evidence of
student understanding, and returns an appropriate tutoring action. The
architecture is intended to remain course-agnostic; Calculus is the current
reference course for implementation and validation.

## V1 implementation

Product code lives in [`src/digital_professor`](src/digital_professor). Work
under `research/` remains reference material or a component prototype until it
is deliberately promoted into the product package.

The implementation follows the contracts and boundaries in:

- [`specs/architecture.md`](specs/architecture.md)
- [`specs/interfaces.md`](specs/interfaces.md)
- [`specs/student-interaction.md`](specs/student-interaction.md)
- [`specs/course-context.md`](specs/course-context.md)
- [`specs/rag-retrieval.md`](specs/rag-retrieval.md)
- [`specs/tutoring-engine.md`](specs/tutoring-engine.md)

The current integrated demo is:

```text
Uploaded syllabus and notes -> normalized pages/chunks -> course retrieval
                                                         |
StudentSubmission -> StudentEvidence -> stateful Tutoring Engine -> mock Delivery
        ^                                  |                       |
        \------ linked follow-up turn -----+------ DeliveryResult -+
```

The root package is divided by specification ownership:

| Package | Current responsibility |
|---|---|
| `interaction` | Preserve typed or handwritten input, handle recognition and confirmation, construct factual `StudentEvidence`, coordinate handoffs, and record trace events. |
| `course_context` | Parse syllabus and notes, preserve page/line mappings, publish an in-memory course workspace, and build a partial runtime Question Schema. |
| `retrieval` | Search uploaded course chunks and return passages with document, version, page, line, and source-view links. |
| `tutoring` / `runtime` | Maintain a session, link follow-up evidence, optionally call an OpenAI-compatible model, produce `TutoringAction`, and apply state only after confirmed delivery. |

Delivery remains mocked. Course workspaces, indexes, sessions, and logs are
in-memory and reset when the server restarts. Without a provider key, the demo
uses a deterministic grounded prompt; with a configured key, it calls the
selected OpenAI-compatible model.

## Repository setup

### Requirements

- Git
- Python 3.10 or newer
- A shell that can activate a Python virtual environment

Node.js is only required for the earlier browser prototype under `research/`;
it is not required for the root V1 test suite.

### Clone and create the environment

```bash
git clone https://github.com/digital-professor-lab/digital-professor.git
cd digital-professor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e "research/knowledge-retrieval/retrieval-tool[test]"
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

### Verify the checkout

Follow the ordered [`V1 testing plan`](docs/notes/V1_TESTING_PLAN.md) when
validating a candidate for team review.

Run the environment and product tests from the repository root:

```bash
PYTHONPATH=src:research/knowledge-retrieval/retrieval-tool \
  python -m pytest tests -q
```

Run only the integrated tutoring-turn and shared-contract checks:

```bash
PYTHONPATH=src:research/knowledge-retrieval/retrieval-tool \
  python -m pytest tests/interaction/test_initial_integration.py \
                  tests/test_spec_contracts.py -v
```

### Run the integrated demo

Copy the provider template and add a key if model-generated tutoring responses
are needed. The key stays server-side.

```bash
cp .env.example .env
# Edit .env and set only the provider API key.
```

```bash
PYTHONPATH=src:research/knowledge-retrieval/retrieval-tool \
  uvicorn digital_professor.webapp.app:app --reload
```

Open <http://127.0.0.1:8000>. Upload one syllabus in the syllabus section, then
upload one or more notes/textbook files in the notes section. Select **Start DP
and build retrieval**. Chat stays unavailable until parsing,
page/line normalization, chunking, and retrieval indexing finish. The app then
reports that the course is ready for queries and opens tutoring setup.

Before publication, ingestion compares course identity signals from the
syllabus against each notes/textbook file. A conflicting explicit course number
or explicit course-title header pauses publication and displays the conflict.
The user may explicitly confirm that the materials belong together; the
published workspace is then labeled **override confirmed** and preserves the
conflict in its audit notes. Files without an identifiable course marker are
allowed but the workspace is labeled **partially verified** with a review note.
Matching identifiers produce **verified** status. This is a guardrail rather
than a semantic proof that every passage belongs to the course.

Use **Provider settings** to select the provider, model, compatible endpoint,
token pricing, and handwriting model. The app never accepts or returns the API
key. Follow-up turns reuse the same session and link to the prior action.
Responses show the passages used; source links open the normalized page and
highlighted line range. An extracted course name can be corrected from the
published-course card. Student and tutor messages render inline TeX written as
`$x^2$`, display TeX written as `$$x^2$$`, and code written between backticks.
The tutoring model is instructed to return mathematical expressions using
these delimiters. The tutoring surface expands with the browser window.
Handwritten PNG, JPEG, WebP, or PDF work can be selected from the `+` button or
dragged directly onto the conversation/composer. OCR output remains editable
as LaTeX and has a live rendered preview before confirmation as evidence.

### Use the demo from a phone or tablet

Start the backend on the computer's local-network interface:

```bash
PYTHONPATH=src:research/knowledge-retrieval/retrieval-tool \
  .venv/bin/uvicorn digital_professor.webapp.app:app \
  --host 0.0.0.0 --port 8000
```

On macOS, find the computer's Wi-Fi address with:

```bash
ipconfig getifaddr en0
```

If that returns nothing, try `ipconfig getifaddr en1`. Connect the computer and
mobile device to the same trusted Wi-Fi network, then open
`http://<computer-ip>:8000` in Safari or Chrome. For example, if the command
prints `192.168.1.42`, open `http://192.168.1.42:8000`. Do not expose this
development server directly to the public internet.

Before testing on mobile, confirm that `http://127.0.0.1:8000` works on the
computer. Then, from the mobile device:

1. Upload the syllabus and notes and prepare the course.
2. Start a tutoring session.
3. Select `+`, then **Take a photo** to photograph handwritten work or
   **Choose image or PDF** to select an existing file.
4. Wait for recognition, edit the extracted LaTeX, and inspect the live preview.
5. Select **Confirm and continue** to create Student Evidence and continue the
   tutoring turn.

Drag-and-drop depends on browser and operating-system support and is mainly
intended for desktop and tablet use. On an iPhone, use the camera or file
picker. The layout uses the mobile viewport, horizontal navigation, touch-sized
controls, safe-area spacing, and 16-pixel form fields to avoid iOS input zoom.

Camera availability depends on the device, browser, and its camera permission.
The original image is preserved before recognition, and the student must review
the transcription before it becomes evidence.

If the phone or tablet cannot connect:

- Keep the backend terminal running and verify the IP address has not changed.
- Confirm both devices are on the same non-guest Wi-Fi network.
- Temporarily disconnect VPNs that may prevent local-network access.
- Allow incoming Python/Uvicorn connections if macOS shows a firewall prompt.
- Open `http://<computer-ip>:8000/api/status` on the mobile device to distinguish
  a network problem from a page-rendering problem.

### Provider and model selection

The provider screen supports OpenAI, OpenRouter, DeepSeek, local Ollama, and a
custom OpenAI-compatible endpoint. Each profile supplies its default base URL
and `.env` key-variable name. The UI never accepts or returns the key itself.

1. Put the applicable key in `.env` (`OPENAI_API_KEY`,
   `OPENROUTER_API_KEY`, or `DEEPSEEK_API_KEY`). Ollama does not require one.
2. Select a provider and enter an exact model/version identifier.
3. Select **Test provider and load models**. The backend calls the provider's
   model-list endpoint and populates the model/version suggestions.
4. Select or enter the desired model/version and apply the settings.

The model-list endpoint reports identifiers available to the account, but it
does not guarantee that every listed model supports chat or vision. Handwriting
requires a model and compatible endpoint supporting image input and structured
Responses output. OpenAI documents the model-list behavior in its
[Models API reference](https://developers.openai.com/api/reference/resources/models/methods/list).

Visible progress bars report the current client-side stage for syllabus and
notes upload, course preparation, tutoring turns, provider checks, and
handwriting recognition. Because the current backend operations are synchronous,
intermediate percentages are stage indicators rather than server-streamed
completion measurements.

The browser stores the active session ID in local storage and reloads the
server-side transcript after a page refresh. This survives browser refreshes,
but not a backend restart because the current session repository is in memory.

Operational handoff events and generated Question Schema records are written
only to backend files under `logs/YYYY-MM-DD/<session-id>/`, with timestamped
filenames; they are not displayed or served by the student UI. Turning
diagnostics on additionally records source details, model/timing/token metadata,
configured cost estimates, and explicit issues. Handwritten images or
PDFs can be transcribed by a compatible configured vision model, but the student
must confirm or correct the transcription before it enters the tutoring flow.
The **Activity log** sidebar item reads a bounded session summary from these
backend files: preserved/recognized input, the selected action and policy phase,
output, and sources. It does not expose private model chain-of-thought. Backend
records keep exact typed input and distinguish OCR output from confirmed text.
Office Hours and Assessments remain placeholders.
See [`docs/notes/INTEGRATED_DEMO.md`](docs/notes/INTEGRATED_DEMO.md) for details.

The handwriting unit tests use a deterministic recognizer and do not require a
paid provider. Live handwriting recognition is optional and requires a
compatible provider/model and, when applicable, its server-side key; never
commit a key or an `.env` file.

## Contributing

Read these documents before changing product code:

1. The applicable module specification under [`specs/`](specs/).
2. [`resources/AI_CODING_AGENT_GUIDELINES.md`](resources/AI_CODING_AGENT_GUIDELINES.md).
3. [`resources/PULL_REQUEST_WORKFLOW.md`](resources/PULL_REQUEST_WORKFLOW.md).
4. [`.github/pull_request_template.md`](.github/pull_request_template.md).

### Branching rules

- Do not commit directly to `main`.
- Start from the latest reviewed `main`.
- Use one Jira ticket and one focused purpose per branch.
- Name branches `<initials>/<Jira-ID>_<short-description>`, for example
  `jm/JDP-55_init-implementation`.
- Start commit messages and PR titles with the Jira ID, for example
  `JDP-55: Implement initial integrated tutoring turn`.

```bash
git switch main
git pull --ff-only origin main
git switch -c jm/JDP-55_init-implementation
```

### Pull requests and review

- Use the repository PR template and describe resulting behavior, affected
  interfaces, tests, limitations, and material AI assistance.
- Run relevant automated and manual checks and include their exact results.
- Review the complete diff and run `git diff --check` before requesting review.
- Obtain at least one teammate approval before merging.
- Request review from affected module owners when changing shared schemas,
  architecture, or cross-module interfaces.
- Do not commit credentials, `.env` files, virtual environments, generated
  builds, raw student data, or machine-specific paths.

### AI-assisted coding

AI-generated work is draft work. The contributor remains responsible for its
correctness, security, scope, and maintainability. Contributors must:

- begin with the applicable specification and preserve module ownership;
- keep requests and commits narrow enough for human review;
- understand and review every generated change;
- verify external APIs and dependencies rather than accepting invented ones;
- use synthetic or de-identified data and never expose secrets or student data;
- test meaningful behavior, including validation and structured failures;
- disclose material AI assistance in the PR; and
- never let an agent approve or merge its own work.

Stop and involve the appropriate teammate when specifications conflict, a
shared interface must change, privacy or retention is unclear, or the proposed
implementation moves responsibilities between modules.

## Project status

### Completed

- Established shared architecture, interface, Course Context, Retrieval,
  Student Interaction, and Tutoring Engine specifications.
- Added the Python environment smoke test and contributor workflow.
- Implemented typed `StudentSubmission` and factual `StudentEvidence` records
  with immutable original-input preservation.
- Implemented handwriting upload, recognition provenance, ambiguity review,
  student correction, and confirmation before semantic use.
- Implemented attempt, revision, prior-action, and evidence links.
- Added a read-only Question Schema store backed by the Calculus examples.
- Connected the initial Tutoring Engine to Retrieval V1's local fixture path.
- Added minimal Learner State creation, grounded probe/explain actions, mock
  Delivery, delivery-result recording, and trace events.
- Added executable tests for required shared-record fields and module
  boundaries.
- Added Jira-linked branching, peer-reviewed PRs, and AI-assisted coding rules.
- Added syllabus/notes ingestion, source-linked retrieval, stateful follow-up
  turns, provider validation, configurable diagnostics, and the integrated UI.
- Added the first policy-driven Tutoring Engine machinery: phase, help level,
  action selection, pending Learner State, and delivery-committed state updates.

### Next

The following specification work is not yet implemented in the root product:

- Replace heuristic Course Context extraction and the partial runtime Question
  Schema with the full validation and instructor-review workflow.
- Implement `QuestionStart`, question reopening, idempotency, and the complete
  question/session state lifecycle.
- Replace the deterministic Tutoring Engine slice with the specified decision
  workflow, action cards, help ladders, math checks, reply checks, safe
  fallbacks, and full failure behavior.
- Replace lexical in-memory search with the specified Retrieval tool loop,
  embedding index, evidence check, and citation validator.
- Implement Delivery as a product module, including structured presentation
  failures, retries, accessibility adaptations, and the avatar handoff.
- Add durable course/session/trace storage, retention rules, authentication,
  and authorization. The current state disappears on server restart.
- Complete recorded-voice input. Real-time voice/video interaction remains
  deferred.
- Expand schema validation and compatibility checks for every shared record.
- Add end-to-end Calculus scenarios for correct, partial, incorrect,
  insufficient-evidence, prerequisite-gap, retry, and reassessment states.

### Future considerations

- Model selection, routing, token use, provider cost, latency, and fallback
  behavior.
- Hosting, public deployment, authentication, authorization, and scaling.
- Student privacy, consent, retention, deletion, redaction, and institutional
  review requirements.
- Course-material copyright, instructor controls, provenance, and source
  publication workflows.
- Accessibility across text, handwriting, speech, avatar, and mobile clients.
- Evaluation of recognition quality, grounding, tutoring reliability, answer
  leakage, consistency, learning outcomes, and human-review burden.
- Monitoring, audit trails, incident response, rate limits, and operational
  support.
- Versioning and migration of interfaces, prompts, policies, indexes, and
  Learner State.

See [`docs/CHANGELOG.md`](docs/CHANGELOG.md) for project history.
See [`docs/reports/INTEGRATED_DEMO_TEST_RESULTS.md`](docs/reports/INTEGRATED_DEMO_TEST_RESULTS.md)
for the latest integrated-demo validation and remaining manual provider checks.
