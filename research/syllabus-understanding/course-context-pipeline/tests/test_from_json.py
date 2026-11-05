"""Reviewer ask: the --from-json path (load a pre-generated CourseContext, no LLM)."""
import json

from course_context_pipeline.config import Config
from course_context_pipeline.pipeline import run_stage_a


def test_from_json_loads_validates_and_writes(tmp_path, valid_cc):
    src = tmp_path / "cc.json"
    src.write_text(json.dumps(valid_cc), encoding="utf-8")
    out = tmp_path / "out.json"

    res = run_stage_a(Config(from_json=src, output_path=out), quiet=True)

    assert res.source == "from_json"
    assert res.errors == []                 # the fixture is structurally valid
    assert res.attempts == 0                # no generation
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8"))["Course"]["id"] == "c"


def test_from_json_reports_structural_errors(tmp_path):
    broken = {"course_context_schema_version": "1.1", "Course": {}, "Module": [], "Concept": []}
    src = tmp_path / "broken.json"
    src.write_text(json.dumps(broken), encoding="utf-8")
    out = tmp_path / "out.json"

    res = run_stage_a(Config(from_json=src, output_path=out), quiet=True)

    assert res.source == "from_json"
    assert res.errors                       # missing arrays + empty Module/Concept
    assert out.exists()                     # still written for inspection
