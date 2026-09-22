"""Prepare, run, and summarize the focused local prototype evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx


HERE = Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "cases.json"
DEFAULT_RESULTS = HERE / "results"
REVIEW_FIELDS = ["run_id", "case_id", "kind", "phase", "math_equivalent", "correctness", "grounding", "uncertainty", "answer_family", "failure_tags", "notes"]


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(manifest: dict, root: Path, kind: str | None = None) -> list[str]:
    problems: list[str] = []
    kinds = [kind] if kind else ["handwriting", "tutoring"]
    for selected in kinds:
        cases = manifest.get(selected, [])
        if not cases:
            problems.append(f"No {selected} cases defined.")
        ids = [case.get("id") for case in cases]
        if len(ids) != len(set(ids)):
            problems.append(f"Duplicate {selected} case IDs.")
        for case in cases:
            case_id = case.get("id", "<missing id>")
            if selected == "handwriting":
                if not case.get("file") or not (root / case["file"]).is_file():
                    problems.append(f"{case_id}: image file is missing.")
                if not case.get("reference_markdown", "").strip():
                    problems.append(f"{case_id}: reference_markdown is empty.")
            else:
                if not case.get("question", "").strip() or not case.get("expected_points"):
                    problems.append(f"{case_id}: question or expected_points missing.")
    if kind in (None, "tutoring"):
        for source in manifest.get("course_sources", []):
            if not (root / source["file"]).is_file():
                problems.append(f"Course source is missing: {source['file']}")
        if not manifest.get("course_sources"):
            problems.append("No course sources defined.")
    return problems


def normalized(text: str) -> str:
    text = re.sub(r"\[PAGE\s+\d+\]", "", text, flags=re.I)
    return re.sub(r"\s+", "", text).strip()


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for index, letter in enumerate(left, 1):
        current = [index]
        for column, other in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (letter != other)))
        previous = current
    return previous[-1]


def response_json(response: httpx.Response) -> dict:
    response.raise_for_status()
    return response.json()


def upload(client: httpx.Client, path: Path, source_type: str, provider: str) -> tuple[dict, float]:
    started = time.perf_counter()
    with path.open("rb") as handle:
        result = response_json(client.post(
            "/api/sources",
            files={"file": (path.name, handle)},
            data={"source_type": source_type, "recognition_provider": provider},
        ))
    return result, time.perf_counter() - started


def run(args: argparse.Namespace) -> None:
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    problems = validate(manifest, manifest_path.parent, args.kind)
    if problems:
        raise SystemExit("Evaluation set is incomplete:\n- " + "\n- ".join(problems))
    if args.phase == "cold" and args.repeats != 1:
        raise SystemExit("Cold runs measure the first case once; use --repeats 1.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{stamp}-{args.kind}-{args.phase}"
    result_path = args.out_dir / f"{stem}.jsonl"
    review_path = args.out_dir / f"{stem}-review.csv"
    settings_path = args.out_dir / f"{stem}-settings.json"
    rows: list[dict] = []
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        if response_json(client.get("/api/sources")):
            raise SystemExit("The backend already has sources loaded. Restart it or remove them in the Sources tab before an evaluation run.")
        settings = response_json(client.get("/api/evaluation/config"))
        if not settings["api_key_configured"] and (args.kind == "tutoring" or args.provider == "openai_vision"):
            raise SystemExit("The backend has no API key configured for OpenAI recognition or tutoring.")
        source_uploads = []
        uploaded_ids: list[str] = []
        if args.kind == "tutoring":
            for source in manifest["course_sources"]:
                path = (manifest_path.parent / source["file"]).resolve()
                uploaded, elapsed = upload(client, path, source["type"], args.provider)
                uploaded_ids.append(uploaded["id"])
                source_uploads.append({"filename": path.name, "source_id": uploaded["id"], "upload_seconds": elapsed})

        settings_path.write_text(json.dumps({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "kind": args.kind,
            "phase": args.phase,
            "repeats": args.repeats,
            "base_url": args.base_url,
            "recognition_provider": args.provider,
            "expose_sources": True,
            "backend": settings,
            "course_sources": source_uploads,
            "latency_definition": "Client wall-clock HTTP time; cold label requires a fresh backend restart immediately before this command.",
        }, indent=2), encoding="utf-8")

        cases = manifest[args.kind][:1] if args.phase == "cold" else manifest[args.kind]
        with result_path.open("w", encoding="utf-8") as output:
            for case in cases:
                for repetition in range(args.repeats):
                    row = {
                        "run_id": f"{stem}-{case['id']}-{repetition + 1}",
                        "case_id": case["id"], "kind": args.kind, "phase": args.phase,
                        "repetition": repetition + 1, "category": case["category"],
                        "reference_note": case.get("reference_note", ""),
                    }
                    try:
                        if args.kind == "handwriting":
                            path = (manifest_path.parent / case["file"]).resolve()
                            uploaded, elapsed = upload(client, path, "handwriting", args.provider)
                            uploaded_ids.append(uploaded["id"])
                            transcript = response_json(client.get(f"/api/evaluation/sources/{uploaded['id']}/text"))["text"]
                            expected, observed = normalized(case["reference_markdown"]), normalized(transcript)
                            row.update({
                                "file": case["file"], "source_id": uploaded["id"], "transcript": transcript,
                                "reference_markdown": case["reference_markdown"],
                                "exact_match": expected == observed,
                                "character_error_rate": edit_distance(expected, observed) / max(len(expected), 1),
                                "wall_seconds": elapsed, "provider_requests": uploaded["request_metadata"],
                            })
                        else:
                            started = time.perf_counter()
                            answer = response_json(client.post("/api/chat", json={
                                "question": case["question"], "model": settings["model"],
                                "skills": settings["skills"], "expose_sources": True,
                                "input_cost_per_1m": settings["input_cost_per_1m"],
                                "output_cost_per_1m": settings["output_cost_per_1m"],
                            }))
                            row.update({
                                "question": case["question"], "expected_points": case["expected_points"],
                                "reference": case["reference"], "source_visibility": case["source_visibility"],
                                "response": answer, "wall_seconds": time.perf_counter() - started,
                                "provider_seconds": answer["request"]["elapsed_seconds"],
                            })
                    except (httpx.HTTPError, KeyError) as exc:
                        row["error"] = str(exc)
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")
                    output.flush()
                    rows.append(row)
                    print(f"{row['run_id']}: {'error' if 'error' in row else 'saved'}")

        for source_id in uploaded_ids:
            response_json(client.delete(f"/api/sources/{source_id}"))

    with review_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in REVIEW_FIELDS} for row in rows)
    print(f"Results: {result_path}\nReview sheet: {review_path}\nSettings: {settings_path}")


def percentile(values: list[float], proportion: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * proportion) - 1)]


def summarize(directory: Path) -> str:
    rows = [json.loads(line) for path in directory.glob("*.jsonl") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    reviews = {}
    for path in directory.glob("*-review.csv"):
        with path.open(newline="", encoding="utf-8") as handle:
            reviews.update({row["run_id"]: row for row in csv.DictReader(handle)})
    valid = [row for row in rows if "error" not in row]
    handwriting = [row for row in valid if row["kind"] == "handwriting"]
    tutoring = [row for row in valid if row["kind"] == "tutoring"]
    lines = ["# Focused evaluation summary", "", f"Successful runs: {len(valid)}; errors: {len(rows) - len(valid)}."]
    if handwriting:
        lines += ["", "## Handwriting", f"- Exact transcription: {sum(row['exact_match'] for row in handwriting)}/{len(handwriting)}.",
                  f"- Mean character error rate: {statistics.mean(row['character_error_rate'] for row in handwriting):.3f}."]
        graded = [reviews.get(row["run_id"], {}) for row in handwriting]
        equivalent = [grade["math_equivalent"].strip().lower() for grade in graded if grade.get("math_equivalent", "").strip()]
        if equivalent:
            lines.append(f"- Reviewer-rated mathematical equivalence: {equivalent.count('yes')}/{len(equivalent)}.")
        else:
            lines.append("- Mathematical equivalence: pending human review.")
    if tutoring:
        lines += ["", "## Tutoring"]
        for field in ("correctness", "grounding", "uncertainty"):
            scores = [int(reviews[row["run_id"]][field]) for row in tutoring if reviews.get(row["run_id"], {}).get(field, "").isdigit()]
            lines.append(f"- {field.title()} (0–2): {statistics.mean(scores):.2f} across {len(scores)} graded runs." if scores else f"- {field.title()}: pending human review.")
        families: dict[str, list[str]] = defaultdict(list)
        for row in tutoring:
            if row["phase"] == "warm":
                family = reviews.get(row["run_id"], {}).get("answer_family", "").strip()
                if family:
                    families[row["case_id"]].append(family)
        repeated = [values for values in families.values() if len(values) >= 2]
        lines.append(f"- Consistent answer family: {sum(len(set(values)) == 1 for values in repeated)}/{len(repeated)} reviewed repeated cases." if repeated else "- Response consistency: pending repeated graded runs.")
    lines += ["", "## Latency (client wall clock)"]
    for kind in ("handwriting", "tutoring"):
        for phase in ("cold", "warm"):
            times = [row["wall_seconds"] for row in valid if row["kind"] == kind and row["phase"] == phase]
            if times:
                lines.append(f"- {kind}, {phase}: n={len(times)}, median={statistics.median(times):.2f}s, p90={percentile(times, .9):.2f}s.")
    tags = Counter(tag.strip() for grade in reviews.values() for tag in grade.get("failure_tags", "").split(";") if tag.strip())
    lines += ["", "## Common failure cases"]
    lines += [f"- {tag}: {count}" for tag, count in tags.most_common(5)] or ["- Pending human review."]
    recommendation = (
        "- Add page-level retrieval and allow citations only to pages actually provided to the model; the reviewed runs contain invented page citations."
        if tags.get("invented_page", 0)
        else "- Decide after reviewing the errors and grounding scores; investigate page-level retrieval if questions beyond the first loaded note pages fail."
    )
    lines += ["", "## Recommended next improvement", recommendation]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    check.add_argument("--kind", choices=("handwriting", "tutoring"))
    execute = sub.add_parser("run")
    execute.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    execute.add_argument("--kind", choices=("handwriting", "tutoring"), required=True)
    execute.add_argument("--phase", choices=("cold", "warm"), required=True)
    execute.add_argument("--repeats", type=int, default=1)
    execute.add_argument("--provider", choices=("openai_vision", "tesseract"), default="openai_vision")
    execute.add_argument("--base-url", default="http://127.0.0.1:8001")
    execute.add_argument("--timeout", type=float, default=180.0)
    execute.add_argument("--out-dir", type=Path, default=DEFAULT_RESULTS)
    report = sub.add_parser("summarize")
    report.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    if args.command == "validate":
        problems = validate(load_manifest(args.manifest), args.manifest.resolve().parent, args.kind)
        print("Evaluation set ready." if not problems else "Evaluation set needs work:\n- " + "\n- ".join(problems))
        raise SystemExit(bool(problems))
    if args.command == "run":
        if args.repeats < 1:
            parser.error("--repeats must be positive")
        run(args)
    else:
        print(summarize(args.results))


if __name__ == "__main__":
    main()
