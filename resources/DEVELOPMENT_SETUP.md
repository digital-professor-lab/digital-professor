# Development Environment and Shared Specifications Setup

This guide prepares a contributor's local Python environment and copies the
shared specifications into that contributor's V1 branch.

Run all commands from the repository root unless a step says otherwise.

## 1. Prerequisites

Install the following before starting:

- Git
- Python 3.10 or newer
- A local clone of the Digital Professor repository

Verify the installations:

```bash
git --version
python3 --version
```

On Windows, `python` or `py` may be used instead of `python3`.

## 2. Enter the repository

```bash
cd path/to/digital-professor
git status
```

Make sure the command is running in the repository root, where
`requirements.txt` is located.

## 3. Create a virtual environment

Create one project-local environment named `.venv`:

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Windows Command Prompt

```bat
py -m venv .venv
.venv\Scripts\activate.bat
```

After activation, the shell prompt should normally begin with `(.venv)`.
Confirm that the environment's interpreter is active:

```bash
python --version
python -m pip --version
```

The displayed `pip` path should point inside the repository's `.venv`
directory.

## 4. Install project dependencies

Upgrade the environment's package installer and install the packages declared
in the root `requirements.txt`:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Check for incompatible or missing dependencies:

```bash
python -m pip check
```

Run the environment smoke test from the repository root:

```bash
python -m pytest tests/test_environment.py
```

The smoke test checks the supported Python version, all direct dependencies in
`requirements.txt`, their expected import names, and the minimum project
directory structure. Installation errors, import errors, or dependency
conflicts must be resolved before development.

Deactivate the environment when finished:

```bash
deactivate
```

Reactivate the same environment in later terminal sessions instead of creating
a new one.

## 5. Switch to a contributor V1 branch

Each contributor should work on a branch named `v1-<contributor>`, such as
`v1-jonathanma`. Replace `v1-yourname` below with the real branch name; do not
type the angle brackets literally.

If the branch already exists locally:

```bash
git switch v1-yourname
```

If it exists on GitHub but not locally:

```bash
git fetch origin
git switch --track origin/v1-yourname
```

If it does not exist yet, create it from the latest `main`:

```bash
git switch main
git pull --ff-only origin main
git switch -c v1-yourname
git push -u origin v1-yourname
```

Before importing shared files, confirm the correct branch and a clean working
tree:

```bash
git branch --show-current
git status
```

Commit or intentionally stash unrelated work before continuing.

## 6. Copy `specs/` from the integration branch

The repository's shared specification branch is named **`integration-spec`**
(singular). Copy only its `specs/` directory rather than merging the entire
branch.

First, update the remote branch references:

```bash
git fetch origin
```

While still on `v1-yourname`, copy the directory from the remote integration
branch:

```bash
git restore --source origin/integration-spec -- specs/
```

This updates the working tree on the contributor branch. It does not switch to
or merge `integration-spec`.

Review the imported files:

```bash
git status --short
git diff -- specs/
```

For newly added files, `git diff` may not display their contents until they are
staged. Review the directory directly and then stage it:

```bash
git add specs/
git diff --cached -- specs/
```

Commit and push the specifications after review:

```bash
git commit -m "Add shared integration specifications"
git push
```

## 7. Updating the specifications later

When the team updates `integration-spec`, repeat the selective import from the
contributor branch:

```bash
git switch v1-yourname
git status
git fetch origin
git restore --source origin/integration-spec -- specs/
git diff -- specs/
```

Review the changes before staging and committing them. Do not merge the entire
integration branch merely to refresh `specs/`, because that may bring unrelated
research files and history into the V1 implementation branch.

## 8. Final readiness check

Before beginning implementation, verify:

- The active Git branch is the intended `v1-<contributor>` branch.
- `git status` contains only intentional changes.
- The `.venv` environment activates successfully.
- `python -m pip check` reports no broken requirements.
- The latest reviewed `specs/` directory is committed on the contributor
  branch.
- No API keys, `.env` files, credentials, or local virtual-environment files
  are staged for commit.
