"""Explainable request-scope policy; no model confidence or benchmark labels."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal


Decision = Literal["retrieve", "not_found", "needs_clarification"]


@dataclass
class RequestAssessment:
    decision: Decision = "retrieve"
    category: str = "within_selected_scope"
    reason_code: str | None = None
    requested_scopes: list[str] = field(default_factory=list)
    required_source_types: list[str] = field(default_factory=list)
    available_source_types: list[str] = field(default_factory=list)
    matched_rules: list[dict[str, str]] = field(default_factory=list)
    next_action: str = "retrieve"
    explanation: str = "No explicit scope or source requirement blocks retrieval; evidence sufficiency is not assessed."

    def to_dict(self) -> dict:
        result = asdict(self)
        result["policy_version"] = "2"
        return result


def active_mentions(pattern: str, question: str) -> list[str]:
    """Do not treat explicit exclusions or background study as requested scopes."""
    values = []
    for match in re.finditer(pattern, question, re.IGNORECASE):
        before = question[max(0, match.start() - 50):match.start()]
        after = question[match.end():match.end() + 50]
        if re.search(r"(?:\bnot|\bwithout|\bexcluding|\bexclude|\brather than|不要|不是|不使用)\s*(?:(?:from|in|using|the|material from|content from)\s+)?$", before, re.IGNORECASE):
            continue
        if (re.search(r"\b(?:studied|completed|took|heard about)\s*$", before, re.IGNORECASE)
                and re.search(r"\b(?:but|however)\b", after, re.IGNORECASE)):
            continue
        values.append(match.group())
    return values


def assess_request(question: str, *, include_unconfirmed: bool,
                   include_outside_course: bool, source_types: set[str],
                   course_id: str | None = None) -> RequestAssessment:
    assessment = RequestAssessment(available_source_types=sorted(source_types))
    calc1 = active_mentions(r"\bcalculus\s*(?:i|1)\b|微积分\s*(?:I(?!I)|Ⅰ|一|1)", question)
    calc2 = active_mentions(r"\bcalculus\s*(?:ii|2)\b|微积分\s*(?:II|Ⅱ|二|2)", question)
    number = active_mentions(r"\bnumber theory(?:\s*(?:i|1))?\b|数论", question)
    semester = active_mentions(r"\bsecond[ -]semester\b|第二学期", question)
    if calc1:
        assessment.requested_scopes.append("calc1")
    if calc2:
        assessment.requested_scopes.append("calc2")
    if number:
        assessment.requested_scopes.append("number_theory_1")
    if semester:
        assessment.requested_scopes.append("second_semester")

    def stop(decision: Decision, category: str, reason: str, action: str,
             explanation: str, rule: str, matched: str) -> RequestAssessment:
        assessment.decision, assessment.category = decision, category
        assessment.reason_code, assessment.next_action = reason, action
        assessment.explanation = explanation
        assessment.matched_rules.append({"rule": rule, "matched_text": matched})
        return assessment

    # A mixed or conflicting request needs a choice, not a blanket rejection.
    if calc2 and not include_outside_course:
        if calc1 or number:
            return stop("needs_clarification", "mixed_scope", "mixed_allowed_and_excluded_scopes",
                        "clarify_scope", "The request names both available and excluded course scopes. Narrow the request or explicitly opt into outside-course material.",
                        "mixed_course_scope", "; ".join(calc1 + calc2 + number))
        return stop("not_found", "out_of_scope", "outside_course_scope", "change_scope",
                    "Calculus II evidence is excluded by the current request settings; the material is not necessarily absent from the catalog.",
                    "excluded_calculus_ii", calc2[0])
    if course_id and (((calc1 or calc2) and course_id != "calc1") or (number and course_id != "number_theory_1")):
        return stop("needs_clarification", "filter_conflict", "course_filter_conflict", "clarify_scope",
                    "The named course conflicts with the selected course filter.", "named_course_filter_conflict", "; ".join(calc1 + number))
    if semester and not include_unconfirmed:
        if number or course_id == "number_theory_1" or re.search(r"\bunconfirmed\b", question, re.IGNORECASE):
            return stop("not_found", "out_of_scope", "unconfirmed_semester_scope", "confirm_scope",
                        "The requested number-theory semester has not been confirmed for this pilot. Explicit opt-in is required.",
                        "unconfirmed_number_theory_semester", semester[0])
        if not calc1 and not calc2:
            return stop("needs_clarification", "ambiguous_scope", "semester_course_unspecified", "clarify_scope",
                        "A second semester was requested without identifying its course. Semester numbering alone cannot determine scope.",
                        "semester_without_course", semester[0])

    lecture = re.search(r"\b(?:lecture transcript|lecture recording)\b|课堂原话|课堂录音", question, re.IGNORECASE)
    if not lecture:
        exact = re.search(r"\b(?:exact words|verbatim)\b|逐字记录", question, re.IGNORECASE)
        instructor = re.search(r"\b(?:instructor|professor|teacher|lecture)\b|老师|课堂", question, re.IGNORECASE)
        utterance = re.search(r"\b(?:what|which).*\b(?:instructor|professor|teacher)\b.*\b(?:say|said)\b|老师.*(?:说了什么|原话)", question, re.IGNORECASE)
        lecture = utterance or (exact if exact and instructor else None)
    if lecture and not re.search(r"\b(?:without|not requesting|do not need)\b.*\b(?:transcript|recording|verbatim)\b", question, re.IGNORECASE):
        assessment.required_source_types.append("lecture_record")

    grade = re.search(r"\b(?:score|grade|mark)\b|成绩|得分", question, re.IGNORECASE)
    personal = re.search(r"\b(?:my|his|her|their|your|student(?:'s)?)\s+(?:score|grade|mark)\b|我的成绩|学生.*(?:成绩|得分)", question, re.IGNORECASE)
    named_student = re.search(r"\bstudent\s+[A-Z][a-z]+\b", question)
    named_result = re.search(r"\b(?:[Dd]id|[Hh]as)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:receive|earn|get|score)\b", question)
    # Lowercase names also count when a past-result request is explicit.
    past_student = re.search(r"\b(?:did|received|earned|got)\b", question, re.IGNORECASE) and re.search(r"\bstudent\s+\w+", question, re.IGNORECASE)
    if grade and (personal or named_student or past_student or named_result):
        assessment.required_source_types.append("student_record")
    missing = [role for role in assessment.required_source_types if role not in source_types]
    if missing:
        reason = "lecture_record_unavailable" if missing == ["lecture_record"] else "student_record_unavailable" if missing == ["student_record"] else "required_sources_unavailable"
        return stop("not_found", "source_unavailable", reason, "request_source",
                    "The selected course catalog lacks the requested source type(s): " + ", ".join(missing) + ". Course summaries cannot establish these facts.",
                    "required_source_missing", (lecture.group() if lecture else grade.group()))
    return assessment


def query_facets(question: str) -> list[str]:
    """Decompose explicit multi-part wording without inventing facts or reading gold labels."""
    comparison = re.match(r"\s*(?:compare|contrast)\s+(.+?)\s+(?:with|versus|vs\.?|and)\s+(.+?)[?.]?\s*$", question, re.IGNORECASE)
    if comparison:
        return [part.strip().rstrip(".?") + "." for part in comparison.groups()]
    application = re.match(r"\s*(.+?),?\s+and\s+(?:where|how)\s+(?:does|is|can)\s+(.+)", question, re.IGNORECASE)
    if application:
        primary = application.group(1).rstrip(" ,?.")
        return [primary + "?", "Applications and examples: " + primary + "."]
    return []
