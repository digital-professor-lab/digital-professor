"""End-to-end checks for course ingestion and chained tutoring turns."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from digital_professor.providers import GenerationResult, OpenAICompatibleProvider
from digital_professor.runtime import DemoApplication, TimestampedTraceStore
from digital_professor.webapp.app import create_app
from digital_professor.interaction import RecognizerOutput, StubHandwritingRecognizer


SYLLABUS = b"""110.108 Calculus I
Fall 2026
Course Description
This course introduces derivatives, integrals, the chain rule, and applications.
Grading
Homework 30 percent. Exams 70 percent.
Office Hours
Tuesday afternoon.
"""

NOTES = b"""Lecture 1: The Chain Rule
Definition: For a composite function f(g(x)), differentiate the outer function
and multiply by the derivative of the inner function.
Example
For sin(x^2), the derivative is cos(x^2) times 2x.
Lecture 2: Integration by Parts
The formula is integral u dv = uv - integral v du.
"""


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> GenerationResult:
        self.calls.append(messages)
        return GenerationResult(
            text="Which function is inside the sine, and what is its derivative?",
            model="fake-tutor",
            latency_ms=7,
            input_tokens=40,
            output_tokens=12,
            estimated_cost_usd=0.000052,
        )


def _client(provider=None) -> TestClient:
    return TestClient(create_app(runtime=DemoApplication(provider)))


def _publish(client: TestClient) -> dict:
    response = client.post(
        "/api/courses",
        files=[
            ("files", ("calculus_syllabus.txt", SYLLABUS, "text/plain")),
            ("files", ("lecture_notes.txt", NOTES, "text/plain")),
        ],
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_course_preparation_gate_opens_only_after_ingestion_and_indexing() -> None:
    client = _client()

    before = client.get("/api/status").json()
    assert before["ready_for_query"] is False
    assert before["status"] == "course_setup_required"

    _publish(client)

    after = client.get("/api/status").json()
    assert after["ready_for_query"] is True
    assert after["status"] == "ready"


def test_ingestion_requires_syllabus_and_course_knowledge() -> None:
    client = _client()

    response = client.post(
        "/api/courses",
        files=[("files", ("lecture_notes.txt", NOTES, "text/plain"))],
    )

    assert response.status_code == 422
    assert "syllabus" in response.json()["detail"].lower()


def test_course_ingestion_preserves_source_locations() -> None:
    client = _client()
    course = _publish(client)

    assert course["course_name"] == "Calculus I"
    assert course["course_number"] == "110.108"
    assert course["term"] == "Fall 2026"
    assert {doc["document_type"] for doc in course["documents"]} == {
        "syllabus",
        "lecture_notes",
    }
    assert course["consistency_status"] == "partially_verified"
    assert course["consistency_notes"]


def test_course_ingestion_rejects_explicitly_mismatched_notes() -> None:
    client = _client()
    mismatched_notes = b"""550.413 Linear Algebra Lecture Notes
Lecture 1: Vector spaces
Definition: A vector space is closed under addition and scalar multiplication.
"""

    response = client.post(
        "/api/courses",
        files=[
            ("files", ("calculus_syllabus.txt", SYLLABUS, "text/plain")),
            ("files", ("linear_algebra_notes.txt", mismatched_notes, "text/plain")),
        ],
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "consistency check failed" in detail.lower()
    assert "550.413" in detail
    assert "110.108" in detail


def test_staged_course_ingestion_requires_and_records_mismatch_override() -> None:
    client = _client()
    mismatched_notes = b"""550.413 Linear Algebra Lecture Notes
Lecture 1: Vector spaces
Definition: A vector space is closed under addition and scalar multiplication.
"""
    syllabus = client.post(
        "/api/course-setup/syllabus",
        files={"file": ("calculus_syllabus.txt", SYLLABUS, "text/plain")},
    )
    notes = client.post(
        "/api/course-setup/notes",
        files={"files": ("linear_algebra_notes.txt", mismatched_notes, "text/plain")},
    )
    assert syllabus.status_code == 200
    assert notes.status_code == 200

    paused = client.post("/api/course-setup/publish")

    assert paused.status_code == 409
    detail = paused.json()["detail"]
    assert detail["code"] == "course_mismatch_confirmation_required"
    assert detail["requires_confirmation"] is True
    assert "550.413" in " ".join(detail["conflicts"])

    published = client.post(
        "/api/course-setup/publish?confirm_course_mismatch=true"
    )

    assert published.status_code == 200, published.text
    course = published.json()
    assert course["consistency_status"] == "override_confirmed"
    assert any("Human override confirmed" in note for note in course["consistency_notes"])
    assert any("550.413" in note and "110.108" in note for note in course["consistency_notes"])


def test_course_ingestion_verifies_matching_course_number() -> None:
    client = _client()
    matching_notes = b"""110.108 Calculus I Lecture Notes
