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

The current integrated turn is:

```text
StudentSubmission -> StudentEvidence ----\
                                       Tutoring Engine <-> Retrieval
QuestionSchema ------------------------/       |
                                                v
                                      TutoringAction -> mock Delivery
                                             ^               |
                                             \-- DeliveryResult
```

The root package is divided by specification ownership:

| Package | Current responsibility |
|---|---|
| `interaction` | Preserve typed or handwritten input, handle recognition and confirmation, construct factual `StudentEvidence`, coordinate handoffs, and record trace events. |
| `course_context` | Provide a read-only view of a frozen `QuestionSchema` and its course concepts. |
| `retrieval` | Adapt the product contracts to Retrieval V1 and return grounded passage references without choosing pedagogy. |
| `tutoring` | Construct a minimal `LearnerState`, select a deterministic probe or grounded explanation, produce `TutoringAction`, and publish state after confirmed delivery. |

Delivery is mocked in the current slice. The integrated Retrieval test uses the
dependency-free fixture backend, so it requires no API key, model download, or
database.

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

### Run the local V1 interface

The browser shell exposes the tested typed tutoring turn and shows disabled,
status-labeled placeholders for planned course setup, handwriting, voice,
assessment, provider settings, and avatar delivery features.

```bash
PYTHONPATH=src:research/knowledge-retrieval/retrieval-tool \
  uvicorn digital_professor.webapp.app:app --reload
```

Open <http://127.0.0.1:8000>. The demo uses the frozen Calculus I Question
Schema and the local Retrieval fixture, so typed turns require no provider key.
The interface is an integration shell rather than a production client; disabled
controls intentionally mark functionality that is not implemented yet.

The handwriting unit tests use a deterministic recognizer and do not require a
paid provider. Live handwriting recognition is optional and requires an
approved provider key; never commit that key or an `.env` file.

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

### Next

The following specification work is not yet implemented in the root product:

- Promote course ingestion, validation, runtime Question Schema creation, and
  versioned course publication into product modules.
- Implement `QuestionStart`, question reopening, idempotency, and the complete
  question/session state lifecycle.
- Replace the deterministic Tutoring Engine slice with the specified decision
  workflow, action cards, help ladders, math checks, reply checks, safe
  fallbacks, and full failure behavior.
- Replace fixture retrieval with versioned ingested sources, production search,
  citation resolution, and page/line/highlight links.
- Implement Delivery as a product module, including structured presentation
  failures, retries, accessibility adaptations, and the avatar handoff.
- Add durable state and trace storage, logging configuration, retention rules,
  and diagnostic logging controls.
- Add the root product API and browser client; the current web application is a
  local integration shell and is not yet a production client.
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
