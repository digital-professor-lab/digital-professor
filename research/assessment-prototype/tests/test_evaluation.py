"""Offline checks for evaluation preparation and scoring."""

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from evaluation.evaluate import edit_distance, load_manifest, normalized, summarize, validate
from webapp.backend.app import app, sources


class EvaluationTests(unittest.TestCase):
    def test_manifest_is_complete_and_requires_handwriting_references(self):
        manifest_path = Path(__file__).resolve().parents[1] / "evaluation" / "cases.json"
        manifest = load_manifest(manifest_path)
        self.assertEqual(validate(manifest, manifest_path.parent), [])
        manifest["handwriting"][0]["reference_markdown"] = ""
        self.assertTrue(any("reference_markdown" in problem for problem in validate(manifest, manifest_path.parent, "handwriting")))

    def test_normalized_character_error_and_summary(self):
        self.assertEqual(normalized("[PAGE 1]\n$a + b$"), "$a+b$")
        self.assertEqual(edit_distance("abc", "axc"), 1)
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            run = {"run_id": "one", "case_id": "h01", "kind": "handwriting", "phase": "warm", "exact_match": False, "character_error_rate": 0.25, "wall_seconds": 1.2}
            (directory / "sample.jsonl").write_text(json.dumps(run) + "\n", encoding="utf-8")
            with (directory / "sample-review.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["run_id", "math_equivalent", "failure_tags"])
                writer.writeheader()
                writer.writerow({"run_id": "one", "math_equivalent": "yes", "failure_tags": "latex_format"})
            report = summarize(directory)
        self.assertIn("Mean character error rate: 0.250", report)
        self.assertIn("Reviewer-rated mathematical equivalence: 1/1", report)
        self.assertIn("latex_format: 1", report)

    def test_source_text_endpoint_returns_full_transcription(self):
        sources.clear()
        response = TestClient(app).post(
            "/api/sources",
            files={"file": ("example.txt", b"Course overview\nThis course studies optimization.", "text/plain")},
            data={"source_type": "document"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        source_id = response.json()["id"]
        text = TestClient(app).get(f"/api/evaluation/sources/{source_id}/text")
        self.assertEqual(text.status_code, 200)
        self.assertIn("This course studies optimization.", text.json()["text"])
        sources.clear()


if __name__ == "__main__":
    unittest.main()
