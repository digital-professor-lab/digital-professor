"""Published courses can be kept across restarts of the local demo (opt-in)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from digital_professor.webapp.app import create_app

SYLLABUS = b"Course: Calculus I\nWeek 1: derivatives and the chain rule.\n"
NOTES = (b"Chain rule. If g is differentiable at x and f is differentiable at g(x), then the derivative of "
         b"f(g(x)) is f'(g(x)) g'(x).\n")
FILES = [("files", ("calculus_syllabus.txt", SYLLABUS, "text/plain")),
         ("files", ("lecture_notes.txt", NOTES, "text/plain"))]


def test_courses_are_not_kept_unless_asked(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DP_COURSE_CACHE", str(tmp_path))
    assert TestClient(create_app()).post("/api/courses", files=FILES).status_code == 200
    assert list(tmp_path.iterdir()) == []
    assert TestClient(create_app()).get("/api/status").json()["courses"] == 0


def test_a_published_course_is_there_again_after_a_restart(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DP_KEEP_COURSES", "1")
    monkeypatch.setenv("DP_COURSE_CACHE", str(tmp_path))
    course = TestClient(create_app()).post("/api/courses", files=FILES).json()

    restarted = TestClient(create_app())                    # a new process would do the same
    status = restarted.get("/api/status").json()
    assert status["courses"] == 1 and course["course_id"] in status["retrieval"]
    session = restarted.post("/api/sessions", json={"course_id": course["course_id"],
                                                    "question": "Differentiate sin(x^3)"})
    assert session.status_code == 200, session.text


def test_a_damaged_saved_course_is_skipped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DP_KEEP_COURSES", "1")
    monkeypatch.setenv("DP_COURSE_CACHE", str(tmp_path))
    (tmp_path / "broken.pkl").write_bytes(b"not a pickle")
    assert TestClient(create_app()).get("/api/status").json()["courses"] == 0
