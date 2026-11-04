"""Shared pytest fixtures. Lives at the package root so `course_context_pipeline`
is importable when pytest is run from this directory."""
import pytest


@pytest.fixture
def valid_cc() -> dict:
    """A minimal structurally-valid CourseContext (schema 1.1)."""
    return {
        "course_context_schema_version": "1.1",
        "Course": {"id": "c", "title": "C", "level": "undergraduate introductory",
                   "duration_weeks": 14, "assumed_background": "algebra",
                   "module_ids": ["c.01-m"], "provenance": "ai_inferred"},
        "Module": [{"id": "c.01-m", "course_id": "c", "title": "M", "goal": "g",
                    "weeks": "1-2", "concept_ids": ["c.01-m.x"], "provenance": "ai_inferred"}],
        "Concept": [{"id": "c.01-m.x", "module_id": "c.01-m", "name": "X", "summary": "s",
                     "key_definitions": [], "prerequisite_ids": [],
                     "objective_ids": ["c.01-m.x.lo1"], "difficulty_notes": [],
                     "source_ids": ["src.1"], "provenance": "ai_inferred"}],
        "LearningObjective": [{"id": "c.01-m.x.lo1", "concept_id": "c.01-m.x", "text": "t",
                               "bloom_level": "apply", "provenance": "ai_inferred"}],
        "Source": [{"id": "src.1", "type": "textbook", "citation": "cit", "section": "S1",
                    "text_chunk": "x", "provenance": "source_backed"}],
        "assumptions": [],
    }
