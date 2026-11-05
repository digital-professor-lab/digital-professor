"""The one-command smoke check, and the committed current fixture."""

import json
import subprocess
import sys
import unittest

from _setup import PACKAGE
from retrieval_tool.schemas import validate_record


class SmokeTests(unittest.TestCase):
    def test_smoke_check_passes_from_any_folder(self):
        run = subprocess.run([sys.executable, str(PACKAGE / "scripts" / "smoke_check.py")], cwd="/",
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("Smoke check passed.", run.stdout)

    def test_committed_fixture_matches_the_schemas(self):
        fixture = json.loads((PACKAGE / "results" / "fixtures" / "stubbed_explain_turn.json").read_text(encoding="utf-8"))
        self.assertTrue(fixture["requests"] and fixture["records"])
        for record in [*fixture["requests"], *fixture["records"]]:
            self.assertEqual(validate_record(record), [])


if __name__ == "__main__":
    unittest.main()
