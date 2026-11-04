"""Reviewer ask: basic structural validation."""
from course_context_pipeline.validate_basic import basic_errors, counts


def test_valid_passes(valid_cc):
    assert basic_errors(valid_cc) == []


def test_non_dict_top_level():
    assert basic_errors([1, 2]) == ["top level is not a JSON object"]


def test_missing_schema_version(valid_cc):
    del valid_cc["course_context_schema_version"]
    assert any("course_context_schema_version" in e for e in basic_errors(valid_cc))


def test_course_not_object(valid_cc):
    valid_cc["Course"] = None
    assert any("Course" in e for e in basic_errors(valid_cc))


def test_array_not_a_list(valid_cc):
    valid_cc["Concept"] = {}
    assert any("Concept" in e for e in basic_errors(valid_cc))


def test_empty_module_and_concept(valid_cc):
    valid_cc["Module"] = []
    valid_cc["Concept"] = []
    errs = basic_errors(valid_cc)
    assert any("Module" in e for e in errs)
    assert any("Concept" in e for e in errs)


def test_counts(valid_cc):
    assert counts(valid_cc) == {"Module": 1, "Concept": 1, "LearningObjective": 1,
                                "Source": 1, "assumptions": 0}
