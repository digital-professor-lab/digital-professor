# V1 Testing Plan

## Purpose

This test cycle establishes whether the initial root implementation behaves as
documented before further development begins. It checks the development
environment, shared records, module boundaries, Student Evidence pipelines,
the integrated tutoring turn, and regressions in the merged research
components.

The sequence for this cycle is:

```text
prepare environment -> run tests -> capture evidence -> report results
                     -> review failures and limitations -> decide next work
```

Do not begin additional feature development during this cycle. After testing,
publish the results, failures, warnings, and limitations for team review.

## Scope

### Included

- Repository and Python environment readiness.
- Required shared fields from `specs/interfaces.md`.
- Typed `StudentSubmission` and `StudentEvidence` behavior.
- Handwriting preservation, recognition, ambiguity, and confirmation behavior
  using deterministic test doubles.
- Interaction-to-Engine-to-Delivery coordination and trace events.
- Question Schema loading and course/question identity checks.
- Minimal Learner State creation and publication after delivery.
- Retrieval V1 fixture integration and grounding references.
- Structured failures at implemented boundaries.
- Regression tests for the Interaction, Retrieval, and Course Context research
  components used by the integrated slice.

### Excluded

- Live provider calls or paid handwriting recognition.
- Production databases, vector indexes, or model downloads.
- Real student data.
- Browser usability testing for the research prototype.
- Avatar, production Delivery, voice, video, deployment, load, and security
  testing.
- Tutoring Engine behavior that remains listed under **Next** in the root
  README.

An excluded capability must not be reported as passing. Record it as not yet
implemented or not evaluated.

## Test environment record

Before running tests, record:

| Item | Value |
|---|---|
| Date and time | |
| Tester | |
| Branch | |
| Commit SHA | |
| Operating system | |
| Python version | |
| Dependency installation result | |
| Relevant environment variables | Names only; never record secret values |

Use synthetic fixtures only. Confirm that no API key, `.env` file, raw student
artifact, or machine-specific credential is staged.

## Testing steps

Run every command from the repository root unless the step says otherwise.

### 1. Confirm the working context

```bash
git branch --show-current
git status --short
git rev-parse --short HEAD
python --version
```

Expected behavior:

- The branch is the intended Jira-linked feature branch.
- All visible changes are part of the test candidate.
- Python is version 3.10 or newer.
- No secret, local environment, or unrelated generated file appears.

### 2. Create or refresh the environment

For a clean checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e "research/knowledge-retrieval/retrieval-tool[test]"
```

For an existing environment, activate it and run the two installation commands
again so declared dependencies match the candidate branch.

Expected behavior: every command completes without a dependency-resolution or
installation error.

### 3. Run the environment smoke tests

```bash
PYTHONPATH=src \
  python -m pytest tests/test_environment.py -v
```

Verify:

- Workspace structure is present.
- Every root requirement has a smoke-test mapping.
- Every required distribution is installed and importable.

### 4. Run the shared-contract checks

```bash
PYTHONPATH=src \
  python -m pytest tests/test_spec_contracts.py -v
```

Verify that `StudentSubmission`, `StudentEvidence`, `LearnerState`,
`TutoringAction`, and `DeliveryResult` expose the required fields from
`specs/interfaces.md`. Confirm that Student Evidence does not contain mastery,
misconception, correctness, or diagnosis fields.

### 5. Run typed Student Evidence tests

```bash
PYTHONPATH=src \
  python -m pytest tests/interaction/test_typed_pipeline.py -v
```

Verify:

- Exact typed input is preserved.
- Typed input bypasses recognition.
- Invalid or empty input stops before downstream handoffs.
- Attempts, revisions, parent evidence, and prior actions remain linked.
- Engine, Delivery, and delivery-recording failures are structured and visible.

### 6. Run handwriting Student Evidence tests

```bash
PYTHONPATH=src \
  python -m pytest tests/interaction/test_handwriting_pipeline.py -v
```

Verify:

- Original handwriting bytes remain preserved.
- Recognition output remains separate from the original artifact.
- Meaning-changing ambiguity blocks semantic use until confirmation.
- Corrections append auditable records instead of overwriting recognition.
- Recognition failure does not create fabricated evidence.
- Confirmed handwriting uses the same downstream path as typed evidence.

These tests use a stub recognizer. Do not configure or call a paid provider for
this test cycle.

### 7. Run the integrated tutoring-turn tests

```bash
PYTHONPATH=src:research/knowledge-retrieval/retrieval-tool \
  python -m pytest tests/interaction/test_initial_integration.py -v
