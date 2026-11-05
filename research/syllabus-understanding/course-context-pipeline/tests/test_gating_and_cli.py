"""Reviewer asks: invalid output must not replace a valid published file (#2),
and CLI exit codes."""
import json

from course_context_pipeline.cli import main
from course_context_pipeline.config import Config
from course_context_pipeline.pipeline import run_stage_a

_INVALID = {"course_context_schema_version": "1.1", "Course": {}, "Module": [], "Concept": []}


def test_invalid_result_does_not_overwrite_published(tmp_path):
    out = tmp_path / "cc.json"
    out.write_text(json.dumps({"published": "valid"}), encoding="utf-8")   # last good file
    src = tmp_path / "bad.json"
    src.write_text(json.dumps(_INVALID), encoding="utf-8")

    res = run_stage_a(Config(from_json=src, output_path=out), quiet=True)

    assert res.errors                                                      # it IS invalid
    assert json.loads(out.read_text())["published"] == "valid"            # untouched
    assert (tmp_path / "cc.rejected.json").exists()                        # written elsewhere, marked


def test_valid_result_publishes_and_flags(tmp_path, valid_cc):
    out = tmp_path / "cc.json"
    src = tmp_path / "good.json"
    src.write_text(json.dumps(valid_cc), encoding="utf-8")

    res = run_stage_a(Config(from_json=src, output_path=out), quiet=True)

    assert res.errors == []
    assert out.exists()
    assert (tmp_path / "cc.review.json").exists()
    assert not (tmp_path / "cc.rejected.json").exists()


def test_cli_exit_0_on_clean(tmp_path, valid_cc):
    src = tmp_path / "cc.json"
    src.write_text(json.dumps(valid_cc), encoding="utf-8")
    assert main(["--validate-only", "--from-json", str(src)]) == 0


def test_cli_exit_1_on_errors(tmp_path):
    src = tmp_path / "bad.json"
    src.write_text(json.dumps(_INVALID), encoding="utf-8")
    assert main(["--validate-only", "--from-json", str(src)]) == 1
