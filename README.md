# Digital Professor

Digital Professor project for Fall 2026.

## Jonathan's V1 responsibility

The first implementation iteration focuses on the **Student Interaction and
Evidence pipeline**. The initial path accepts typed student input, preserves
the original submission, constructs shared records, validates them, and passes
validated `StudentEvidence` to the Tutoring Engine interface.

The first end-to-end implementation may use mock Tutoring Engine and Delivery
components. This allows the team to verify the Interaction contracts and one
complete tutoring turn before integrating the other production modules.

### Initial V1 scope

V1 includes:

- Typed text input, including typed mathematical notation.
- Preservation of the student's original submission.
- Construction and validation of a `StudentSubmission` record.
- Construction and validation of factual `StudentEvidence`.
- Delivery of validated evidence to the Tutoring Engine interface.
- Receipt of a structured `TutoringAction`.
- Forwarding that action to the Delivery interface without changing its
  pedagogical meaning.
- Recording handoff status for the tutoring turn.

The pipeline should follow `specs/student-interaction.md` and the shared record
definitions in `specs/interfaces.md` after those specifications are brought
into this branch.

### Minimum tutoring-turn flow

```text
Typed student input
        |
        v
Preserve original submission
        |
        v
Construct and validate StudentSubmission
        |
        v
Construct and validate StudentEvidence
        |
        v
Tutoring Engine interface (mock initially)
        |
        v
Structured TutoringAction
        |
        v
Delivery interface (mock initially)
        |
        v
Record delivery and handoff status
```

The Interaction module records observable student work. It does not determine
whether the work is correct, diagnose the learner, or select the tutoring
action.

## Implementation order

### 1. Confirm Python readiness

- [x] Confirm every active developer can run the supported Python version
  locally.
- [x] Confirm each developer can create and activate the project environment.
- [x] Confirm dependencies install successfully.
- [x] Add and run a basic project test or smoke check.
- [x] Record setup instructions so Python does not become an integration
  blocker.

### 2. Set up GitHub review and AI coding guidelines

- [x] Establish a lightweight branch and pull-request workflow.
- [ ] Add `CODEOWNERS` for components that require designated review. (requries Ran)
- [ ] Configure branch protection or a repository ruleset for `main` where
  appropriate.
- [ ] Require human review before AI-assisted changes enter `main`.
- [ ] Document practical coding-agent guidelines, including reviewing generated
  changes, running tests, avoiding secrets, and keeping commits scoped.

### 3. Implement the typed submission and evidence pipeline

- [x] Accept typed student input.
- [x] Preserve the original input before transformation or validation.
- [x] Construct a `StudentSubmission` using the shared interface.
- [x] Validate required identifiers, input type, links, and record version.
- [x] Construct factual `StudentEvidence` without correctness, mastery, or
  misconception labels.
- [x] Validate the evidence before releasing it downstream.
- [x] Add focused tests for record preservation, construction, validation, and
  invalid inputs.

### 4. Implement basic tutoring-turn coordination

- [x] Send validated `StudentEvidence` to the Tutoring Engine interface.
- [x] Use a mock Tutoring Engine that returns a structured `TutoringAction`.
- [x] Forward the action unchanged to a mock Delivery interface.
- [x] Record success, structured failure, and handoff status.
- [x] Link the student's next submission to the action and prior attempt.
- [x] Demonstrate one complete typed tutoring turn.

### 5. Integrate handwriting recognition

After the typed path is stable:

- [ ] Reuse the existing handwriting-recognition experiments.
- [ ] Integrate one handwriting-recognition path into the same evidence
  pipeline.
- [ ] Preserve the original image or PDF separately from derived images and
  recognized content.
- [ ] Surface recognition uncertainty that could change mathematical meaning.
- [ ] Require confirmation before meaning-changing recognition corrections are
  treated as confirmed evidence.
- [ ] Reuse the same `StudentEvidence` validation and downstream handoff.

## Deferred work

- **Voice input:** add recorded voice after typed and handwritten paths are
  stable.
- **Real-time interaction:** defer continuous voice, interruption handling, and
  other real-time behavior until the basic tutoring loop is reliable.
- **Reasoning verification:** keep this outside the first coding iteration. It
  may be computationally expensive, and the team still needs to decide whether
  it belongs in the Tutoring Engine, the evidence pipeline, or a separate
  verification layer.

## V1 completion criterion

The first coding iteration is complete when a typed student response can move
through the full pipeline without losing or silently changing the original
work, produce schema-valid `StudentSubmission` and `StudentEvidence` records,
receive a structured action from the mock engine, pass it to mock delivery, and
record the complete handoff status.
