"""Reviewer ask: module assembly (trimmed schema v1.1 — no LO/Source arrays)."""
from course_context_pipeline.generate_by_module import assemble


def _outline():
    return {
        "course_context_schema_version": "1.1",
        "Course": {"id": "c", "module_ids": []},
        "Module": [{"id": "c.01", "concept_ids": []}, {"id": "c.02", "concept_ids": []}],
        "assumptions": [{"entity": "Course", "id": "c", "field": "level",
                         "assumption": "intro", "reason": "first course"}],
    }


def test_merge_and_backfill():
    m1 = {
        "Concept": [{"id": "c.01.a", "module_id": "c.01"}],
        "assumptions": [{"entity": "Concept", "id": "c.01.a", "field": "summary",
                         "assumption": "x", "reason": "y"}],
    }
    m2 = {
        "Concept": [{"id": "c.02.b", "module_id": "c.02", "prerequisite_ids": ["c.01.a"]}],
    }
    cc = assemble(_outline(), [m1, m2])

    # concatenation
    assert [c["id"] for c in cc["Concept"]] == ["c.01.a", "c.02.b"]
    # no LO/Source arrays in trimmed schema
    assert "LearningObjective" not in cc
    assert "Source" not in cc
    # back-filled Module.concept_ids from each concept's module_id
    assert cc["Module"][0]["concept_ids"] == ["c.01.a"]
    assert cc["Module"][1]["concept_ids"] == ["c.02.b"]
    # back-filled Course.module_ids (outline left it empty)
    assert cc["Course"]["module_ids"] == ["c.01", "c.02"]
    # assumptions collected from outline + modules
    assert len(cc["assumptions"]) == 2


def test_empty_modules_yield_empty_array():
    cc = assemble({"Course": {"id": "c", "module_ids": ["c.01"]},
                   "Module": [{"id": "c.01"}]}, [])
    assert cc["Concept"] == []
    assert cc["Module"][0]["concept_ids"] == []
    assert "assumptions" not in cc        # none collected -> key omitted
