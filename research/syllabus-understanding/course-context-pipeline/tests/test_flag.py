"""Tests for the deterministic Review Flagger.

v1 behavior: confidence IS used to suppress — `high`-confidence items are dropped
entirely; only `low` and `medium` (and untagged, treated as medium) reach the
worklist. Check-first set: {Concept.difficulty_notes, Course.assumed_background}.
"""
from course_context_pipeline.flag import flag


def _cc(assumptions):
    return {"Course": {"id": "c"}, "assumptions": assumptions}


def _a(entity, rid, field, confidence=None):
    e = {"entity": entity, "id": rid, "field": field, "assumption": "val", "reason": "why"}
    if confidence is not None:
        e["confidence"] = confidence
    return e


def test_high_confidence_items_suppressed():
    rep = flag(_cc([
        _a("Concept", "c.01.x", "difficulty_notes", "high"),    # suppressed
        _a("Concept", "c.01.y", "difficulty_notes", "low"),     # shown
        _a("Course", "c", "assumed_background", "high"),         # suppressed
        _a("Course", "c", "assumed_background", "medium"),       # shown (same field, lower conf)
    ]))
    flagged = {(i["entity"], i["field"], i["confidence"]) for i in rep["items"]}
    assert ("Concept", "difficulty_notes", "low") in flagged
    assert ("Course", "assumed_background", "medium") in flagged
    assert rep["summary"]["check_first"] == 2                   # high items dropped


def test_non_check_first_field_not_flagged():
    rep = flag(_cc([_a("Concept", "c.01.x", "summary", "low")]))
    assert rep["summary"]["check_first"] == 0


def test_untagged_confidence_is_still_flagged():
    rep = flag(_cc([_a("Concept", "c.01.x", "difficulty_notes")]))   # no confidence key
    assert rep["summary"]["check_first"] == 1
    assert rep["items"][0]["confidence"] is None


def test_confidence_orders_shakiest_first():
    rep = flag(_cc([
        _a("Concept", "c.01.b", "difficulty_notes", "low"),
        _a("Concept", "c.01.c", "difficulty_notes", "medium"),
    ]))
    assert [i["confidence"] for i in rep["items"]] == ["low", "medium"]


def test_wildcard_becomes_global_note():
    rep = flag(_cc([_a("Concept", "calc1.*", "difficulty_notes")]))
    assert rep["summary"]["global_notes"] == 1
    assert rep["summary"]["check_first"] == 0


def test_report_shape():
    rep = flag(_cc([_a("Course", "c", "assumed_background", "medium")]), source_sha256="abc")
    assert set(rep) == {"course_id", "built_from_sha256", "summary", "items", "global_notes"}
    assert rep["built_from_sha256"] == "abc"
    assert rep["course_id"] == "c"
