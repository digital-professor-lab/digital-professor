"""Create a readable local review page from evaluation results and review CSVs."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote


HERE = Path(__file__).resolve().parent
DEFAULT_RESULTS = HERE / "results"


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def load_results(directory: Path) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                grouped[row["case_id"]].append(row)
    reviews: dict[str, dict] = {}
    for path in directory.glob("*-review.csv"):
        with path.open(newline="", encoding="utf-8") as handle:
            reviews.update({row["run_id"]: row for row in csv.DictReader(handle)})
    return grouped, reviews


def render_run(row: dict, grade: dict) -> str:
    phase = f"{row['phase']} #{row['repetition']}"
    score = (
        f"math equivalent: {grade.get('math_equivalent') or 'unreviewed'}"
        if row["kind"] == "handwriting"
        else " | ".join(f"{name}: {grade.get(name) or '—'}/2" for name in ("correctness", "grounding", "uncertainty"))
    )
    details = f"<p class='review'><strong>Draft review:</strong> {escape(score)}<br>{escape(grade.get('notes', ''))}</p>"
    if row.get("error"):
        body = f"<p class='error'>{escape(row['error'])}</p>"
    elif row["kind"] == "handwriting":
        body = (
            "<div class='columns'>"
            f"<div><h4>Reference transcription</h4><pre>{escape(row['reference_markdown'])}</pre></div>"
            f"<div><h4>Model transcription</h4><pre>{escape(row['transcript'])}</pre></div>"
            "</div>"
            f"<p>Surface exact match: {escape(row['exact_match'])}; character error rate: {row['character_error_rate']:.3f}; "
            f"HTTP time: {row['wall_seconds']:.2f}s.</p>"
        )
    else:
        answer = row["response"]
        citations = answer.get("citations", [])
        citation_list = "".join(
            f"<li>{escape(c.get('filename', ''))}, PDF p. {escape(c.get('page_number') or 'unspecified')}: {escape(c.get('basis', ''))}</li>"
            for c in citations
        ) or "<li>No citations returned.</li>"
        body = (
            f"<h4>Model answer</h4><pre>{escape(answer.get('answer_markdown', ''))}</pre>"
            f"<h4>Model citations</h4><ul>{citation_list}</ul>"
            f"<p>HTTP time: {row['wall_seconds']:.2f}s; provider time: {row['provider_seconds']:.2f}s.</p>"
        )
    return (
        f"<details class='run'><summary>{escape(phase)} · {escape(score)}</summary>"
        f"<small>Run ID: {escape(row['run_id'])}</small>{body}{details}</details>"
    )


def render_page(directory: Path) -> str:
    grouped, reviews = load_results(directory)
    nav = "".join(f"<a href='#{escape(case_id)}'>{escape(case_id)}</a>" for case_id in sorted(grouped))
    sections = []
    for case_id in sorted(grouped):
        rows = grouped[case_id]
        first = rows[0]
        if first["kind"] == "handwriting":
            link = f"../{quote(first['file'])}"
            prompt = f"<p><a href='{escape(link)}' target='_blank'>Open the handwritten PDF ↗</a> · {escape(first['category'])}</p>"
        else:
            points = "".join(f"<li>{escape(point)}</li>" for point in first["expected_points"])
            prompt = (
                f"<p><strong>Student question:</strong> {escape(first['question'])}</p>"
                f"<p><strong>Expected points:</strong></p><ul>{points}</ul>"
                f"<p><strong>Reference:</strong> {escape(first['reference'])}</p>"
            )
        runs = "".join(render_run(row, reviews.get(row["run_id"], {})) for row in rows)
        sections.append(f"<section id='{escape(case_id)}'><h2>{escape(case_id)} · {escape(first['kind'])}</h2>{prompt}{runs}</section>")
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Digital Professor evaluation review</title>
<style>
:root {{font-family:system-ui,-apple-system,sans-serif;color:#21302b;background:#f6f5ef}}
body {{max-width:1100px;margin:auto;padding:30px 22px 100px;line-height:1.5}}
h1 {{margin-bottom:4px}} .hint {{color:#52635a;max-width:800px}}
nav {{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0}} nav a {{padding:5px 10px;background:#e0ebe4;border-radius:8px;color:#194732;text-decoration:none}}
section {{background:white;border:1px solid #d7e0d9;border-radius:14px;padding:18px 22px;margin:20px 0;scroll-margin-top:16px}}
section h2 {{margin:0 0 8px}} a {{color:#126340}}
.run {{border-top:1px solid #d7e0d9;padding:12px 0}} summary {{cursor:pointer;font-weight:600}}
.columns {{display:grid;grid-template-columns:1fr 1fr;gap:14px}} pre {{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f2;border-radius:8px;padding:14px;font-size:13px;line-height:1.5}}
.review {{background:#fff4de;border-radius:8px;padding:11px 14px}} .error {{color:#a63724}} small {{color:#67766c}}
@media(max-width:700px) {{.columns {{grid-template-columns:1fr}}}}
</style></head><body>
<h1>Evaluation review</h1>
<p class='hint'>Open a case, then a run. For handwriting, compare the PDF with the reference and model transcription. For tutoring, compare the student question, expected points, model answer, and citations. Scores are provisional AI-assisted reviews; this page reads the latest CSV files whenever regenerated.</p>
<nav>{nav}</nav>{''.join(sections)}
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.results / "REVIEW.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_page(args.results), encoding="utf-8")
    print(f"Review page: {output.resolve()}")


if __name__ == "__main__":
    main()
