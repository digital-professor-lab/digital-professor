"""Tests for the QuestionSchema builder, using a stub LLM."""
import json

import pytest

from course_context_pipeline import build_question_schema as B
from course_context_pipeline.build_question_schema import (
    adhoc_id, build_runtime_question_schema, main, validate_question_schema, verify_answer)

XCOSX = "\\int x\\cos(x) dx"

# LLM runtime payload for ∫ x cos(x) dx.
# learning_objectives are now LLM-generated (not copied from LO records).
# verification block is sympy-checkable: d/dx[x*sin(x)+cos(x)] = x*cos(x).
RUNTIME = {
    "learning_objectives": [{"text": "Apply integration by parts to evaluate an integral", "bloom_level": "apply"}],
    "question_type": "worked_problem",
    "expected_response_modes": ["steps", "equation"],
    "correct_approach": {"technique": "Integration by parts", "justification": "LIATE: u=x"},
    "alternative_approaches": [{"technique": "Tabular", "justification": "degree-1 polynomial"}],
    "reference_answer": "x sin(x) + cos(x) + C",
    "prerequisite_relevance": {"c.01-m.y": "needed to reverse the product rule"},
    "misconception_cues": ["student sets u=cos(x)"],
    "additional_misconceptions": [],
    "verification": {"variable": "x", "integrand": "x*cos(x)", "antiderivative": "x*sin(x)+cos(x)"},
}


def _cc() -> dict:
    """Minimal trimmed-schema CourseContext fixture (no LO, Source, key_definitions, weeks)."""
    return {
        "course_context_schema_version": "1.1",
        "Course": {"id": "c", "title": "C", "level": "undergraduate introductory",
                   "assumed_background": "algebra", "module_ids": ["c.01-m"],
                   "provenance": "ai_inferred"},
        "Module": [{"id": "c.01-m", "course_id": "c", "title": "M", "goal": "g",
                    "concept_ids": ["c.01-m.y", "c.01-m.x"], "provenance": "ai_inferred"}],
        "Concept": [
            {"id": "c.01-m.y", "module_id": "c.01-m", "name": "Y", "summary": "s",
             "prerequisite_ids": [], "difficulty_notes": [], "provenance": "ai_inferred"},
            {"id": "c.01-m.x", "module_id": "c.01-m", "name": "X", "summary": "s",
             "prerequisite_ids": ["c.01-m.y"],
             "difficulty_notes": [{"misconception": "M-desc", "mitigation": "M-fix"}],
             "provenance": "ai_inferred"},
        ],
        "assumptions": [],
    }


class FakeLLM:
    """Returns canned responses in order (matcher call, then runtime call)."""
    def __init__(self, responses):
        self.responses = [r if isinstance(r, str) else json.dumps(r) for r in responses]

    def complete(self, system, user):
        return self.responses.pop(0) if self.responses else "{}"


def _build(responses, concept_id="c.01-m.x", matcher=None, prompt=XCOSX):
    return build_runtime_question_schema(_cc(), "sha", prompt, FakeLLM(responses),
                                         concept_id=concept_id, matcher=matcher)


# --- deterministic ID normalization -----------------------------------------

def test_adhoc_id_matches_golden():
    assert adhoc_id("calc1.06-integral-applications.by-parts", XCOSX) == \
        "calc1.06-integral-applications.by-parts.adhoc-d7df1b60"


def test_adhoc_id_is_whitespace_insensitive():
    assert adhoc_id("p", "a b\tc") == adhoc_id("p", "abc")


def test_adhoc_id_is_notation_sensitive():
    assert adhoc_id("p", XCOSX) != adhoc_id("p", "integral of x cos(x)")


# --- concept selection: explicit, automatic (matcher + LLM), rejection ------

def test_explicit_concept_selection():
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    assert qs["concept_ids"][0] == "c.01-m.x" and qs["origin"] == "runtime"


def test_automatic_selection_via_injected_matcher():
    qs = _build([RUNTIME], concept_id=None, matcher=lambda prompt, concepts: ("c.01-m.x", []))
    assert qs["concept_ids"] == ["c.01-m.x"]


def test_automatic_selection_via_llm_matcher():
    match = {"primary_concept_id": "c.01-m.x", "related_concept_ids": []}
    qs = _build([match, RUNTIME], concept_id=None)
    assert qs["concept_ids"][0] == "c.01-m.x"


def test_unknown_concept_id_rejected():
    with pytest.raises(B.BuildError):
        _build([RUNTIME], concept_id="c.01-m.ghost")


def test_matcher_returning_unknown_concept_rejected():
    with pytest.raises(B.BuildError):
        _build([RUNTIME], concept_id=None, matcher=lambda p, c: ("nope", []))


# --- assembled content -------------------------------------------------------

