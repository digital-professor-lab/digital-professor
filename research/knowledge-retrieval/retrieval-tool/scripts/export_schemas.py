"""Write the JSON Schemas of RetrievalRequest, GroundingBundle, RetrievalStop and RetrievalPlan.

In the repository they go to specs/schemas/ (next to specs/rag-retrieval.md); elsewhere to schemas/.

    python scripts/export_schemas.py            # write
    python scripts/export_schemas.py --check    # exit 1 if a file is out of date
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WEEK8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEEK8))
from retrieval_tool.planner import PLAN_SCHEMA  # noqa: E402
from retrieval_tool.schemas import SCHEMAS  # noqa: E402


def rendered() -> dict[str, str]:
    out = {name: json.dumps(build(), indent=2, ensure_ascii=False) + "\n" for name, build in SCHEMAS.items()}
    out["retrieval-plan.schema.json"] = json.dumps(PLAN_SCHEMA, indent=2, ensure_ascii=False) + "\n"
    return out


def schema_folder() -> Path:
    """Where the schema files live: the repository's specs/schemas/ when this package sits at
    research/knowledge-retrieval/retrieval-tool/ in the repo, otherwise schemas/ next to the package."""
    repo_specs = WEEK8.parents[2] / "specs"
    if (repo_specs / "rag-retrieval.md").exists():
        return repo_specs / "schemas"
    return WEEK8 / "schemas"


def main() -> None:
    folder = schema_folder()
    folder.mkdir(exist_ok=True)
    stale = []
    for name, text in rendered().items():
        path = folder / name
        if "--check" in sys.argv:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}")
    if stale:
        print("out of date:", ", ".join(stale), "— run python scripts/export_schemas.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
