# V1 Test Results

## Test candidate

| Item | Value |
|---|---|
| Date | 2026-11-05 |
| Tester | Jonathan Ma |
| Branch | `jm/JDP-55_init-implementation` |
| Base commit | `c36cfec` |
| Candidate state | Uncommitted working-tree changes on the base commit |
| Operating system | macOS |
| Python | 3.14.6 |
| Test plan | [`docs/notes/V1_TESTING_PLAN.md`](../notes/V1_TESTING_PLAN.md) |

The base commit does not uniquely identify the tested candidate because the
JDP-55 implementation was uncommitted during this run. The file list and
working-tree status below define the tested candidate until it is committed.

## Results

| Step | Command or suite | Passed | Failed | Skipped | Warnings | Status |
|---|---|---:|---:|---:|---:|---|
| Working context | Branch, status, SHA, and Python checks | — | 0 | 0 | 0 | Pass |
| Environment setup | Root requirements and editable Retrieval test dependencies | — | 0 | 0 | 0 | Pass |
| Environment | `tests/test_environment.py` | 37 | 0 | 0 | 0 | Pass |
| Shared contracts | `tests/test_spec_contracts.py` | 4 | 0 | 0 | 5 | Pass |
| Typed evidence | `tests/interaction/test_typed_pipeline.py` | 10 | 0 | 0 | 5 | Pass |
| Handwriting evidence | `tests/interaction/test_handwriting_pipeline.py` | 6 | 0 | 0 | 5 | Pass |
| Integrated turn | `tests/interaction/test_initial_integration.py` | 2 | 0 | 0 | 5 | Pass |
| Full root suite | `python -m pytest tests -q` | 59 | 0 | 0 | 5 | Pass |
| Interaction regression | `research/interaction-methods/tests` | 18 | 0 | 0 | 6 | Pass |
| Retrieval regression | `unittest discover -s tests` | 100 | 0 | 26 | 0 | Pass |
| Course Context regression | `course-context-pipeline/tests` | 28 | 0 | 0 | 0 | Pass |
| Repository hygiene | `git diff --check`, status, and file review | — | 0 | 0 | 0 | Pass |

Counts from targeted suites overlap with the full root suite and must not be
summed as a count of unique tests.

## Behaviors verified

- The development environment contains every declared root dependency and each
  dependency is importable.
- Shared `StudentSubmission`, `StudentEvidence`, `LearnerState`,
  `TutoringAction`, and `DeliveryResult` records expose the required fields.
- Student Evidence remains factual and contains no mastery, misconception,
  correctness, or diagnosis fields.
- Typed input is preserved exactly and bypasses recognition.
- Invalid typed input stops before Engine or Delivery handoffs.
- Attempts, revisions, parent evidence, and prior actions remain linked.
- Original handwriting is preserved separately from recognition output.
- Meaning-changing handwriting ambiguity blocks downstream use until the
  student confirms or corrects it.
- Recognition failures create no fabricated Student Evidence.
- A help request produces a grounded `explain` action through the Retrieval
  fixture.
- Submitted mathematical work produces a `probe` without an unnecessary
  Retrieval call.
- Learner State is published only after mock Delivery reports presentation.
- Engine, Delivery, and delivery-result recording failures are structured.
- Existing Interaction, Retrieval, and Course Context suites show no new
  failures.

## Warnings and skips

### W1 — PyMuPDF/SWIG deprecation warnings

| Field | Value |
|---|---|
| Classification | Environment/dependency compatibility |
| Affected runs | Shared contracts, typed evidence, handwriting evidence, integrated turn, full root suite, and Interaction regression |
| Evidence | Python 3.14 reports missing `__module__` attributes for `SwigPyPacked`, `SwigPyObject`, and `swigvarlink` |
| Current impact | No failed behavior or test |
| Recommendation | Track for future PyMuPDF/Python dependency upgrades; do not block this candidate |

### W2 — Starlette `BlockingPortal` deprecation warning

| Field | Value |
|---|---|
| Classification | Environment/dependency compatibility |
| Affected run | Interaction research regression |
| Evidence | Starlette's test client uses a deprecated AnyIO alias |
| Current impact | No failed behavior or test |
| Recommendation | Track with future FastAPI/Starlette dependency maintenance; do not block this candidate |

### S1 — Retrieval optional-integration skips

| Field | Value |
|---|---|
| Classification | Expected optional integration |
| Count | 26 |
| Reason | External Week 3/PostgreSQL/vector dependencies were not enabled for the local fixture run |
| Current impact | The dependency-free Retrieval path passed; production external integration was not evaluated |
| Recommendation | Retain as an explicit limitation and run the external suite before production Retrieval is claimed ready |

## Repository hygiene

`git diff --check` produced no output. The working tree contained only the
expected JDP-55 candidate files:

- Root README and dependency/smoke-test updates.
- `docs/CHANGELOG.md` and the V1 testing plan.
- The new `src/digital_professor/` product package.
- Root Interaction, integration, and shared-contract tests.

No `.env` file, API key, credential, cache, generated frontend build, raw
student artifact, or unrelated file was identified in `git status --short`.

## Not evaluated

- Live or paid handwriting recognition.
- Production Retrieval with PostgreSQL, vector encoders, and published course
  indexes.
- Full Tutoring Engine policy, symbolic math checking, help ladders, reply
  guards, and all action cards.
- Production Delivery, accessibility adaptations, retries, avatar behavior,
  and real-time interaction.
- Root product API and browser client.
- Voice and video interaction.
- Durable persistence, authentication, authorization, privacy/retention, load,
  deployment, and security behavior.
- Learning outcomes or independent mathematical review.

These items are unimplemented or outside this test cycle. They are not passing
or failing results.

## Recommendation

The implemented JDP-55 V1 slice meets this test cycle's acceptance criteria:
all root tests and merged-component regressions passed, expected skips and
warnings are understood, and repository hygiene checks passed.

The candidate is ready for human diff review, commit, and pull-request review.
Further feature development should remain paused until the team reviews this
report and agrees on the next specification item.
