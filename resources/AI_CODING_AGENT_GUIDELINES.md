# AI-Assisted Coding Guidelines

These guidelines apply to code, tests, documentation, configuration, and
specifications created or modified with coding agents, chat assistants, code
completion tools, or other generative AI systems.

AI assistance can accelerate implementation, but the contributor who submits
the work remains responsible for its correctness, security, scope, and
maintainability.

## 1. Human responsibility

- A human contributor must understand and approve every submitted change.
- AI-generated output is a draft, not evidence that the implementation is
  correct.
- Do not submit code that the contributor cannot explain during review.
- Do not allow an agent to approve or merge its own work.
- A human reviewer must assess AI-assisted changes before they enter `main`.

## 2. Start from the specification

Before asking an agent to implement a component:

1. Identify the relevant module specification in `specs/`.
2. State the component's responsibilities and explicit non-responsibilities.
3. Identify the shared input, output, status, and error records.
4. Define the smallest behavior that completes the task.
5. Identify the tests or observable acceptance criteria.

If the specification is incomplete or contradictory, record the issue for team
discussion. Do not let the agent silently invent a permanent interface or move
responsibilities between modules.

## 3. Keep requests narrow and reviewable

Prefer focused requests such as:

- Implement validation for one shared record.
- Add one mock interface.
- Handle one documented failure condition.
- Add tests for one expected behavior.

Avoid asking an agent to redesign the entire architecture, refactor unrelated
files, or implement several modules in one change. Separate unrelated work into
different commits or pull requests.

## 4. Protect secrets and student data

Never provide an AI tool with:

- API keys, tokens, passwords, or private credentials.
- `.env` contents.
- Private student records or identifiable educational data.
- Private repository content unless the tool and account are approved for it.
- Raw logs containing secrets, personal information, or restricted content.

Use synthetic or de-identified examples. Store credentials only through the
approved environment or secret-management mechanism. Before committing, check
that `.env`, local credentials, artifacts, and raw student files are not staged.

## 5. Preserve module boundaries

Agent-generated code must follow the ownership defined in the specifications.
For example:

- Interaction may capture, recognize, confirm, validate, and route student
  evidence.
- Interaction must not diagnose mastery or silently correct mathematical work.
- Retrieval owns passage retrieval and ranking.
- The Tutoring Engine owns learner interpretation and action selection.
- Delivery owns presentation and avatar behavior.

When a change affects another module's contract, stop and request review from
that module's owner instead of hiding the dependency inside local code.

## 6. Review every generated diff

Before committing AI-assisted work:

```bash
git status --short
git diff
git diff --check
```

Review for:

- Unrequested files or broadened scope.
- Changed interfaces, defaults, or behavior.
- Hard-coded secrets, usernames, machine paths, or environment assumptions.
- Fabricated APIs, packages, functions, citations, or configuration options.
- Missing validation and structured error handling.
- Silent fallback behavior that could hide a failure.
- Duplicate logic that belongs to another module.
- Unnecessary dependencies.
- Debug output, generated artifacts, and commented-out code.
- Tests that merely reproduce the implementation rather than verify behavior.

Read the complete affected functions and surrounding code, not only the lines
highlighted by the diff.

## 7. Validate dependencies and external APIs

- Prefer dependencies already approved in `requirements.txt`.
- Require a clear reason before adding a new dependency.
- Verify package names and APIs against primary documentation.
- Pin or constrain versions when reproducibility requires it.
- Never assume an API model, endpoint, field, price, or rate limit remains
  unchanged.
- Mock external services in unit tests unless an explicit integration test is
  being run.

Any new dependency must be included in the environment smoke test or its
documented replacement.

## 8. Test meaningful behavior

Run the tests relevant to the change and include the commands and results in
the pull request. At minimum:

```bash
python -m pytest
git diff --check
```

Tests should cover applicable behavior such as:

- Required fields and schema validation.
- Preservation of original student work.
- Separation of raw, corrected, and confirmed values.
- Module input and output contracts.
- Structured failure and timeout behavior.
- Attempt and revision links.
- Mock external-service failures.
- Prevention of responsibilities leaking between modules.

Do not weaken, delete, or skip a failing test merely to make generated code
pass. Determine whether the implementation, test, or specification is wrong.

## 9. Use safe agent permissions

Give a coding agent only the access needed for the task.

- Prefer read-only access while investigating.
- Review filesystem and shell commands before allowing broad changes.
- Do not authorize automatic deployment, merging, publication, or external
  messaging unless that action is explicitly intended and reviewed.
- Do not allow destructive Git operations on shared work without a backup and
  explicit human approval.
- Check the working tree before and after an agent runs.

An agent should not bypass repository rules, approval requirements, or failing
checks.

## 10. Commit and pull request practices

- Keep AI-assisted changes in focused commits.
- Use commit messages that describe the implemented behavior.
- Disclose substantial AI assistance in the pull request.
- Identify which files or functions were generated or substantially modified.
- Explain how the contributor reviewed and tested the result.
- List known limitations and unresolved interface questions.

Suggested pull request disclosure:

```markdown
## AI assistance

A coding agent drafted the StudentEvidence validation functions and related
tests. I reviewed the full diff, checked it against `specs/interfaces.md`, and
ran the tests listed below. I manually verified preservation of original input,
required identifiers, revision links, and invalid-record behavior.
```

Minor completion assistance does not require a line-by-line inventory, but the
pull request must disclose AI involvement when it materially shaped the design
or implementation.

## 11. Documentation and traceability

When an AI-assisted change affects a shared record or handoff:

- Update the applicable specification or explicitly state why no spec change
  is needed.
- Preserve schema and record version information.
- Record the producer and consumer of each interface.
- Document structured statuses and failure behavior.
- Keep logs free of secrets and unnecessary student content.
- Record model or provider versions when model behavior affects the result.

Generated comments and documentation must describe actual behavior. Remove
claims that cannot be verified from the implementation or specification.

## 12. Stop and ask for review when

Pause implementation and involve the appropriate teammate or supervisor when:

- Two specifications conflict.
- A shared schema or interface must change.
- Module ownership is unclear.
- The change would expose private data to a new service.
- The agent proposes a new dependency or external platform.
- Security, authorization, retention, or logging behavior is uncertain.
- A generated solution bypasses a failing check or required human review.
- The contributor cannot explain why the generated code is correct.

## 13. Contributor checklist

Before opening a pull request containing AI-assisted changes, confirm:

- [ ] The task and affected specification were identified.
- [ ] The change stays within the owning module's responsibilities.
- [ ] No secrets or identifiable student data were supplied or committed.
- [ ] The complete diff was reviewed by a human.
- [ ] External APIs and dependency names were verified.
- [ ] Relevant tests pass.
- [ ] Failures return structured, visible results.
- [ ] Generated artifacts and debugging files were removed.
- [ ] Material AI assistance is disclosed in the pull request.
- [ ] A human and the applicable code owner will review the change.

