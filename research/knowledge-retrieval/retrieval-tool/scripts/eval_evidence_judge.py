"""Rules vs Jev on "does this passage state what the need asks for?" (28 labelled need–passage pairs).

The main metric is FALSE COVERED: a passage judged to state a need when it does not. That is the error that
lets the tutor cite a topic title as if it were the theorem. Labels (data/evidence_judge_cases.jsonl) are
Sean's silver labels on real passages from the Week 3 corpus; spot-check them.

    python scripts/eval_evidence_judge.py              # rules (offline) + Jev (28 calls, < $0.01)
    python scripts/eval_evidence_judge.py --rules-only # no Jev call
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WEEK8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEEK8))
from retrieval_tool import retrieval_root  # noqa: E402
from retrieval_tool.evidence import JUDGE_COVERED_AT, JUDGE_PARTIAL_AT, rule_check  # noqa: E402

LEVELS = ("not_covered", "partially_covered", "covered")


def metrics(rows: list[dict], key: str) -> dict:
    return {"agree_3way": f"{sum(r[key] == r['label'] for r in rows)}/{len(rows)}",
            "false_covered": sum(r[key] == "covered" and r["label"] != "covered" for r in rows),
            "missed_covered": sum(r[key] != "covered" and r["label"] == "covered" for r in rows),
            "covered_vs_not_correct": f"{sum((r[key] == 'covered') == (r['label'] == 'covered') for r in rows)}/{len(rows)}"}


def level(p: float, covered_at: float, partial_at: float) -> str:
    return "covered" if p >= covered_at else "partially_covered" if p >= partial_at else "not_covered"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-only", action="store_true")
    args = parser.parse_args()
    root = retrieval_root()
    passages = {json.loads(l)["passage_id"]: json.loads(l)
                for l in (root / "data/catalog/passages.jsonl").read_text().splitlines() if l.strip()}
    cases = [json.loads(l) for l in (WEEK8 / "data/evidence_judge_cases.jsonl").read_text().splitlines() if l.strip()]
    rows = []
    for case in cases:
        passage = passages[case["week3_passage_id"]]
        rule, why = rule_check(case["need"], passage["raw_latex"])
        rows.append({"id": case["id"], "label": case["label"], "rules": rule, "rules_why": why,
                     "need": case["need"]["description"], "_text": passage.get("readable_text") or passage["raw_latex"]})
    out: dict = {"cases": len(rows), "rules": metrics(rows, "rules")}
    if not args.rules_only:
        from retrieval_tool.jev_decider import default_evidence_judge
        judge = default_evidence_judge()
        scores = [judge.score([c["need"]], [r["_text"]])[0]["n1"] for c, r in zip(cases, rows)]
        for r, p in zip(rows, scores):
            r["jev_p"] = round(p, 4)
            r["jev"] = level(p, JUDGE_COVERED_AT, JUDGE_PARTIAL_AT)
        out["jev_at_defaults"] = {"covered_at": JUDGE_COVERED_AT, "partial_at": JUDGE_PARTIAL_AT, **metrics(rows, "jev")}
        sweep = {}
        for covered_at in (0.5, 0.6, 0.7, 0.8, 0.9):
            for r in rows:
                r["_s"] = level(r["jev_p"], covered_at, min(JUDGE_PARTIAL_AT, covered_at))
            sweep[str(covered_at)] = metrics(rows, "_s")
        out["jev_threshold_sweep"] = sweep
        out["jev_usage"] = judge.client.usage.to_dict()
    for r in rows:
        r.pop("_text", None)
        r.pop("_s", None)
    out["rows"] = rows
    path = WEEK8 / "results" / "evidence_judge_eval.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{'id':4s} {'label':8s} {'rules':8s} {'jev':8s} p     need")
    for r in rows:
        print(f"{r['id']:4s} {r['label'][:8]:8s} {r['rules'][:8]:8s} {r.get('jev', '-')[:8]:8s} "
              f"{r.get('jev_p', ''):<5} {r['need'][:60]}")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    print(f"saved {path.relative_to(WEEK8)}")


if __name__ == "__main__":
    main()