```

Verify both implemented paths:

1. A help request selects `explain`, calls the Retrieval fixture, attaches a
   grounding reference, reaches mock Delivery, and publishes Learner State
   after delivery.
2. Submitted mathematical work selects `probe` without an unnecessary
   Retrieval call and completes the same delivery handoff.

### 8. Run the complete root product suite

```bash
PYTHONPATH=src:research/knowledge-retrieval/retrieval-tool \
  python -m pytest tests -q
```

This is the release-level check for the current root implementation. Record the
number passed, failed, skipped, and warned. Do not describe warnings as failures,
but copy and classify warnings that could affect supported Python versions or
future dependency upgrades.

### 9. Run merged-component regression suites

Interaction reference suite:

```bash
PYTHONPATH=research/interaction-methods/src \
  python -m pytest research/interaction-methods/tests -q
```

Retrieval reference suite:

```bash
cd research/knowledge-retrieval/retrieval-tool
PYTHONPATH=. ../../../.venv/bin/python -m unittest discover -s tests
cd ../../..
```

Course Context reference suite:

```bash
cd research/syllabus-understanding/course-context-pipeline
../../../.venv/bin/python -m pytest tests -q
cd ../../..
```

Record expected skips separately. A skip is acceptable only when its reason is
an explicitly optional dependency or external integration.

### 10. Run repository hygiene checks

```bash
git diff --check
git status --short
```

Review the complete diff before reporting results:

```bash
git diff
```

Verify that the candidate contains no secrets, environment files, caches,
generated builds, raw student data, or unrelated changes.

## Acceptance criteria

The current V1 test candidate passes this cycle when:

- Every root product test passes.
- Shared-contract tests pass without changing the specifications during the
  test run.
- Typed and handwritten input remain faithful to the original submission.
- Unconfirmed handwriting cannot reach the Tutoring Engine.
- The integrated help path returns at least one fixture grounding reference.
- Learner State is published only after Delivery reports presentation.
- The no-retrieval path does not call Retrieval unnecessarily.
- Implemented failures return structured results.
- Reference-component regressions show no new failures.
- Every skip and warning is documented and understood.
- `git diff --check` passes and the working tree contains only intended files.

A failed acceptance criterion blocks the candidate from being reported as
ready. It does not automatically justify changing code during this cycle.
First report and classify the failure.

## Failure classification

Classify each failure before recommending work:

| Classification | Meaning | Next decision |
|---|---|---|
| Implementation defect | Code contradicts an agreed specification or expected behavior | Fix in a focused Jira ticket or this ticket if still in scope |
| Contract mismatch | Producer and consumer disagree on a shared record or handoff | Review with affected module owners before editing |
| Environment problem | Installation, Python version, path, or local service issue | Correct setup and rerun the affected step |
| Test defect | Test does not represent the agreed behavior | Review test and specification before changing either |
| Specification gap | Required behavior is missing, contradictory, or still proposed | Record for team agreement; do not invent a permanent contract |
| Deferred capability | Failure concerns work explicitly outside this V1 slice | Record as not implemented; do not count as a regression |

For a failure, preserve the command, error output, affected test, and relevant
specification section. Avoid rerunning repeatedly without recording the first
failure state.

## Results report template

Create the test report before additional development using this structure:

```markdown
# V1 Test Results

## Test candidate

- Branch:
- Commit:
- Tester:
- Date:
- Python / OS:

## Results

| Step | Command or suite | Passed | Failed | Skipped | Warnings | Status |
|---|---|---:|---:|---:|---:|---|
| Environment | | | | | | |
| Shared contracts | | | | | | |
| Typed evidence | | | | | | |
| Handwriting evidence | | | | | | |
| Integrated turn | | | | | | |
| Full root suite | | | | | | |
| Interaction regression | | | | | | |
| Retrieval regression | | | | | | |
| Course Context regression | | | | | | |
| Repository hygiene | | | | | | |

## Failures and warnings

- Identifier:
- Classification:
- Evidence:
- Relevant specification:
- Recommended decision:

## Not evaluated

- List excluded and deferred capabilities.

## Recommendation

- Ready for the next development step, or blocked pending review.
```

## Stop point

After executing the plan, stop and report the results. Do not implement fixes,
expand scope, or start the next specification item until the test report has
been reviewed and the next action is agreed.
