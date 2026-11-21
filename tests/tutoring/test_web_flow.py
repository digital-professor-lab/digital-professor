"""The Engine inside the web application: turns, the public response and the run log."""

from __future__ import annotations

from fastapi.testclient import TestClient

from digital_professor.runtime import DemoApplication
from digital_professor.webapp.app import create_app

from .helpers import ScriptedProvider, judge_record

SYLLABUS = b"""110.108 Calculus I
Fall 2026
Course Description
This course introduces derivatives, integrals, the chain rule, and applications.
"""
NOTES = b"""Lecture 1: The Chain Rule
For a composite function f(g(x)), differentiate the outer function
and multiply by the derivative of the inner function.
Lecture 2: Integration by Parts
The formula is integral u dv = uv - integral v du.
"""


def test_session_runs_through_the_engine_and_the_run_log_explains_each_step() -> None:
    provider = ScriptedProvider(
        judge=[judge_record("D3", target_gap="correct_approach", final_answer=None,
                            first_issue="the substitution does not simplify a product")],
        writer=["MOVE: ask_plan\nHow would you start this one?",
                "MOVE: point\nLook at how the two factors behave when you differentiate each.",
                "MOVE: ask_reason\nWhat made you choose that for a product of two functions?"])
    runtime = DemoApplication(provider)
    client = TestClient(create_app(runtime=runtime))
    course = client.post("/api/courses", files=[
        ("files", ("calculus_syllabus.txt", SYLLABUS, "text/plain")),
        ("files", ("lecture_notes.txt", NOTES, "text/plain"))]).json()
    question = "Evaluate the integral of x cos(x) dx."
    session = client.post("/api/sessions", json={"course_id": course["course_id"], "question": question}).json()
    turns = f"/api/sessions/{session['session_id']}/turns"

    opening = client.post(turns, json={"text": question}).json()
    assert opening["action_type"] == "elicit" and opening["sources"] == []
    assert opening["message"] == "How would you start this one?"
    help_turn = client.post(turns, json={"text": "I don't know how to start"}).json()
    assert help_turn["action_type"] == "hint" and help_turn["sources"] == []
    wrong = client.post(turns, json={"text": "I tried substitution with u = x cos(x) but it got messy"}).json()
    assert wrong["action_type"] == "probe"
    for hidden in ("learner_state", "action_id", "cost", "trace", "reference_answer"):
        assert hidden not in wrong

    view = client.get(f"/api/sessions/{session['session_id']}/pipeline")
    assert view.status_code == 200, view.text
    first, second, third = view.json()["turns"]
    assert first["flow"] == {"message_type": "OPENING", "verdict": None, "move": "ask_plan", "retrieval": "not_run"}
    assert second["flow"]["move"] == "point" and third["flow"]["verdict"] == "D3"
    titles = [step["title"] for step in third["steps"]]
    assert titles == [
        "Student message received", "Reading: what kind of message is this?",
        "Marking: where is the student now?", "Learning checklist updated",
        "Decision: what situation is this?", "Retrieval tool searches the course material",
        "Writing the reply: the tutor model chooses how to teach", "Reply checks before sending",
        "Delivered and state saved"]
    decision = next(step for step in second["steps"] if step["title"].startswith("Decision"))
    assert "The student asked for help (request 1)." in decision["explain"]
    assert decision["output"]["help_given_so_far"] == "pointed at a feature or a step"
    assert decision["output"]["method_may_be_named"] is False        # stuck once: the tutor points
    later = next(step for step in third["steps"] if step["title"].startswith("Decision"))
    assert later["output"]["method_may_be_named"] is True            # a help request and a wrong attempt
    marking = next(step for step in first["steps"] if step["title"].startswith("Marking"))
    assert marking["explain"] == "Not run: the student has only posed the problem."


def test_placeholder_lesson_plan_does_not_put_a_made_up_method_into_the_goal() -> None:
    runtime = DemoApplication()                                 # no model: the lesson plan is a placeholder
    client = TestClient(create_app(runtime=runtime))
    course = client.post("/api/courses", files=[
        ("files", ("calculus_syllabus.txt", SYLLABUS, "text/plain")),
        ("files", ("lecture_notes.txt", NOTES, "text/plain"))]).json()
    session = client.post("/api/sessions", json={
        "course_id": course["course_id"], "question": "Differentiate sin(x^2)."}).json()
    engine = runtime.sessions[session["session_id"]].engine
    assert engine.qstate.gaps["method"].requirement == "Choose and apply a suitable method for this problem"