def test_learning_objectives_from_llm():
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    assert len(qs["learning_objectives"]) == 1
    lo = qs["learning_objectives"][0]
    assert lo["id"] == "c.01-m.x.lo.0"
    assert lo["bloom_level"] == "apply"
    assert "integration by parts" in lo["text"].lower()


def test_prereqs_and_misconceptions_from_cc():
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    assert [p["concept_id"] for p in qs["prerequisite_concepts"]] == ["c.01-m.y"]
    assert qs["common_misconceptions"][0]["description"] == "M-desc"   # verbatim from CC
    assert qs["common_misconceptions"][0]["mitigation"] == "M-fix"
    assert qs["common_misconceptions"][0]["cue"] == "student sets u=cos(x)"  # from LLM


def test_source_reference_empty_source_ids():
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    assert qs["source_reference"]["source_ids"] == []
    assert qs["source_reference"]["grounding"] == "reference_only"


# --- malformed LLM output ----------------------------------------------------

def test_malformed_llm_output_raises():
    with pytest.raises(ValueError):                 # GenerationError (unparseable)
        _build(["this is not json"], concept_id="c.01-m.x")


# --- independent answer verification ----------------------------------------

def test_verify_answer_unverified_without_sympy_payload():
    assert verify_answer(None)[0] == "unverified"
    assert verify_answer({"variable": "x"})[0] == "unverified"


def test_unverified_status_when_payload_missing():
    j = dict(RUNTIME, verification=None)
    qs = _build([j], concept_id="c.01-m.x")
    assert qs["answer_verification"]["status"] == "unverified"


def test_correct_answer_verifies():
    pytest.importorskip("sympy")
    assert verify_answer(RUNTIME["verification"])[0] == "verified"
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    assert qs["answer_verification"]["status"] == "verified"


def test_wrong_answer_fails_and_is_rejected():
    pytest.importorskip("sympy")
    bad = dict(RUNTIME, verification={"variable": "x", "integrand": "x*cos(x)",
                                      "antiderivative": "x*sin(x)"})   # wrong (missing +cos)
    assert verify_answer(bad["verification"])[0] == "failed"
    with pytest.raises(B.BuildError):
        _build([bad], concept_id="c.01-m.x")


# --- full schema validation: enums & references -----------------------------

def test_built_schema_validates_clean():
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    assert validate_question_schema(qs, _cc()) == []


def test_validate_bad_question_type_enum():
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    qs["question_type"] = "bogus"
    assert any("question_type" in m for m in validate_question_schema(qs, _cc()))


def test_validate_bad_response_mode_enum():
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    qs["expected_response_modes"] = ["telepathy"]
    assert any("expected_response_modes" in m for m in validate_question_schema(qs, _cc()))


def test_validate_bad_bloom_level():
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    qs["learning_objectives"][0]["bloom_level"] = "bogus"
    assert any("bloom_level" in m for m in validate_question_schema(qs, _cc()))


def test_validate_prerequisite_not_direct():
    qs = _build([RUNTIME], concept_id="c.01-m.x")
    qs["prerequisite_concepts"].append({"concept_id": "c.01-m.x", "name": "X", "relevance": "r",
                                        "provenance": "ai_inferred", "derived_from": "runtime"})
    assert any("direct prerequisite" in m for m in validate_question_schema(qs, _cc()))


# --- CLI: publication gating + exit codes -----------------------------------

def test_cli_exit_0_and_publishes_valid(tmp_path):
    ccf = tmp_path / "cc.json"; ccf.write_text(json.dumps(_cc()), encoding="utf-8")
    out = tmp_path / "qs.json"
    rc = main(["--course-context", str(ccf), "--question", XCOSX, "--concept-id", "c.01-m.x",
               "--out", str(out)], llm=FakeLLM([RUNTIME]))
    assert rc == 0 and out.exists()


def test_cli_invalid_output_not_published_exit_2(tmp_path):
    ccf = tmp_path / "cc.json"; ccf.write_text(json.dumps(_cc()), encoding="utf-8")
    out = tmp_path / "qs.json"
    bad = dict(RUNTIME, question_type="bogus")               # invalid enum -> schema invalid
    rc = main(["--course-context", str(ccf), "--question", XCOSX, "--concept-id", "c.01-m.x",
               "--out", str(out)], llm=FakeLLM([bad]))
    assert rc == 2
    assert not out.exists()                                  # NOT published
    assert (tmp_path / "qs.rejected.json").exists()          # written elsewhere, marked


def test_cli_exit_2_on_unknown_concept(tmp_path):
    ccf = tmp_path / "cc.json"; ccf.write_text(json.dumps(_cc()), encoding="utf-8")
    rc = main(["--course-context", str(ccf), "--question", XCOSX, "--concept-id", "ghost"],
              llm=FakeLLM([RUNTIME]))
    assert rc == 2
