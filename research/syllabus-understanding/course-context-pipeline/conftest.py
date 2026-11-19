"""Shared pytest fixtures. Lives at the package root so `course_context_pipeline`
is importable when pytest is run from this directory."""
import pytest


@pytest.fixture
def valid_cc() -> dict:
    """A minimal structurally-valid CourseContext (schema 1.1)."""
    return {
        "course_context_schema_version": "1.1",
        "Course": {"id": "c", "title": "C", "level": "undergraduate introductory",
                   "assumed_background": "algebra", "module_ids": ["c.01-m"],
                   "provenance": "ai_inferred"},
        "Module": [{"id": "c.01-m", "course_id": "c", "title": "M", "goal": "g",
                    "concept_ids": ["c.01-m.x"], "provenance": "ai_inferred"}],
        "Concept": [{"id": "c.01-m.x", "module_id": "c.01-m", "name": "X", "summary": "s",
                     "prerequisite_ids": [], "difficulty_notes": [], "provenance": "ai_inferred"}],
        "assumptions": [],
    }
