# Project Changelog

This changelog records major project-level changes. It begins with the first V1
implementation work; earlier research artifacts remain available in the Git
history and under `research/`.

## 2026-11-05 — Initial integrated V1 product slice

### Added

- Created the root `src/digital_professor/` product package with separate
  Interaction, Course Context, Retrieval, and Tutoring boundaries.
- Connected typed or confirmed handwritten `StudentEvidence` to a frozen
  Calculus `QuestionSchema`.
- Connected the initial deterministic Tutoring Engine to Retrieval V1's local
  fixture backend.
- Added minimal `LearnerState`, grounded `TutoringAction`, mock Delivery,
  `DeliveryResult` recording, and end-to-end trace events.
- Added root integration tests and executable checks for the shared records in
  `specs/interfaces.md`.

### Current limitations

- Tutoring decisions are limited to deterministic probe/explain behavior.
- Retrieval uses the development fixture rather than a published course index.
- Delivery is mocked, and the research browser prototype is not yet the root
  product client.

## 2026-11-05 — Shared components merged

- Merged the revised Retrieval specification and Retrieval V1 prototype.
- Merged the Course Context Stage A pipeline and its offline tests.
- Added the final V1 Tutoring Engine specification.
- Reconciled component ownership: Interaction captures evidence and coordinates
  handoffs; Retrieval supplies course evidence; the Tutoring Engine interprets
  learner state and chooses actions; Delivery presents approved actions.

## 2026-10-27 — Handwriting interaction V1

- Added handwriting upload and stylus-canvas input to the Interaction research
  prototype.
- Preserved original artifacts separately from recognition output.
- Added ambiguity detection, student confirmation, correction records, and
  routing only after validated evidence is available.
- Added Jira-linked PR conventions, peer review, and a reusable PR template.

## 2026-10-23 to 2026-10-24 — Simple V1 interaction implementation

- Added repository setup instructions, a Python virtual-environment workflow,
  and an environment smoke test.
- Added the shared architecture and interface specifications.
- Implemented the first typed Student Submission and Student Evidence pipeline.
- Added mock Tutoring Engine and Delivery ports to demonstrate one complete
  tutoring handoff without assigning their responsibilities to Interaction.
- Added AI-assisted coding guidelines, `.gitignore`, and draft code-ownership
  practices.
