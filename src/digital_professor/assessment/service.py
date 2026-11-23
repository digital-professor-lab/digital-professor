"""One-question-at-a-time, note-grounded assessment coordination."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime, timezone
import re
from typing import Any, Protocol
from uuid import uuid4

from digital_professor.course_context.ingestion import CourseWorkspace
from digital_professor.interaction import InMemoryArtifactStore, StudentEvidencePipeline
from digital_professor.interaction.models import StudentEvidence, TypedSubmissionInput
from digital_professor.retrieval.index import CourseRetrievalIndex, RetrievedPassage

from .models import (
    AssessmentEngineHandoff,
    AssessmentEvaluation,
    AssessmentQuestion,
    AssessmentSessionState,
    DifficultyDecision,
    QuestionRating,
)
from .ports import AssessmentTutoringEnginePort


QUESTION_TYPES = {"multiple_choice", "true_false", "open_ended"}
RATINGS = {"too_easy", "just_right", "too_hard"}
NOTE_TYPES = frozenset({"lecture_notes"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


class TraceStore(Protocol):
    def write(self, session_id: str, event: dict[str, Any]) -> Any: ...


class AssessmentError(ValueError):
    """Structured assessment failure with an API-safe code."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class AssessmentService:
    """Coordinate assessment without taking over Interaction or Retrieval ownership."""

    def __init__(
        self,
        courses: dict[str, CourseWorkspace],
        indexes: dict[str, CourseRetrievalIndex],
        trace_store: TraceStore,
        *,
        tutoring_engine_port: AssessmentTutoringEnginePort | None = None,
        clock: Callable[[], str] = _now,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self.courses = courses
        self.indexes = indexes
        self.trace_store = trace_store
        self.tutoring_engine_port = tutoring_engine_port
        self._clock = clock
        self._id = id_factory
        self.sessions: dict[str, AssessmentSessionState] = {}
        self._evidence_pipeline = StudentEvidencePipeline(InMemoryArtifactStore())

    def start(
        self,
        *,
        course_id: str,
        concept: str,
        allowed_question_types: tuple[str, ...],
        starting_difficulty: int = 2,
        user_id: str = "local-demo-student",
        diagnostic_logging: bool = False,
        tutoring_history_signal: dict[str, Any] | None = None,
        linked_tutoring_session_id: str | None = None,
    ) -> dict[str, Any]:
        course = self.courses.get(course_id)
        index = self.indexes.get(course_id)
        if course is None or index is None:
            raise AssessmentError("course_not_found", f"Published course not found: {course_id}", status_code=404)
        selected_types = tuple(dict.fromkeys(allowed_question_types))
        if not selected_types or any(value not in QUESTION_TYPES for value in selected_types):
            raise AssessmentError("invalid_question_types", "Choose at least one supported question type.")
        if not 1 <= starting_difficulty <= 5:
            raise AssessmentError("invalid_difficulty", "Starting difficulty must be between 1 and 5.")
        clean_concept = concept.strip()
        if not clean_concept:
            raise AssessmentError("concept_required", "Choose a concept from the course notes.")
        content_versions = "+".join(
            document.content_version
            for document in course.documents
            if document.document_type == "lecture_notes"
        )
        if not content_versions:
            raise AssessmentError(
                "insufficient_grounding",
                "Assessment requires at least one lecture-notes source; syllabus and textbook content are not eligible in V1.",
            )
        assessment_id = self._id("assessment")
        state = AssessmentSessionState(
            assessment_session_id=assessment_id,
            course_id=course_id,
            session_id=assessment_id,
            user_id=user_id,
            created_at=self._clock(),
            correlation_id=self._id("correlation"),
            allowed_question_types=selected_types,
            target_concept=clean_concept,
            current_difficulty=starting_difficulty,
            course_context_version=content_versions,
            retrieval_snapshot_id=f"local-index-{content_versions}",
            diagnostic_logging=diagnostic_logging,
            tutoring_history_signal=tutoring_history_signal or {
                "summary_ref": None,
                "prerequisite_gap_active": None,
                "recent_help_level": None,
            },
            linked_tutoring_session_id=linked_tutoring_session_id,
        )
        self.sessions[assessment_id] = state
        self._event(state, "assessment_started", {"concept": clean_concept})
        question = self._generate_next_question(state)
        return self.snapshot(assessment_id, include_restricted=False, question=question)

    def submit_response(self, assessment_id: str, response: str) -> dict[str, Any]:
        state = self._state(assessment_id)
        question = state.active_question
        if question is None or state.status != "active":
            raise AssessmentError("no_active_question", "There is no active assessment question.", status_code=409)
        clean_response = response.strip()
        if not clean_response:
            raise AssessmentError("response_required", "Enter a response before submitting.")
        turn_id = f"assessment-turn-{state.question_number}"
        request = TypedSubmissionInput(
            user_id=state.user_id,
            course_id=state.course_id,
            session_id=state.session_id,
            turn_id=turn_id,
            question_id=question.question_id,
            attempt_id=question.attempt_id,
            submitted_text=response,
            evidence_kind="initial_attempt",
            consent_flags={"diagnostic_logging": state.diagnostic_logging},
        )
        submission = self._evidence_pipeline.capture_typed_submission(request)
        evidence = self._evidence_pipeline.build_student_evidence(submission, request)
        response_time_ms, timing_quality = _elapsed(question.presented_at, self._clock())
        evaluation = self._evaluate(state, question, evidence, response_time_ms, timing_quality)
        state.active_question = replace(question, status="evaluated")
        state.evaluations.append(evaluation)
        state.status = "awaiting_rating"
        self._event(
            state,
            "assessment_response_received",
            {
                "question_id": question.assessment_question_id,
                "submission_id": submission.submission_id,
                "evidence_id": evidence.evidence_id,
                "preserved_input": response,
                "response_time_ms": response_time_ms,
                "timing_quality": timing_quality,
            },
        )
        self._event(
            state,
            "assessment_evaluated",
            {
                "question_id": question.assessment_question_id,
                "evaluation": _evaluation_dict(evaluation),
            },
        )
        return {
            "assessment_session_id": assessment_id,
            "status": state.status,
            "evaluation": _evaluation_dict(evaluation),
            "rating_options": ["too_easy", "just_right", "too_hard"],
        }

    def rate_and_continue(
        self,
        assessment_id: str,
        *,
        rating: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        state = self._state(assessment_id)
        if state.status != "awaiting_rating" or not state.evaluations or state.active_question is None:
            raise AssessmentError("rating_not_expected", "A question result must be awaiting a rating.", status_code=409)
        if rating not in RATINGS:
            raise AssessmentError("invalid_rating", "Rating must be too_easy, just_right, or too_hard.")
        evaluation = state.evaluations[-1]
        question = state.active_question
        rating_record = QuestionRating(
            record_id=self._id("rating"),
            record_type="QuestionRating",
            schema_version="0.1",
            created_at=self._clock(),
            producer="assessment",
            status="recorded",
            correlation_id=state.correlation_id,
            rating_id="",
            assessment_session_id=state.assessment_session_id,
            assessment_question_id=question.assessment_question_id,
            evaluation_id=evaluation.evaluation_id,
            user_id=state.user_id,
            perceived_difficulty=rating,
            comment=(comment or "").strip() or None,
            submitted_at=self._clock(),
        )
        rating_record = replace(rating_record, rating_id=rating_record.record_id)
        decision = self._difficulty_decision(state, question, evaluation, rating_record)
        state.ratings.append(rating_record)
        state.difficulty_decisions.append(decision)
        state.completed_questions.append(replace(question, status="closed"))
        state.active_question = None
        state.current_difficulty = decision.next_level
        state.status = "ready"
        self._event(state, "assessment_rating_recorded", {"rating": asdict(rating_record)})
        self._event(state, "assessment_difficulty_decided", {"decision": asdict(decision)})
        engine_handoff = self._handoff_to_tutoring_engine(
            state, question, evaluation, rating_record, decision
        )
        next_question = self._generate_next_question(state)
        return {
            "assessment_session_id": assessment_id,
            "difficulty_decision": asdict(decision),
            "question": _public_question(next_question),
            "tutoring_engine_handoff": engine_handoff,
            "status": state.status,
        }

    def snapshot(
        self,
        assessment_id: str,
        *,
        include_restricted: bool = False,
        question: AssessmentQuestion | None = None,
    ) -> dict[str, Any]:
        state = self._state(assessment_id)
        active = question or state.active_question
        result: dict[str, Any] = {
            "assessment_session_id": state.assessment_session_id,
            "course_id": state.course_id,
            "status": state.status,
            "current_difficulty": state.current_difficulty,
            "target_concept": state.target_concept,
            "completed_question_count": len(state.completed_questions),
            "question": _public_question(active) if active else None,
            "evaluation": _evaluation_dict(state.evaluations[-1]) if state.status == "awaiting_rating" and state.evaluations else None,
            "session_record": self._session_record(state),
        }
        if include_restricted and active:
            result["restricted_question"] = asdict(active)
        return result

    def end(self, assessment_id: str) -> dict[str, Any]:
        state = self._state(assessment_id)
        state.active_question = None
        state.status = "complete"
        scores = [
            value.correctness_score
            for value in state.evaluations[: len(state.completed_questions)]
            if value.correctness_score is not None
        ]
        enough = bool(state.completed_questions)
        summary_id = self._id("assessment-summary")
        question_results = []
        for index, question in enumerate(state.completed_questions):
            evaluation = state.evaluations[index]
            rating = state.ratings[index] if index < len(state.ratings) else None
            question_results.append(
                {
                    "assessment_question_id": question.assessment_question_id,
                    "evaluation_id": evaluation.evaluation_id,
                    "question_type": question.question_type,
                    "difficulty_level": question.difficulty_level,
                    "correctness_score": evaluation.correctness_score,
                    "rating_id": rating.rating_id if rating else None,
                }
            )
        concept_evidence = []
        if enough:
            concept_evidence.append(
                {
                    "concept_id": state.target_concept,
                    "assessment_question_ids": [
                        item.assessment_question_id for item in state.completed_questions
                    ],
                    "observation_count": len(state.completed_questions),
                    "evidence_status": _evidence_status(scores, len(state.completed_questions)),
                    "score_range": {
                        "minimum": min(scores),
                        "maximum": max(scores),
                    }
                    if scores
                    else None,
                    "limitations": [
                        "This is assessment evidence, not a certified mastery determination."
                    ],
                }
            )
        summary = {
            "record_id": summary_id,
            "record_type": "AssessmentSummary",
            "schema_version": "0.1",
            "created_at": self._clock(),
            "producer": "assessment",
            "status": "completed" if enough else "insufficient_evidence",
            "correlation_id": state.correlation_id,
            "assessment_summary_id": summary_id,
            "assessment_session_id": state.assessment_session_id,
            "course_id": state.course_id,
            "session_id": state.session_id,
            "user_id": state.user_id,
            "completed_question_count": len(state.completed_questions),
            "question_results": question_results,
            "concept_evidence": concept_evidence,
            "difficulty_history": [
                {
                    "assessment_question_id": question.assessment_question_id,
                    "difficulty_decision_id": decision.difficulty_decision_id,
                    "presented_level": decision.previous_level,
                    "next_level": decision.next_level,
                }
                for question, decision in zip(
                    state.completed_questions, state.difficulty_decisions, strict=False
                )
            ],
            "content_versions": state.course_context_version.split("+"),
            "retrieval_snapshot_id": state.retrieval_snapshot_id,
            "limitations": [
                "V1 uses deterministic term matching and does not certify mastery."
            ],
            "summary_policy_version": "assessment-summary@0.1",
        }
        self._event(state, "assessment_completed", {"summary": summary})
        return summary

    def activity(self, assessment_id: str) -> list[dict[str, Any]]:
        return list(self._state(assessment_id).activity)

    def _generate_next_question(self, state: AssessmentSessionState) -> AssessmentQuestion:
        if state.active_question is not None:
            raise AssessmentError("active_question_exists", "Complete the active question before generating another.", status_code=409)
        index = self.indexes[state.course_id]
        passages = index.search(
            state.target_concept,
            top_k=4,
            document_types=set(NOTE_TYPES),
        )
        if not passages:
            state.status = "paused"
            self._event(state, "assessment_paused", {"reason": "insufficient_grounding"})
            raise AssessmentError(
                "insufficient_grounding",
                f"No lecture-note passage supports the selected concept: {state.target_concept}.",
            )
        if any(item.passage.document_type != "lecture_notes" for item in passages):
            raise AssessmentError("source_policy_violation", "Assessment grounding contained a disallowed source type.")
        state.question_number += 1
        question_type = state.allowed_question_types[
            (state.question_number - 1) % len(state.allowed_question_types)
        ]
        question = self._local_question(state, passages, question_type)
        state.active_question = replace(question, status="active", presented_at=self._clock())
        state.status = "active"
        self._event(
            state,
            "assessment_question_presented",
            {"question": _public_question(state.active_question)},
        )
        return state.active_question

    def _local_question(
        self,
        state: AssessmentSessionState,
        passages: tuple[RetrievedPassage, ...],
        question_type: str,
    ) -> AssessmentQuestion:
        primary = passages[0]
        source_text = primary.passage.text.strip()
        sentence = _sentence_for_difficulty(source_text, state.current_difficulty)
        terms = _keywords(source_text)[: max(3, min(8, 2 + state.current_difficulty))]
        choices: tuple[dict[str, str], ...] = ()
        if question_type == "true_false":
            prompt = f"True or false according to the lecture notes: {sentence}"
            answer_key: dict[str, Any] = {
                "correct_boolean": True,
                "required_elements": [sentence],
                "acceptable_equivalents": ["true", "t"],
            }
        elif question_type == "multiple_choice":
            alternatives = [_first_sentence(item.passage.text) for item in passages[1:4]]
            while len(alternatives) < 2:
                alternatives.append(
                    f"The lecture notes do not connect {state.target_concept} to any defined method."
                )
            options = [sentence, *alternatives[:3]]
            choices = tuple(
                {"choice_id": chr(65 + index), "content_latex": value}
                for index, value in enumerate(options)
            )
            prompt = f"Which statement is supported by the lecture notes about {state.target_concept}?"
            answer_key = {
                "correct_choice_ids": ["A"],
                "required_elements": [sentence],
                "acceptable_equivalents": [sentence],
            }
        else:
            instruction = {
                1: "State its basic definition or meaning.",
                2: "State the main idea and the relevant definition or method.",
                3: "Explain the method and describe when it applies.",
                4: "Explain the method, its conditions, and a meaningful connection to another idea in the notes.",
                5: "Analyze the method, its conditions, and a limitation or consequence supported by the notes.",
            }[state.current_difficulty]
            prompt = f"Using the course notes, explain {state.target_concept}. {instruction}"
            answer_key = {
                "expected_answer_latex": source_text,
                "required_elements": terms,
                "acceptable_equivalents": [],
            }
        dimensions = (
            ("concept", 0.35, True),
            ("method", 0.25, question_type == "open_ended"),
            ("execution", 0.25, False),
            ("communication", 0.15, False),
        )
        rubric = {
            "rubric_version": "assessment-rubric@0.1",
            "dimensions": [
                {
                    "dimension": name,
                    "weight": weight,
                    "criteria": f"Demonstrates {name} using the frozen answer key and lecture notes.",
                    "critical": critical,
                }
                for name, weight, critical in dimensions
            ],
        }
        grounding = tuple(_source_ref(item) for item in passages)
        question_id = self._id("assessment-question")
        return AssessmentQuestion(
            record_id=question_id,
            record_type="AssessmentQuestion",
            schema_version="0.1",
            created_at=self._clock(),
            producer="assessment",
            status="validated",
            correlation_id=state.correlation_id,
            assessment_question_id=question_id,
            assessment_session_id=state.assessment_session_id,
            question_id=question_id,
            attempt_id=self._id("attempt"),
            course_id=state.course_id,
            concept_ids=(state.target_concept,),
            objective_ids=(f"runtime-objective-{_slug(state.target_concept)}",),
            difficulty_level=state.current_difficulty,
            question_type=question_type,
            prompt_latex=prompt,
            choices=choices,
            answer_key=answer_key,
            rubric=rubric,
            grounding_refs=grounding,
            content_versions=tuple(dict.fromkeys(ref["content_version"] for ref in grounding)),
            retrieval_snapshot_id=state.retrieval_snapshot_id,
            expected_time_ms=120_000,
        )

    def _evaluate(
        self,
        state: AssessmentSessionState,
        question: AssessmentQuestion,
        evidence: StudentEvidence,
        response_time_ms: int | None,
        timing_quality: str,
    ) -> AssessmentEvaluation:
        response = evidence.confirmed_content or ""
        normalized = response.strip().lower()
        answer = question.answer_key
        if question.question_type == "true_false":
            expected = bool(answer["correct_boolean"])
            observed = normalized in {"true", "t", "yes"}
            base = 1.0 if observed == expected else 0.0
            correct = ("The truth value matches the lecture notes.",) if base == 1 else ()
            incorrect = () if base == 1 else ("The selected truth value does not match the lecture notes.",)
            partial: tuple[str, ...] = ()
            omitted: tuple[str, ...] = ()
        elif question.question_type == "multiple_choice":
            correct_ids = {value.lower() for value in answer["correct_choice_ids"]}
            base = 1.0 if normalized in correct_ids else 0.0
            correct = ("The selected option matches the note-grounded answer.",) if base == 1 else ()
            incorrect = () if base == 1 else ("The selected option is not the note-grounded answer.",)
            partial = ()
            omitted = ()
        else:
            required = [term.lower() for term in answer.get("required_elements", [])]
            matched = [term for term in required if re.search(rf"\b{re.escape(term)}\b", normalized)]
            base = len(matched) / len(required) if required else 0.0
            correct = tuple(f"Included the key idea: {term}." for term in matched)
            missing = [term for term in required if term not in matched]
            incorrect = ()
            partial = ("The response contains some, but not all, note-grounded elements.",) if 0 < base < 1 else ()
            omitted = tuple(f"Missing the note-grounded element: {term}." for term in missing)
        communication = min(1.0, len(response.split()) / 20) if question.question_type == "open_ended" else 1.0
        method = base if question.question_type == "open_ended" else base
        execution = base
        values = {
            "concept": base,
            "method": method,
            "execution": execution,
            "communication": communication,
        }
        results: list[dict[str, Any]] = []
        total = 0.0
        for dimension in question.rubric["dimensions"]:
            name = dimension["dimension"]
            earned = round(values[name], 4)
            weight = float(dimension["weight"])
            total += earned * weight
            status = "correct" if earned >= 0.8 else "partial" if earned > 0 else "incorrect"
            results.append(
                {
                    "dimension": name,
                    "weight": weight,
                    "earned": earned,
                    "status": status,
                    "explanation": f"{name.title()} evidence was {status} against the frozen rubric.",
                    "grounding_refs": list(question.grounding_refs),
                }
            )
        score = round(total, 4)
        if score >= 0.8:
            summary = "Your response is well supported by the lecture notes."
        elif score >= 0.5:
            summary = "Your response is partially correct; review the missing elements below."
        else:
            summary = "Your response needs revision using the cited lecture-note passage."
        feedback = (
            f"{summary} Score: {score:.2f}. "
            + " ".join((*correct, *partial, *incorrect, *omitted))
        ).strip()
        evaluation = AssessmentEvaluation(
            record_id=self._id("evaluation"),
            record_type="AssessmentEvaluation",
            schema_version="0.1",
            created_at=self._clock(),
            producer="assessment",
            status="completed",
            correlation_id=state.correlation_id,
            evaluation_id="",
            assessment_session_id=state.assessment_session_id,
            assessment_question_id=question.assessment_question_id,
            question_id=question.question_id,
            attempt_id=question.attempt_id,
            evidence_id=evidence.evidence_id,
            correctness_score=score,
            dimension_results=tuple(results),
            correct_elements=correct,
            partial_elements=partial,
            incorrect_elements=incorrect,
            omitted_elements=omitted,
            feedback_latex=feedback,
            grounding_refs=question.grounding_refs,
            response_time_ms=response_time_ms,
            timing_quality=timing_quality,
            review_status="not_required",
            limitations=("V1 local evaluation uses frozen rubric term matching; model/math-checker review is not yet enabled.",),
        )
        return replace(evaluation, evaluation_id=evaluation.record_id)

    def _difficulty_decision(
        self,
        state: AssessmentSessionState,
        question: AssessmentQuestion,
        evaluation: AssessmentEvaluation,
        rating: QuestionRating,
    ) -> DifficultyDecision:
        score = evaluation.correctness_score or 0.0
        critical_incorrect = any(
            item["dimension"] in {"concept", "method"} and item["status"] == "incorrect"
            for item in evaluation.dimension_results
        )
        history = state.tutoring_history_signal
        prerequisite_gap = history.get("prerequisite_gap_active") is True
        help_level = history.get("recent_help_level")
        previous = state.current_difficulty
        timing = _timing_signal(
            evaluation.response_time_ms,
            evaluation.timing_quality,
            question.expected_time_ms,
        )
        slow_with_struggle = timing["relative_band"] == "slower" and score < 0.7
        strong_and_not_slow = score >= 0.8 and timing["relative_band"] != "slower"
        self_reported_easy_with_support = (
            score >= 0.65
            and rating.perceived_difficulty == "too_easy"
            and timing["relative_band"] != "slower"
        )
        if (
            score < 0.5
            or prerequisite_gap
            or rating.perceived_difficulty == "too_hard"
            or slow_with_struggle
        ):
            next_level = max(1, previous - 1)
            rationale = "Decrease one level to reinforce missing or difficult material."
        elif (
            (strong_and_not_slow or self_reported_easy_with_support)
            and not critical_incorrect
            and rating.perceived_difficulty != "too_hard"
            and (help_level is None or help_level <= 2)
        ):
            next_level = min(5, previous + 1)
            rationale = "Increase one level after a strong response without a critical gap."
        else:
            next_level = previous
            rationale = "Keep the current level and reinforce the target concept."
        missing = tuple(
            name
            for name, absent in (
                ("timing", evaluation.timing_quality != "valid"),
                ("tutoring_history", history.get("summary_ref") is None),
            )
            if absent
        )
        decision = DifficultyDecision(
            record_id=self._id("difficulty"),
            record_type="DifficultyDecision",
            schema_version="0.1",
            created_at=self._clock(),
            producer="assessment",
            status="completed" if not missing else "partial",
            correlation_id=state.correlation_id,
            difficulty_decision_id="",
            assessment_session_id=state.assessment_session_id,
            assessment_question_id=question.assessment_question_id,
            evaluation_id=evaluation.evaluation_id,
            previous_level=previous,
            next_level=next_level,
            correctness_signal={"score": score, "critical_dimension_incorrect": critical_incorrect},
            timing_signal=timing,
            student_rating=rating.perceived_difficulty,
            tutoring_history_signal=history,
            missing_signals=missing,
            rationale=rationale,
        )
        return replace(decision, difficulty_decision_id=decision.record_id)

    def _handoff_to_tutoring_engine(
        self,
        state: AssessmentSessionState,
        question: AssessmentQuestion,
        evaluation: AssessmentEvaluation,
        rating: QuestionRating,
        decision: DifficultyDecision,
    ) -> dict[str, Any]:
        """Publish facts; leave diagnosis and action selection to the Engine."""
        handoff = AssessmentEngineHandoff(
            handoff_id=self._id("assessment-handoff"),
            assessment_session_id=state.assessment_session_id,
            linked_tutoring_session_id=state.linked_tutoring_session_id,
            course_id=state.course_id,
            assessment_question_id=question.assessment_question_id,
            question_id=question.question_id,
            evidence_id=evaluation.evidence_id,
            evaluation_id=evaluation.evaluation_id,
            rating_id=rating.rating_id,
            difficulty_decision_id=decision.difficulty_decision_id,
            concept_ids=question.concept_ids,
            correctness_score=evaluation.correctness_score,
            dimension_results=evaluation.dimension_results,
            correct_elements=evaluation.correct_elements,
            partial_elements=evaluation.partial_elements,
            incorrect_elements=evaluation.incorrect_elements,
            omitted_elements=evaluation.omitted_elements,
            timing_quality=evaluation.timing_quality,
            student_rating=rating.perceived_difficulty,
            recommended_focus=_recommended_focus(evaluation),
            grounding_refs=evaluation.grounding_refs,
            created_at=self._clock(),
        )
        state.engine_handoffs.append(handoff)
        result: dict[str, Any] = {
            "handoff_id": handoff.handoff_id,
            "status": "pending_engine_integration",
            "linked_tutoring_session_id": handoff.linked_tutoring_session_id,
            "recommended_focus": handoff.recommended_focus,
            "tutoring_action_id": None,
            "tutoring_action_type": None,
        }
        if self.tutoring_engine_port is not None:
            try:
                action = self.tutoring_engine_port.record_assessment_result(handoff)
                result["status"] = "recorded"
                if action is not None:
                    result["status"] = "action_selected"
                    result["tutoring_action_id"] = action.action_id
                    result["tutoring_action_type"] = action.action_type
            except Exception as error:  # adapter failures must not lose the assessment
                result["status"] = "engine_handoff_failed"
                result["error_type"] = type(error).__name__
        self._event(state, "assessment_engine_handoff", result)
        return result

    def _state(self, assessment_id: str) -> AssessmentSessionState:
        state = self.sessions.get(assessment_id)
        if state is None:
            raise AssessmentError("assessment_not_found", f"Assessment session not found: {assessment_id}", status_code=404)
        return state

    def _session_record(self, state: AssessmentSessionState) -> dict[str, Any]:
        return {
            "record_id": state.assessment_session_id,
            "record_type": "AssessmentSession",
            "schema_version": "0.1",
            "created_at": state.created_at,
            "producer": "assessment",
            "status": state.status,
            "correlation_id": state.correlation_id,
            "assessment_session_id": state.assessment_session_id,
            "course_id": state.course_id,
            "session_id": state.session_id,
            "user_id": state.user_id,
            "allowed_question_types": list(state.allowed_question_types),
            "target_scope": {
                "scope_type": "concepts",
                "concept_ids": [state.target_concept],
                "objective_ids": [],
            },
            "current_difficulty": state.current_difficulty,
            "active_question_id": state.active_question.assessment_question_id
            if state.active_question
            else None,
            "completed_question_ids": [
                item.assessment_question_id for item in state.completed_questions
            ],
            "course_context_version": state.course_context_version,
            "retrieval_snapshot_id": state.retrieval_snapshot_id,
            "question_count_goal": None,
            "paused_reason": None,
        }

    def _event(self, state: AssessmentSessionState, event: str, details: dict[str, Any]) -> None:
        row = {
            "created_at": self._clock(),
            "event": event,
            "assessment_session_id": state.assessment_session_id,
            "course_id": state.course_id,
            "status": state.status,
            "details": details,
        }
        state.activity.append(row)
        self.trace_store.write(state.session_id, row)


def _public_question(question: AssessmentQuestion | None) -> dict[str, Any] | None:
    if question is None:
        return None
    return {
        "assessment_question_id": question.assessment_question_id,
        "question_id": question.question_id,
        "question_type": question.question_type,
        "difficulty_level": question.difficulty_level,
        "prompt_latex": question.prompt_latex,
        "choices": list(question.choices),
        "concept_ids": list(question.concept_ids),
        "status": question.status,
    }


def _evaluation_dict(evaluation: AssessmentEvaluation) -> dict[str, Any]:
    result = asdict(evaluation)
    result["grounding_refs"] = list(evaluation.grounding_refs)
    return result


def _source_ref(item: RetrievedPassage) -> dict[str, Any]:
    passage = item.passage
    if passage.document_type != "lecture_notes":
        raise AssessmentError("source_policy_violation", "Assessment may only cite lecture notes in V1.")
    return {
        "passage_id": passage.passage_id,
        "document_id": passage.document_id,
        "filename": passage.filename,
        "source_type": passage.document_type,
        "content_version": passage.content_version,
        "page_number": passage.page_number,
        "line_start": passage.line_start,
        "line_end": passage.line_end,
        "highlight_url": item.highlight_url,
    }


def _elapsed(start: str | None, end: str) -> tuple[int | None, str]:
    if start is None:
        return None, "unknown"
    try:
        started = datetime.fromisoformat(start.replace("Z", "+00:00"))
        ended = datetime.fromisoformat(end.replace("Z", "+00:00"))
        value = max(0, round((ended - started).total_seconds() * 1000))
    except ValueError:
        return None, "unknown"
    return value, "valid"


def _timing_signal(value: int | None, quality: str, expected: int | None) -> dict[str, Any]:
    if quality != "valid" or value is None or expected is None:
        return {"quality": quality, "response_time_ms": value, "relative_band": "excluded"}
    band = "faster" if value < expected * 0.6 else "slower" if value > expected * 1.5 else "expected"
    return {"quality": quality, "response_time_ms": value, "relative_band": band}


def _keywords(text: str) -> list[str]:
    stop = {"about", "after", "before", "course", "from", "have", "into", "lecture", "notes", "that", "their", "there", "these", "this", "using", "which", "with"}
    values = [value.lower() for value in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)]
    return list(dict.fromkeys(value for value in values if value not in stop))


def _first_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    match = re.match(r"(.{1,500}?[.!?])(?:\s|$)", cleaned)
    return match.group(1) if match else cleaned[:500]


def _sentence_for_difficulty(text: str, level: int) -> str:
    cleaned = " ".join(text.split())
    sentences = [
        value.strip()
        for value in re.findall(r"[^.!?]{1,500}[.!?](?:\s|$)", cleaned)
        if value.strip()
    ]
    if not sentences:
        return _first_sentence(cleaned)
    return sentences[min(level - 1, len(sentences) - 1)]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "concept"


def _evidence_status(scores: list[float], count: int) -> str:
    if count < 2 or not scores:
        return "insufficient_evidence"
    average = sum(scores) / len(scores)
    if average >= 0.8 and min(scores) >= 0.65:
        return "consistently_demonstrated"
    if average < 0.5:
        return "needs_reinforcement"
    return "mixed"


def _recommended_focus(evaluation: AssessmentEvaluation) -> str:
    """Name the weakest measured dimension without selecting a tutoring action."""
    if not evaluation.dimension_results:
        return "insufficient_evidence"
    priority = {"concept": 0, "method": 1, "execution": 2, "communication": 3}
    weakest = min(
        evaluation.dimension_results,
        key=lambda item: (float(item.get("earned", 0.0)), priority.get(str(item.get("dimension")), 99)),
    )
    return str(weakest.get("dimension", "insufficient_evidence"))

