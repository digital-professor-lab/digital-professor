# Pull Request Workflow

This document defines the implementation-phase pull request workflow for the
Digital Professor repository. It assumes `CODEOWNERS` will be configured so
GitHub can automatically request the appropriate module reviewers.

## 1. Core rules

- Do not commit directly to `main`.
- Develop on a contributor or task branch.
- Keep each pull request focused on one feature, fix, specification update, or
  infrastructure change.
- Require at least one human reviewer before merging.
- Require approval from the applicable code owner after `CODEOWNERS` is
  enabled.
- Run the relevant checks before requesting final review.
- Never commit API keys, `.env`, credentials, local virtual environments, or
  generated secrets.
- Treat AI-generated code as untrusted draft code until a developer has read,
  tested, and accepted it.

## 2. Branch naming

Longer-lived contributor branches may use:

```text
v1-<contributor>
```

Examples:

```text
v1-jonathanma
v1-seansong
```

Focused branches created from a contributor branch or `main` should describe
the work:

```text
<contributor>/<type>-<short-description>
```

Examples:

```text
jonathan/feature-student-submission
jonathan/fix-evidence-validation
sean/feature-retrieval-interface
ovunc/update-question-schema
```

Recommended types include `feature`, `fix`, `test`, `docs`, and `refactor`.

## 3. Start from the correct base

Use `main` when the work should contain only code already accepted by the
team. Use a contributor V1 branch when the change depends on unmerged work from
that branch.

Before starting:

```bash
git status
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c yourname/feature-short-description
```

If working directly on an existing contributor branch:

```bash
git switch v1-yourname
git pull --ff-only
```

The working tree should be clean before switching branches or importing work.

## 4. Implement in reviewable increments

During implementation:

1. Follow the applicable files in `specs/`.
2. Keep module ownership boundaries intact.
3. Add or update tests that verify meaningful behavior.
4. Run relevant checks after each material change.
5. Review the diff before committing.

Useful commands:

```bash
git status --short
git diff
python -m pytest
git diff --check
```

Stage only intentional files:

```bash
git add path/to/file1 path/to/file2
git diff --cached
```

Create a concise commit:

```bash
git commit -m "Implement typed student submission records"
```

Prefer several coherent commits over one large, mixed commit. Avoid commits
that combine unrelated formatting, generated files, documentation, and feature
logic.

## 5. Review AI-assisted changes locally

Before pushing code produced or substantially modified by a coding agent:

- Read the complete diff.
- Confirm the code matches the relevant specification.
- Check that the agent did not broaden the requested scope.
- Check for hard-coded credentials, local paths, unsafe file handling, or
  unnecessary dependencies.
- Confirm errors and external-service failures return structured results.
- Run the relevant tests yourself.
- Remove generated artifacts and debugging output that do not belong in the
  repository.

The contributor who submits the pull request remains responsible for the code,
regardless of which tools helped create it.

## 6. Push the branch

For the first push:

```bash
git push -u origin yourname/feature-short-description
```

For later updates:

```bash
git push
```

Do not force-push a shared branch without coordinating with every contributor
using it. If rewriting your own PR branch is necessary, prefer:

```bash
git push --force-with-lease
```

`--force-with-lease` must still be used carefully because it rewrites remote
history.

## 7. Open the pull request

Open the pull request against `main` unless the team has intentionally chosen
another integration base.

Use a draft pull request when:

- The implementation is incomplete.
- An interface decision is still unresolved.
- Early feedback is needed before tests or documentation are finished.

Mark it ready for review only when the change is complete enough to merge.

### Required pull request description

Include:

1. **Problem:** What concrete behavior or gap does this change address?
2. **Result:** What happens after this change?
3. **Scope:** Which module and shared records are affected?
4. **Interfaces:** Did any input, output, schema, status, or ownership contract
   change?
5. **Validation:** Which tests or manual checks were run, with their results?
6. **AI assistance:** Identify substantial AI-generated or AI-modified code and
   explain how it was reviewed.
7. **Remaining limitations:** List known limitations relevant to the change.

Example:

```markdown
## Problem

Typed student responses do not yet produce shared interaction records.

## Result

The Interaction module preserves the original text and constructs validated
StudentSubmission and StudentEvidence records.

## Interfaces

- Implements StudentSubmission and StudentEvidence from specs/interfaces.md.
- Does not change the Tutoring Engine or Delivery contracts.

## Validation

- `python -m pytest tests/interaction`
- `git diff --check`

## AI assistance

An AI coding agent drafted the model validation functions. I reviewed the full
diff and added tests for missing IDs, unchanged original text, and invalid
evidence links.

## Limitations

Only typed input is supported in this iteration.
```

## 8. Automated and CODEOWNERS review

After `CODEOWNERS` is configured, GitHub should automatically request review
from the owner of each affected module or shared interface.

A pull request should not merge until:

- Required automated checks pass.
- At least one human reviewer approves it.
- Required code-owner approvals are present.
- All blocking review conversations are resolved.
- The branch is current enough with `main` to merge cleanly.

Changes to `specs/`, shared schemas, module boundaries, or common interfaces
should receive review from every affected module owner, even if GitHub requests
only one reviewer automatically.

## 9. Respond to review

For each requested change:

1. Decide whether code, tests, documentation, or the specification should
   change.
2. Make the smallest complete correction.
3. Run the relevant checks again.
4. Push the update.
5. Reply with what changed and where.

Do not resolve a review conversation until the issue is addressed or the
reviewer agrees that no change is required.

If a review changes an interface, update the corresponding specification and
request review from affected module owners.

## 10. Update a branch with `main`

Do not merge with main.

## 11. Merge and clean up

Use **squash and merge** by default for focused feature pull requests. The
squashed commit message should describe the final behavior rather than the
development process.

After merging:

```bash
git switch main
git pull --ff-only origin main
git branch -d yourname/feature-short-description
```

Delete the remote feature branch through GitHub or with:

```bash
git push origin --delete yourname/feature-short-description
```

Keep longer-lived `v1-<contributor>` branches only while the team still needs
them. Regularly refresh them from `main` and avoid treating them as substitutes
for reviewed pull requests.

## 12. Merge checklist

Before merging, confirm:

- [ ] The pull request has one clear purpose.
- [ ] The full diff has been reviewed by the contributor.
- [ ] The implementation follows the current specifications.
- [ ] Shared interface changes are explicitly documented.
- [ ] Tests and required automated checks pass.
- [ ] No credentials or local-only files are included.
- [ ] AI-assisted changes are disclosed and human-reviewed.
- [ ] Required human and code-owner approvals are present.
- [ ] Blocking review conversations are resolved.
- [ ] The final title and description match the implemented behavior.
