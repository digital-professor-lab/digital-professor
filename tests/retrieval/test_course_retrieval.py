"""Knowledge preparation -> retrieval: ingested course blocks served by Retrieval V1.

These tests need the Week 3 retrieval code (``scripts/setup_week3.sh``) and the PostgreSQL client packages
it imports. They need no database, no network and no embedding model: a small deterministic encoder
stands in for BGE so the vector channel runs.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from digital_professor.course_context.ingestion import DocumentIngestionService, SourceUpload
from digital_professor.retrieval import course_retrieval
from digital_professor.retrieval.course_retrieval import (
    RetrievalUnavailable,
    ToolCourseRetrieval,
    build_catalog_rows,
    build_course_retrieval,
)
from digital_professor.retrieval.index import CourseRetrievalIndex
from digital_professor.runtime import DemoApplication, TimestampedTraceStore
from digital_professor.webapp.app import create_app

from .course_fixture import SYLLABUS, notes_pdf

retrieval_tool = pytest.importorskip("retrieval_tool")
pytest.importorskip("psycopg", reason="Week 3's search module imports psycopg")
pytest.importorskip("pgvector", reason="Week 3's search module imports pgvector")
try:
    WEEK3_ROOT = retrieval_tool.retrieval_root()
except FileNotFoundError:
    pytest.skip("Week 3 retrieval code is not checked out (scripts/setup_week3.sh)", allow_module_level=True)

from retrieval_tool.schemas import validate_record  # noqa: E402

# Words that mean the same thing for the stand-in encoder, so a paraphrase lands near its passage.
SYNONYMS = {"inside": "inner", "nested": "inner", "biggest": "maximum", "largest": "maximum",
            "smallest": "minimum", "derivative": "differentiate", "differentiable": "differentiate"}


class HashingEncoder:
    """Deterministic bag-of-words vectors. A stand-in for BGE: it exercises the vector channel only."""

    models = ("bge_base_en_v1_5",)

    def __init__(self) -> None:
        self.document_calls = 0

    @staticmethod
    def _vectors(texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in re.findall(r"[a-z]+", text.lower()):
                token = SYNONYMS.get(token, token)
                if len(token) > 3:
                    out[row, int(hashlib.sha256(token.encode()).hexdigest(), 16) % 256] += 1.0
            norm = np.linalg.norm(out[row])
            out[row] /= norm if norm else 1.0
        return out

    def encode_documents(self, key: str, texts: list[str]) -> np.ndarray:
        self.document_calls += 1
        return self._vectors(texts)

    def encode_queries(self, key: str, texts: list[str]) -> np.ndarray:
        return self._vectors(texts)


@pytest.fixture(scope="module")
def workspace():
    return DocumentIngestionService().ingest_course([
        SourceUpload("calculus_syllabus.txt", "text/plain", SYLLABUS),
        SourceUpload("lecture_notes.pdf", "application/pdf", notes_pdf()),
    ])


@pytest.fixture(scope="module")
def index(workspace):
    return ToolCourseRetrieval(workspace, encoder=HashingEncoder(), week3_root=WEEK3_ROOT, cache_dir=None)


def _texts(passages) -> list[str]:
    return [item.passage.text for item in passages]


# --------------------------------------------------------------------------- knowledge preparation
def test_blocks_become_passages_with_page_and_line_locations(workspace) -> None:
    documents, passages, records = build_catalog_rows(workspace)

    assert {d["source_type"] for d in documents.values()} == {"syllabus", "lecture_notes"}
    chain_rule = next(p for p in passages.values() if p["raw_latex"].startswith("Theorem 3.2"))
    assert chain_rule["page_number"] == 1
    assert chain_rule["start_line"] < chain_rule["end_line"]
    assert chain_rule["label"] == "Theorem 3.2 (Chain rule)"
    assert chain_rule["section_path"] == "Chapter 3 Differentiation Rules > 3.2 The Chain Rule"
    assert chain_rule["highlight_url"].startswith(f"/api/courses/{workspace.course_id}/sources/lecture-notes?page=1")
    parts = next(p for p in passages.values() if p["raw_latex"].startswith("Theorem 6.2"))
    assert parts["page_number"] == 3
    # one embedding input per short block, in Week 3's "Course / Section / Content" form
    record = next(r for r in records if r["entity_id"] == chain_rule["passage_id"])
    assert record["input_text"].startswith(
        f"Course: {workspace.course_name}. Section: Chapter 3 Differentiation Rules > 3.2 The Chain Rule. Content: Theorem 3.2")


def test_section_titles_are_not_passages(workspace) -> None:
    _, passages, _ = build_catalog_rows(workspace)
    texts = [p["raw_latex"] for p in passages.values()]
    assert "3.2 The Chain Rule" not in texts
    assert "Chapter 6 Techniques of Integration" not in texts
    assert any(text.startswith("Remark. Students often forget") for text in texts)


def test_long_block_is_split_into_overlapping_embedding_inputs() -> None:
    body = " ".join(f"word{i}" for i in range(500))
    parts = course_retrieval._split_for_embedding("Course: C. Section: S. Content: ", body, None)
    assert len(parts) == 3
    assert all(part.startswith("Course: C. Section: S. Content: ") for part in parts)
    assert "word219" in parts[0] and "word195" in parts[1]          # 25 words of overlap


# --------------------------------------------------------------------------- retrieval at a turn
def test_structured_request_returns_course_passages_with_real_locations(index, workspace) -> None:
    found = index.search("ignored", top_k=4, topic="Chain rule", concept_names=("Chain Rule",),
                         student_message="i dont get this at all", session_id="s1", turn_id="turn-1",
                         question_id="q1", correlation_id="c1")

    assert any(text.startswith("Theorem 3.2 (Chain rule)") for text in _texts(found))
    assert all("chain rule" in text.lower() or "inner function" in text.lower() for text in _texts(found))
    bundle, request = index.last_record, index.last_request
    assert validate_record(request) == [] and validate_record(bundle) == []
    assert request["query_origin"] == "structured"
    assert "dont get this" not in request["query"]                   # student wording is never searched
    assert request["retrieval_snapshot_id"] == index.info.snapshot_id == bundle["retrieval_snapshot_id"]
    assert bundle["retrieval_status"] in ("supported", "partial")
    first = bundle["passages"][0]
    assert re.fullmatch(r"psg_[0-9a-f]{16}", first["passage_id"])
    assert (first["page_number"], first["document_id"]) == (1, "lecture-notes")
    assert first["source_provenance"] == "source_document" and first["document_role"] == "lecture_notes"
    assert first["highlight_url"] == found[0].highlight_url
    assert first["source_label"].startswith("lecture_notes.pdf, p. 1, lines ")
    assert {w["code"] for w in bundle["warnings"]}.isdisjoint({"unverified_source", "location_unavailable",
                                                             "semantic_channel_unavailable"})
    assert bundle["query_interpretation"]["backend"] == "ingested_in_memory"


def test_student_question_without_schema_is_searched_as_student_wording(index) -> None:
    question = "how do I take the derivative of a function inside another function?"
    found = index.search(question, top_k=4, question_prompt=question, student_message=question)

    assert index.last_request["query_origin"] == "student_text"
    assert any(text.startswith(("Theorem 3.2", "Definition 3.2")) for text in _texts(found))


def test_paraphrase_is_found_through_the_vector_channel(index, workspace) -> None:
    question = "how do I find the biggest and smallest value on a closed range of numbers?"
    found = index.search(question, top_k=4, student_message=question)

    assert any(text.startswith("Theorem 4.2 (Closed interval method)") for text in _texts(found))
    counts = index.last_record["query_interpretation"]["channel_candidate_counts"]
    assert counts["bge_base_en_v1_5"] > 0


def test_topic_outside_the_course_is_no_support_found_not_a_guess(index) -> None:
    found = index.search("x", topic="Laplace transform", concept_names=("Laplace Transform",))

    assert found == ()
    assert index.last_record["retrieval_status"] == "no_support_found"
    assert index.last_outcome()["status"] == "no_support_found"


def test_request_for_a_lecture_record_is_stopped_before_search(index) -> None:
    question = "what did the instructor say about the midterm?"
    found = index.search(question, student_message=question)

    assert found == ()
    assert index.last_record["retrieval_status"] == "no_support_found"
    assert "source_class_unavailable" in index.last_outcome()["warnings"]


def test_naming_another_course_does_not_trip_week3_pilot_rules(index) -> None:
    question = "In Calculus II terms, what is integration by parts?"
    found = index.search(question, student_message=question)

    assert index.last_record["record_type"] == "GroundingBundle"
    assert any("Integration by parts" in text for text in _texts(found))


def test_syllabus_is_a_reference_and_is_never_cited(index) -> None:
    found = index.search("x", topic="Grading: homework and exams")
    assert all(item.passage.document_type != "syllabus" for item in found)


def test_keyword_only_index_reports_the_missing_vector_channel(workspace) -> None:
    index = ToolCourseRetrieval(workspace, encoder=None, week3_root=WEEK3_ROOT, cache_dir=None)
    found = index.search("x", topic="Chain rule", concept_names=("Chain Rule",))

    assert index.info.semantic_channel is False
    assert found and "semantic_channel_unavailable" in index.last_outcome()["warnings"]


def test_vectors_are_cached_per_file_version(workspace, tmp_path) -> None:
    class VersionedEncoder(HashingEncoder):
        def cache_tag(self, key: str) -> str:
            return "test-revision"

    first, second = VersionedEncoder(), VersionedEncoder()
    ToolCourseRetrieval(workspace, encoder=first, week3_root=WEEK3_ROOT, cache_dir=tmp_path)
    ToolCourseRetrieval(workspace, encoder=second, week3_root=WEEK3_ROOT, cache_dir=tmp_path)

    assert first.document_calls == 2          # the syllabus and the notes
    assert second.document_calls == 0
    assert list(tmp_path.glob("bge_base_en_v1_5/test-revision/*.npz"))


def test_encoder_without_a_version_never_uses_the_cache(workspace, tmp_path) -> None:
    ToolCourseRetrieval(workspace, encoder=HashingEncoder(), week3_root=WEEK3_ROOT, cache_dir=tmp_path)
    assert not list(tmp_path.rglob("*.npz"))


def test_week3_package_does_not_replace_the_product_package(index) -> None:
    import digital_professor
    import digital_professor.retrieval.index as product_index

    assert "retrieval-tool" not in (digital_professor.__file__ or "")
    assert product_index.CourseRetrievalIndex is CourseRetrievalIndex


# --------------------------------------------------------------------------- choosing the index
def test_keyword_mode_keeps_the_demo_index(workspace) -> None:
    index = build_course_retrieval(workspace, mode="keyword")
    assert isinstance(index, CourseRetrievalIndex)
    assert index.info.mode == "keyword_demo"


def test_auto_mode_falls_back_and_says_why_without_embedding_models(workspace, monkeypatch) -> None:
    monkeypatch.setattr(course_retrieval, "default_encoder", lambda root: None)
    index = build_course_retrieval(workspace, mode="auto")

    assert isinstance(index, CourseRetrievalIndex)
    assert "sentence-transformers is not installed" in index.info.note
    assert index.search("chain rule", top_k=2, topic="Chain rule", session_id="s")   # extra context is accepted


def test_tool_mode_raises_when_week3_code_is_missing(workspace, monkeypatch) -> None:
    def missing() -> None:
        raise FileNotFoundError("no .week3")

    monkeypatch.setattr(retrieval_tool, "retrieval_root", missing)
    with pytest.raises(RetrievalUnavailable, match="setup_week3.sh"):
        build_course_retrieval(workspace, mode="tool")
    assert isinstance(build_course_retrieval(workspace, mode="auto"), CourseRetrievalIndex)


# --------------------------------------------------------------------------- the whole chain in the application
def test_upload_to_grounded_turn_through_retrieval_v1(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DP_RETRIEVAL_MODE", "tool")
    monkeypatch.setattr(course_retrieval, "default_encoder", lambda root: HashingEncoder())
    monkeypatch.setattr(course_retrieval, "VECTOR_CACHE_DIR", tmp_path / "vectors")
    runtime = DemoApplication(None, trace_store=TimestampedTraceStore(tmp_path / "logs"))
    client = TestClient(create_app(runtime=runtime))

    published = client.post("/api/courses", files=[
        ("files", ("calculus_syllabus.txt", SYLLABUS, "text/plain")),
        ("files", ("lecture_notes.pdf", notes_pdf(), "application/pdf")),
    ])
    assert published.status_code == 200, published.text
    course_id = published.json()["course_id"]

    status = client.get("/api/status").json()["retrieval"][course_id]
    assert status["mode"] == "retrieval_tool" and status["semantic_channel"] is True
    assert status["passages"] > 10 and status["models"] == ["bge_base_en_v1_5"]

    session = client.post("/api/sessions", json={
        "course_id": course_id, "question": "How do I differentiate sin(x^2)?", "diagnostic_logging": True})
    assert session.status_code == 200, session.text
    session_id = session.json()["session_id"]
    # A concept question is a move that states course content, so the Engine searches for it.
    turn = client.post(f"/api/sessions/{session_id}/turns",
                       json={"text": "Why do we multiply by the derivative of the inner function?"})
    assert turn.status_code == 200, turn.text

    sources = turn.json()["sources"]
    assert sources and sources[0]["filename"] == "lecture_notes.pdf" and sources[0]["page_number"] == 1
    assert any("Chain rule" in source["excerpt"] for source in sources)
    # The worked example of this very problem is held back until the student has solved it.
    assert not any("sin(x^2)" in source["excerpt"].replace(" ", "") for source in sources)
    page = client.get(sources[0]["highlight_url"])
    assert page.status_code == 200

    events = runtime.trace_store.read_session(session_id)
    retrieval = next(e for e in events if e["event"] == "retrieval_result")
    payload = retrieval["details"]
    assert retrieval["issue"] is None
    assert payload["mode"] == "retrieval_tool" and payload["backend"] == "ingested_in_memory"
    assert payload["status"] in ("supported", "partial")
    assert payload["query_origin"] == "student_text"
