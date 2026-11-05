"""Write data/fixture_corpus/ from a Week 3 checkout (run scripts/setup_week3.sh first).

The fixture is a small subset of the Week 3 catalog, so the core tests and the smoke check can run without
Week 3. Only maintainers need this script; the output is committed.

    python scripts/build_fixture_corpus.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from retrieval_tool import retrieval_root  # noqa: E402

TERMS = ("fundamental theorem", "chain rule", "logistic growth", "quadratic reciprocity")
PER_TERM = 8


def main() -> None:
    source = retrieval_root() / "data" / "catalog"
    target = HERE / "data" / "fixture_corpus" / "data" / "catalog"
    target.mkdir(parents=True, exist_ok=True)
    read = lambda name: [json.loads(l) for l in (source / name).read_text(encoding="utf-8").splitlines() if l.strip()]  # noqa: E731
    write = lambda name, rows: (target / name).write_text(  # noqa: E731
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    documents, passages = read("documents.jsonl"), read("passages.jsonl")
    kept: dict[str, dict] = {}
    for term in TERMS:
        for document in documents:
            hits = [p for p in passages if p["document_id"] == document["document_id"]
                    and term in (p.get("readable_text") or p["raw_latex"]).lower()]
            for passage in sorted(hits, key=lambda p: (len(p["raw_latex"]), p["passage_id"]))[:PER_TERM]:
                kept[passage["passage_id"]] = passage
    rows = sorted(kept.values(), key=lambda p: p["passage_id"])
    write("documents.jsonl", documents)
    write("passages.jsonl", rows)
    write("concept_evidence.jsonl", [r for r in read("concept_evidence.jsonl") if r["passage_id"] in kept])
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    (target / "manifest.json").write_text(json.dumps({"courses": manifest["courses"], "note": "Test fixture: a subset of "
                                          "the Week 3 catalog. See scripts/build_fixture_corpus.py."}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} passages to {target}")


if __name__ == "__main__":
    main()
