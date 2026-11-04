# Pull Request Workflow

GitHub's `main` ruleset requires at least one approving review. GitHub and Jira
are connected, so branches, commits, and pull requests should carry the Jira
ticket ID.

## Core rules

- Do not commit directly to `main`.
- Use one Jira ticket and one focused purpose per branch and pull request.
- Obtain approval from at least one teammate before merging.
- Do not make one contributor the required reviewer for every change.
- Ask affected module owners to review architecture, shared schema, and shared
  interface changes.
- Report relevant local tests in the pull request. Required CI checks are
  deferred for now.
- Never commit API keys, `.env`, credentials, virtual environments, generated
  build files, or unapproved student data.
- Treat AI-generated code as draft code until a contributor reads and tests it.

## Naming conventions

Use this branch format:

```text
<contributor-initials>/<Jira-ID>_<short-description>
```

Use lowercase initials, the uppercase Jira ID, an underscore after the ticket,
and hyphens within the description:

```text
jm/JDP-47_integrate-handwriting-recognition
ss/JDP-52_add-retrieval-contract
oe/JDP-55_parse-course-context
yl/JDP-58_add-delivery-status
```

Start commit messages and PR titles with the Jira ID:

```text
JDP-47: Integrate handwriting recognition
```

Existing `v1-*` branches may finish their current work. Use the Jira-linked
format for new focused tasks.

## Start and publish a branch

Start independent work from the latest reviewed `main`:

```bash
git status
git switch main
git pull --ff-only origin main
git switch -c jm/JDP-47_integrate-handwriting-recognition
```

If the work depends on an unmerged branch, identify that dependency in the PR
and deliberately select the appropriate base branch.

Review and stage only intentional changes:

```bash
git status --short
git diff
git add path/to/file1 path/to/file2
git diff --cached
git commit -m "JDP-47: Integrate handwriting recognition"
git push -u origin jm/JDP-47_integrate-handwriting-recognition
```

## Pull request contents

The template at `.github/pull_request_template.md` asks the author to record:

- the Jira ticket and resulting behavior;
- affected modules, records, APIs, and specifications;
- automated tests and manual checks run locally;
- known limitations, risks, and reviewer questions; and
- material AI assistance and how a human verified it.

Use a draft PR for early feedback. Mark it ready only when the behavior is
reviewable and the local validation is recorded.

## Review expectations

Every PR requires at least one teammate's approval. A reviewer should verify:

- the implementation matches the ticket and stated behavior;
- module ownership and boundaries remain clear;
- shared records and handoffs remain compatible;
- failure behavior is visible and structured;
- the reported tests meaningfully cover the change; and
- no secrets, local paths, or unintended generated files are included.

Any teammate may review a routine module change. Changes to `specs/`, overall
architecture, shared interfaces, or cross-module records should also be
reviewed by the teammates who produce or consume the affected interface.
Jonathan may help review major architecture and shared-interface changes, but
is not a required reviewer for every PR.

Address blocking comments before merging. Re-run relevant local tests after
material review changes and update the PR's Testing section. Required CI checks
can be added later when the project structure and test commands stabilize.

## AI-assisted changes

The author remains responsible for AI-assisted code and documentation. Before
requesting review:

- read the complete diff;
- verify the change against the ticket and applicable specification;
- check for secrets, unsafe file handling, invented APIs, and unnecessary
  dependencies;
- run the relevant tests and manual checks; and
- disclose material AI assistance in the PR template.

An AI tool must not approve or merge its own changes or bypass the repository
ruleset.

## Merge checklist

- [ ] The PR has one Jira-linked purpose.
- [ ] The title, branch, and commits contain the Jira ID.
- [ ] The author reviewed the complete diff.
- [ ] Relevant local tests and manual checks are reported.
- [ ] Shared interface changes are documented and reviewed by affected owners.
- [ ] Material AI assistance is disclosed and human-reviewed.
- [ ] At least one teammate approved the PR.
- [ ] Blocking conversations are resolved.
- [ ] No secrets or local-only files are included.
