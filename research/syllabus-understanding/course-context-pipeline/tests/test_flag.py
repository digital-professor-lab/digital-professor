"""Reviewer ask: automated tests for the deterministic Review Flagger.

v1 behavior (per review #6 = option A): confidence is NOT used to suppress review
items — every inferred check-first field is flagged regardless of confidence; the
value only orders the worklist (shakiest first).
"""
from course_context_pipeline.flag import flag


def _cc(assumptions):
    return {"Course": {"id": "c"}, "assumptions": assumptions}


def _a(entity, rid, field, confidence=None):
    e = {"entity": entity, "id": rid, "field": field, "assumption": "val", "reason": "why"}
    if confidence is not None:
        e["confidence"] = confidence
    return e


def test_check_first_fields_flagged_even_when_high_confidence():
    rep = flag(_cc([
        _a("Concept", "c.01.x", "difficulty_notes", "high"),
        _a("Concept", "c.01.y", "prerequisite_ids", "low"),
        _a("Concept", "c.01.z", "key_definitions", "high"),
        _a("Course", "c", "assumed_background", "high"),
    ]))
    flagged = {(i["entity"], i["field"]) for i in rep["items"]}
    assert ("Concept", "difficulty_notes") in flagged      # high is NOT suppressed
    assert ("Course", "assumed_background") in flagged
    assert rep["summary"]["check_first"] == 4


def test_non_check_first_field_not_flagged():
    rep = flag(_cc([_a("Concept", "c.01.x", "summary", "low")]))
    assert rep["summary"]["check_first"] == 0


def test_untagged_confidence_is_still_flagged():
    rep = flag(_cc([_a("Concept", "c.01.x", "key_definitions")]))   # no confidence
    assert rep["summary"]["check_first"] == 1
    assert rep["items"][0]["confidence"] is None


def test_confidence_orders_shakiest_first():
    rep = flag(_cc([
        _a("Concept", "c.01.a", "difficulty_notes", "high"),
        _a("Concept", "c.01.b", "difficulty_notes", "low"),
        _a("Concept", "c.01.c", "difficulty_notes", "medium"),
    ]))
    assert [i["confidence"] for i in rep["items"]] == ["low", "medium", "high"]


def test_wildcard_becomes_global_note():
    rep = flag(_cc([_a("Concept", "calc1.*", "difficulty_notes")]))
    assert rep["summary"]["global_notes"] == 1
    assert rep["summary"]["check_first"] == 0


def test_report_shape():
    rep = flag(_cc([_a("Course", "c", "assumed_background", "medium")]), source_sha256="abc")
    assert set(rep) == {"course_id", "built_from_sha256", "summary", "items", "global_notes"}
    assert rep["built_from_sha256"] == "abc"
    assert rep["course_id"] == "c"
