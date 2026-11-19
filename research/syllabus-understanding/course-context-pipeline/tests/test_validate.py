"""Reviewer ask: automated tests for the deterministic Validator (V-01..V-10)."""
import copy

from course_context_pipeline.validate import error_findings, error_messages, validate


def _rules(cc) -> set[str]:
    return {f.rule for f in error_findings(validate(cc))}


def test_valid_cc_has_no_findings(valid_cc):
    assert validate(valid_cc) == []                      # 0 errors, 0 warnings (warnings off in v1)


# --- required / unknown fields (V-02) ---------------------------------------

def test_missing_required_field(valid_cc):
    del valid_cc["Concept"][0]["summary"]
    assert "V-02" in _rules(valid_cc)


def test_unknown_field(valid_cc):
    valid_cc["Concept"][0]["surprise"] = "x"
    assert "V-02" in _rules(valid_cc)


# --- ids (V-04) -------------------------------------------------------------

def test_duplicate_id(valid_cc):
    valid_cc["Concept"].append(copy.deepcopy(valid_cc["Concept"][0]))
    assert "V-04" in _rules(valid_cc)


# --- references: dangling (V-05) and inconsistent reverse links (V-06) ------

def test_dangling_reference(valid_cc):
    valid_cc["Concept"][0]["prerequisite_ids"] = ["c.01-m.ghost"]
    assert "V-05" in _rules(valid_cc)


def test_inconsistent_reverse_link(valid_cc):
    # a concept whose module_id points at the module, but the module doesn't list it
    valid_cc["Concept"].append({
        "id": "c.01-m.y", "module_id": "c.01-m", "name": "Y", "summary": "s",
        "prerequisite_ids": [], "difficulty_notes": [], "provenance": "ai_inferred"})
    assert "V-06" in _rules(valid_cc)


# --- prerequisites (V-07) ---------------------------------------------------

def test_prerequisite_self_cycle(valid_cc):
    valid_cc["Concept"][0]["prerequisite_ids"] = ["c.01-m.x"]
    assert "V-07" in _rules(valid_cc)


def test_prerequisite_in_later_module(valid_cc):
    valid_cc["Course"]["module_ids"].append("c.02-n")
    valid_cc["Module"].append({"id": "c.02-n", "course_id": "c", "title": "N", "goal": "g",
                               "concept_ids": ["c.02-n.z"], "provenance": "ai_inferred"})
    valid_cc["Concept"].append({"id": "c.02-n.z", "module_id": "c.02-n", "name": "Z", "summary": "s",
                                "prerequisite_ids": [], "difficulty_notes": [], "provenance": "ai_inferred"})
    valid_cc["Concept"][0]["prerequisite_ids"] = ["c.02-n.z"]        # module 1 needs a module-2 concept
    assert "V-07" in _rules(valid_cc)


# --- assumptions + optional confidence (V-09) -------------------------------

def test_assumption_missing_key(valid_cc):
    valid_cc["assumptions"] = [{"entity": "Course", "id": "c", "field": "level", "assumption": "x"}]
    assert "V-09" in _rules(valid_cc)


def test_assumption_bad_confidence(valid_cc):
    valid_cc["assumptions"] = [{"entity": "Course", "id": "c", "field": "level",
                                "assumption": "x", "reason": "y", "confidence": "pretty-sure"}]
    assert "V-09" in _rules(valid_cc)


def test_assumption_valid_confidence_allowed(valid_cc):
    valid_cc["assumptions"] = [{"entity": "Course", "id": "c", "field": "level",
                                "assumption": "x", "reason": "y", "confidence": "high"}]
    assert validate(valid_cc) == []                      # confidence is optional + additive


def test_assumption_unresolved_id(valid_cc):
    valid_cc["assumptions"] = [{"entity": "Concept", "id": "c.01-m.ghost", "field": "summary",
                                "assumption": "x", "reason": "y"}]
    assert "V-09" in _rules(valid_cc)


# --- provenance (V-10) ------------------------------------------------------

def test_missing_provenance(valid_cc):
    del valid_cc["Concept"][0]["provenance"]
    assert any("provenance" in m for m in error_messages(validate(valid_cc)))


def test_provenance_not_enum(valid_cc):
    valid_cc["Concept"][0]["provenance"] = "Syllabus section 1.1"
    assert any("provenance" in m for m in error_messages(validate(valid_cc)))