Lecture 1: The Chain Rule
Definition: Differentiate the outside and multiply by the inside derivative.
"""

    course = client.post(
        "/api/courses",
        files=[
            ("files", ("calculus_syllabus.txt", SYLLABUS, "text/plain")),
            ("files", ("calculus_notes.txt", matching_notes, "text/plain")),
        ],
    )

    assert course.status_code == 200, course.text
    assert course.json()["consistency_status"] == "verified"


def test_local_tutoring_policy_runs_without_a_paid_provider() -> None:
    runtime = DemoApplication()
    client = TestClient(create_app(runtime=runtime))
    course = _publish(client)
    session = client.post(
        "/api/sessions",
        json={"course_id": course["course_id"], "question": "Explain the chain rule"},
    ).json()

    turn = client.post(
        f"/api/sessions/{session['session_id']}/turns",
        json={"text": "I am stuck and need help."},
    )

    assert turn.status_code == 200, turn.text
    payload = turn.json()
    assert payload["action_type"] == "hint"
    state = runtime.sessions[session["session_id"]].engine.state_snapshot()
    assert state["phase"] == "SUPPORT"
    assert state["help_level"] == 1
    assert "learner_state" not in payload
    assert "cost" not in payload


def test_pdf_syllabus_and_notes_are_extracted_and_published() -> None:
    import pymupdf

    def pdf_bytes(text: str) -> bytes:
        document = pymupdf.open()
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 560, 780), text, fontsize=11)
        data = document.tobytes()
        document.close()
        return data

    client = _client()
    response = client.post(
        "/api/courses",
        files=[
            ("files", ("syllabus.pdf", pdf_bytes(SYLLABUS.decode()), "application/pdf")),
            ("files", ("lecture_notes.pdf", pdf_bytes(NOTES.decode()), "application/pdf")),
        ],
    )

    assert response.status_code == 200, response.text
    assert all(document["page_count"] == 1 for document in response.json()["documents"])


def test_two_posts_share_state_and_link_student_responses() -> None:
    provider = FakeProvider()
    runtime = DemoApplication(provider)
    client = TestClient(create_app(runtime=runtime))
    course = _publish(client)
    session = client.post(
        "/api/sessions",
        json={
            "course_id": course["course_id"],
            "question": "How do I differentiate sin(x^2)?",
            "diagnostic_logging": True,
        },
    ).json()

    first = client.post(
        f"/api/sessions/{session['session_id']}/turns",
        json={"text": "I am stuck on the chain rule."},
    )
    second = client.post(
        f"/api/sessions/{session['session_id']}/turns",
        json={"text": "The inside function is x squared."},
    )

    assert first.status_code == second.status_code == 200
    first_data, second_data = first.json(), second.json()
    assert first_data["turn_id"] == "turn-1"
    assert second_data["turn_id"] == "turn-2"
    assert first_data["sources"]
    assert first_data["sources"][0]["highlight_url"].startswith("/api/courses/")
    assert len(provider.calls) == 2
    assert any(item["role"] == "assistant" for item in provider.calls[1])
    assert first_data["action_type"] == "hint"
    internal = runtime.sessions[session["session_id"]]
    assert internal.total_estimated_cost_usd == 0.000104
    assert internal.prior_evidence_id
    assert internal.prior_action_id
    assert internal.engine.state_snapshot()["status"] == "current"
    for hidden in ("evidence_id", "action_id", "parent_evidence_id", "cost", "learner_state", "trace"):
        assert hidden not in first_data

    restored = client.get(f"/api/sessions/{session['session_id']}")
    assert restored.status_code == 200
    snapshot = restored.json()
    assert snapshot["turn_count"] == 2
    assert [item["role"] for item in snapshot["transcript"]] == [
        "student",
        "assistant",
        "student",
        "assistant",
    ]
    assert snapshot["transcript"][-1]["sources"]


def test_source_link_displays_the_used_line_range() -> None:
    client = _client(FakeProvider())
    course = _publish(client)
    session = client.post(
        "/api/sessions",
        json={"course_id": course["course_id"], "question": "Explain the chain rule"},
    ).json()
    turn = client.post(
        f"/api/sessions/{session['session_id']}/turns",
        json={"text": "Why do we multiply by 2x?"},
    ).json()

    response = client.get(turn["sources"][0]["highlight_url"])

    assert response.status_code == 200
    assert "class=\"line selected\"" in response.text
    assert "Page 1" in response.text


def test_logging_toggle_keeps_operations_but_omits_diagnostics(tmp_path) -> None:
    runtime = DemoApplication(FakeProvider(), trace_store=TimestampedTraceStore(tmp_path / "logs"))
    client = TestClient(create_app(runtime=runtime))
    course = _publish(client)
    session = client.post(
        "/api/sessions",
        json={
            "course_id": course["course_id"],
            "question": "Explain integration by parts",
            "diagnostic_logging": False,
        },
    ).json()
    client.post(
        f"/api/sessions/{session['session_id']}/turns",
        json={"text": "I do not know how to choose u."},
    )

    logs = runtime.sessions[session["session_id"]].logs

    assert logs
    assert all("details" not in event for event in logs)
    assert all(event["diagnostic_logging"] is False for event in logs)
    assert any(event["handoff"] == "interaction -> tutoring_engine" for event in logs)
    assert client.get(f"/api/sessions/{session['session_id']}/logs").status_code == 404
    paths = list((tmp_path / "logs").glob(f"????-??-??/{session['session_id']}/*.json"))
    assert paths
    activity_record = next(
        json.loads(path.read_text())
        for path in paths
        if "turn_activity" in path.name
    )
    assert activity_record["record"]["sources"]
    assert "excerpt" not in activity_record["record"]["sources"][0]
    assert "score" not in activity_record["record"]["sources"][0]


def test_diagnostic_logging_includes_handoffs_sources_and_model_usage(tmp_path) -> None:
    runtime = DemoApplication(FakeProvider(), trace_store=TimestampedTraceStore(tmp_path / "logs"))
    client = TestClient(create_app(runtime=runtime))
    course = _publish(client)
    session = client.post(
        "/api/sessions",
        json={
            "course_id": course["course_id"],
            "question": "Explain the chain rule",
            "diagnostic_logging": True,
        },
    ).json()
    client.post(
        f"/api/sessions/{session['session_id']}/turns",
        json={"text": "I need help."},
    )

    events = runtime.sessions[session["session_id"]].logs

    assert any(event.get("details", {}).get("record_ref") for event in events)
    retrieval = next(event for event in events if event["event"] == "retrieval_result")
    assert retrieval["details"]["sources"][0]["highlight_url"].startswith(
        "/api/courses/"
    )
    generation = next(event for event in events if event["event"] == "model_generation")
    assert generation["details"]["model"] == "fake-tutor"
    assert generation["details"]["input_tokens"] == 40
    assert generation["details"]["estimated_cost_usd"] == 0.000052
    completed = next(event for event in events if event["event"] == "turn_completed")
    assert completed["details"]["duration_ms"] >= 0
    assert completed["details"]["estimated_cost_usd"] == 0.000052
    trace_text = "\n".join(path.read_text() for path in (tmp_path / "logs").glob("**/*.json"))
    assert "QuestionSchema" in trace_text
    public_snapshot = client.get(f"/api/sessions/{session['session_id']}").json()
    assert "question_schema" not in public_snapshot
    assert "cost" not in public_snapshot


def test_activity_reads_backend_records_and_preserves_exact_equation_input(tmp_path) -> None:
    runtime = DemoApplication(
        FakeProvider(), trace_store=TimestampedTraceStore(tmp_path / "logs")
    )
    client = TestClient(create_app(runtime=runtime))
    course = _publish(client)
    session = client.post(
        "/api/sessions",
        json={"course_id": course["course_id"], "question": "Check my equation"},
    ).json()
    original = (
        r"For the chain rule, my step is "
        r"$\alpha + \beta x = \beta_0 + \beta_1 x_1$."
    )

    response = client.post(
        f"/api/sessions/{session['session_id']}/turns", json={"text": original}
    )
    activity = client.get(f"/api/sessions/{session['session_id']}/activity")

    assert response.status_code == activity.status_code == 200
    row = activity.json()["turns"][0]
    assert row["input"] == original
    assert row["recognized_input"] == original
    assert row["decision_summary"]["action_type"]
    assert row["sources"]
    raw_records = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "logs").glob("**/*.json")
    )
    assert original.replace("\\", "\\\\") in raw_records


def test_setup_uses_separate_syllabus_and_notes_requests_and_allows_rename() -> None:
    client = _client()
    syllabus = client.post(
        "/api/course-setup/syllabus",
        files={"file": ("syllabus.txt", SYLLABUS, "text/plain")},
    )
    notes = client.post(
        "/api/course-setup/notes",
        files=[
            ("files", ("notes-1.txt", NOTES, "text/plain")),
            ("files", ("notes-2.txt", b"Lecture 3: Limits", "text/plain")),
        ],
    )
    published = client.post("/api/course-setup/publish")

    assert syllabus.status_code == notes.status_code == published.status_code == 200
    assert len(notes.json()["files"]) == 2
    course = published.json()
    renamed = client.patch(
        f"/api/courses/{course['course_id']}", json={"course_name": "Calculus IA"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["course_name"] == "Calculus IA"


def test_provider_test_reports_missing_env_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = _client()

    response = client.post("/api/provider/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "OPENAI_API_KEY" in response.json()["message"]


def test_runtime_provider_settings_change_without_accepting_a_key() -> None:
    client = _client()

    response = client.put(
        "/api/provider/settings",
        json={
            "provider": "custom",
            "model": "course-tutor-v2",
            "base_url": "https://provider.example/v1",
            "input_cost_per_million": 1.25,
            "output_cost_per_million": 5.0,
            "handwriting_model": "vision-v2",
        },
    )

    assert response.status_code == 200
    status = client.get("/api/status").json()["provider"]
    assert status["model"] == "course-tutor-v2"
    assert status["base_url"] == "https://provider.example/v1"
    assert status["handwriting_model"] == "vision-v2"
    assert "api_key" not in response.json()
    assert "api_key" not in status

    rejected = client.put(
        "/api/provider/settings",
        json={
            "provider": "openai",
            "model": "model",
            "handwriting_model": "vision",
            "api_key": "must-not-be-accepted",
        },
    )
    assert rejected.status_code == 422


def test_provider_catalog_exposes_supported_profiles() -> None:
    client = _client()

    response = client.get("/api/provider/catalog")

    assert response.status_code == 200
    providers = {item["id"]: item for item in response.json()["providers"]}
    assert {"openai", "openrouter", "deepseek", "ollama", "custom"} <= providers.keys()
    assert providers["openrouter"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert providers["ollama"]["requires_api_key"] is False


def test_each_provider_profile_can_be_selected_and_models_loaded(monkeypatch) -> None:
    class Model:
        def __init__(self, model_id: str) -> None:
            self.id = model_id

    class Models:
        def list(self):
            return type("ModelList", (), {"data": [Model("version-b"), Model("version-a")]})()

    class Client:
        models = Models()

    monkeypatch.setattr(OpenAICompatibleProvider, "_client", lambda self: Client())
    client = _client()
    selections = {
        "openai": None,
        "openrouter": None,
        "deepseek": None,
        "ollama": None,
        "custom": "https://models.example/v1",
    }
    for provider, base_url in selections.items():
        settings = client.put(
            "/api/provider/settings",
            json={
                "provider": provider,
                "model": "version-a",
                "base_url": base_url,
                "input_cost_per_million": None,
                "output_cost_per_million": None,
                "handwriting_model": "vision-version-a",
            },
        )
        tested = client.post("/api/provider/test")
        assert settings.status_code == 200, settings.text
        assert tested.status_code == 200
        assert tested.json()["ok"] is True
        assert tested.json()["provider"] == provider
        assert tested.json()["models"] == ["version-a", "version-b"]
        assert tested.json()["configured_model_available"] is True


def test_handwriting_requires_confirmation_then_joins_the_same_session() -> None:
    runtime = DemoApplication(FakeProvider())
    app = create_app(runtime=runtime)
    app.state.handwriting_recognizer = StubHandwritingRecognizer(
        RecognizerOutput(
            provider="test-ocr",
            model_version="ocr-v1",
            recognized_content="$2x\\cos(x^2)$",
            content_format="markdown_tex",
            alternatives=(),
            ambiguities=(),
            observed_steps=(
                {
                    "page_number": 1,
                    "region": "line 1",
                    "content": "$2x\\cos(x^2)$",
                    "crossed_out": False,
                },
            ),
            page_count=1,
            processed_pages=(1,),
            recognition_status="recognized",
            latency_ms=9,
        )
    )
    client = TestClient(app)
    course = _publish(client)
    session = client.post(
        "/api/sessions",
        json={"course_id": course["course_id"], "question": "Differentiate sin(x^2)"},
    ).json()

    recognition = client.post(
        f"/api/sessions/{session['session_id']}/handwriting/recognitions",
        files={"file": ("work.png", b"preserved-image", "image/png")},
    )

    assert recognition.status_code == 200
    assert recognition.json()["recognized_content"] == "$2x\\cos(x^2)$"
    assert runtime.sessions[session["session_id"]].prior_evidence_id is None

    confirmation = client.post(
        f"/api/sessions/{session['session_id']}/handwriting/confirmations",
        json={
            "recognition_id": recognition.json()["recognition_id"],
            "confirmed_content": "$2x\\cos(x^2)$",
            "ambiguity_resolutions": {},
        },
    )

    assert confirmation.status_code == 200, confirmation.text
    snapshot = client.get(f"/api/sessions/{session['session_id']}").json()
    assert snapshot["transcript"][0]["modality"] == "handwriting_upload"
    assert snapshot["turn_count"] == 1
