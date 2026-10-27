"""Smoke tests for a contributor's local development environment."""

from __future__ import annotations

import importlib.util
import re
import sys
from importlib import metadata
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"

# Distribution names from requirements.txt do not always match their Python
# import names. Keep the mapping explicit so the smoke test verifies that the
# installed dependency is usable by project code, not merely present in pip's
# package metadata.
IMPORT_NAMES = {
    "requests": "requests",
    "python-dotenv": "dotenv",
    "tenacity": "tenacity",
    "pandas": "pandas",
    "numpy": "numpy",
    "matplotlib": "matplotlib",
    "jupyter": "jupyter_core",
    "ipykernel": "ipykernel",
    "pypdf": "pypdf",
    "python-docx": "docx",
    "openai": "openai",
    "anthropic": "anthropic",
    "huggingface-hub": "huggingface_hub",
    "pytest": "pytest",
    "responses": "responses",
}


def _normalize_distribution_name(name: str) -> str:
    """Return the normalized form used to compare Python distributions."""

    return re.sub(r"[-_.]+", "-", name).lower()


def _declared_requirements() -> list[str]:
    """Read direct distribution names from the root requirements file."""

    requirements: list[str] = []
    for raw_line in REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", maxsplit=1)[0].strip()
        if not line:
            continue

        # The current file contains simple package declarations. Splitting on
        # common version/marker syntax keeps this helper usable when pins are
        # added later.
        distribution = re.split(r"[<>=!~;\[]", line, maxsplit=1)[0].strip()
        requirements.append(_normalize_distribution_name(distribution))

    return requirements


def test_supported_python_version() -> None:
    """The development baseline is Python 3.10 or newer."""

    assert sys.version_info >= (3, 10), (
        "Digital Professor requires Python 3.10 or newer; "
        f"found {sys.version.split()[0]}."
    )


def test_minimum_workspace_structure() -> None:
    """The checkout contains the files and directories needed to develop."""

    required_paths = (
        PROJECT_ROOT / "README.md",
        REQUIREMENTS_FILE,
        PROJECT_ROOT / "src",
        PROJECT_ROOT / "resources",
        PROJECT_ROOT / "tests",
    )
    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required_paths if not path.exists()]

    assert not missing, "Workspace is missing required paths: " + ", ".join(missing)


def test_all_requirements_have_smoke_test_mappings() -> None:
    """New direct dependencies must be included in the import smoke check."""

    declared = set(_declared_requirements())
    mapped = set(IMPORT_NAMES)

    assert declared == mapped, (
        "requirements.txt and the smoke-test import mapping differ. "
        f"Missing mappings: {sorted(declared - mapped)}; "
        f"stale mappings: {sorted(mapped - declared)}."
    )


@pytest.mark.parametrize("distribution_name", sorted(IMPORT_NAMES))
def test_required_distribution_is_installed(distribution_name: str) -> None:
    """Every direct requirement is installed in the active environment."""

    try:
        metadata.version(distribution_name)
    except metadata.PackageNotFoundError:
        pytest.fail(
            f"Missing dependency '{distribution_name}'. Run "
            "`python -m pip install -r requirements.txt` from the repository root."
        )


@pytest.mark.parametrize("distribution_name", sorted(IMPORT_NAMES))
def test_required_module_is_importable(distribution_name: str) -> None:
    """Every installed requirement exposes the module expected by the code."""

    module_name = IMPORT_NAMES[distribution_name]
    assert importlib.util.find_spec(module_name) is not None, (
        f"Dependency '{distribution_name}' is installed but module "
        f"'{module_name}' is not importable. Reinstall requirements in the "
        "active virtual environment."
    )

