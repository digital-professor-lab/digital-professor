"""JSON Schemas (draft 2020-12) for the three records Retrieval exchanges with other modules.

    RetrievalRequest   consumer: Retrieval   producer: Tutoring Engine / coordinator (built from the tool call)
    GroundingBundle    producer: Retrieval   consumers: Tutoring Engine, main AI model (as a view), Delivery
    RetrievalStop      producer: Retrieval   consumer: Tutoring Engine

They are generated from the constants in the code (purposes, need types, statuses, warning codes, plan
schema), so the schema files (specs/schemas/ in the repository) cannot drift from the implementation:

    python scripts/export_schemas.py        # writes schemas/*.schema.json

Each field description starts with [Contract] (already in interfaces.md V0.1) or [Proposed] (added by
rag-retrieval.md V1, needs team agreement). Cross-field rules that JSON Schema cannot express (ranks
1..n without gaps, every ai_generated passage has an unverified_source warning, component faults are
never no_support_found) are checked in code by `records.check_bundle_invariants`.
"""

from __future__ import annotations

from typing import Any

from .planner import PLAN_SCHEMA
from .records import (COVERAGE, NEED_TYPES, PURPOSES, RETRIEVAL_STATUSES, SCHEMA_VERSION, STOP_REASONS,
                      WARNING_CODES)

BASE = "https://digital-professor-lab.github.io/schemas/"   # identifier only; nothing is fetched from it
ID_STRING = {"type": "string", "minLength": 1}


def _c(text: str) -> str:
    return f"[Contract] {text}"


def _p(text: str) -> str:
    return f"[Proposed] {text}"


def _envelope(record_type: str, statuses: list[str]) -> dict[str, Any]:
    return {
        "record_id": {**ID_STRING, "description": _c("Stable identifier of this record (interfaces.md §1.1).")},
        "record_type": {"const": record_type, "description": _c("Canonical record type.")},
        "schema_version": {"const": SCHEMA_VERSION, "description": _c("Shared contract version.")},
        "created_at": {"type": "string", "format": "date-time", "description": _c("Creation time, UTC, ISO-8601.")},
        "producer": {**ID_STRING, "description": _c("Component that created the record.")},
        "status": {"enum": statuses, "description": _c("Record processing status.")},
        "correlation_id": {**ID_STRING, "description": _c("Connects all records of one turn.")},
    }


ENVELOPE_REQUIRED = ["record_id", "record_type", "schema_version", "created_at", "producer", "status", "correlation_id"]


def _ids(nullable_session: bool = False) -> dict[str, Any]:
    return {
        "course_id": {**ID_STRING, "description": _c("Course scope; passed through unchanged.")},
        "question_id": {**ID_STRING, "description": _c("Question scope; passed through unchanged.")},
        "turn_id": {**ID_STRING, "description": _c("Tutoring turn; passed through unchanged.")},
        "session_id": ({"type": ["string", "null"]} if nullable_session else ID_STRING)
        | {"description": _p("Tutoring session; the citation check matches bundles by session and turn.")},
    }


def retrieval_request_schema() -> dict[str, Any]:
    need = {
        "type": "object", "additionalProperties": False,
        "required": ["need_id", "need_type", "description"],
        "properties": {
            "need_id": {"type": "string", "pattern": "^n[1-9][0-9]*$", "description": _p("n1, n2, … in order.")},
            "need_type": {"enum": list(NEED_TYPES), "description": _p("Kind of evidence needed.")},
            "description": {"type": "string", "minLength": 1, "maxLength": 300,
                            "description": _p("What the passage must state; also searched.")},
            "anchor": {"type": "string", "minLength": 1, "maxLength": 80,
                       "description": _p("Exact term or formula that must appear in a supporting passage.")},
            "concept_ids": {"type": "array", "items": ID_STRING, "description": _p("Primary concepts of the turn.")},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "retrieval-request.schema.json",
        "title": "RetrievalRequest",
        "description": "What the tutoring turn asks Retrieval for (interfaces.md §8 + rag-retrieval.md §5.2). "
                       "Built by the system from the main AI model's tool arguments plus system fields; the model "
                       "never sets course, question, version or exclusions.",
        "x-schema-version": SCHEMA_VERSION,
        "type": "object", "additionalProperties": False,
        "required": [*ENVELOPE_REQUIRED, "retrieval_request_id", "course_id", "question_id", "turn_id", "session_id",
                     "query", "query_origin", "purpose", "evidence_needs"],
        "properties": {
            **_envelope("RetrievalRequest", ["valid"]),
            "retrieval_request_id": {**ID_STRING, "description": _c("Request identity; equals record_id.")},
            **_ids(),
            "query": {"type": "string", "minLength": 1, "maxLength": 2000,
                      "description": _c("Search text in course terms (the tool limits the model to 300 chars).")},
            "query_origin": {"enum": ["structured", "student_text"],
                             "description": _p("student_text when the query copies the student; triggers the "
                                               "free-text scope check.")},
            "purpose": {"enum": list(PURPOSES), "description": _c("Why the material is needed; V1 adds "
                                                                  "definition_lookup, example_lookup, prerequisite_review, "
                                                                  "practice_generation, approach_grounding.")},
            "evidence_needs": {"type": "array", "minItems": 1, "maxItems": 4, "items": need,
                               "description": _p("1–4 typed needs; the evidence check runs per need.")},
            "concept_ids": {"type": "array", "items": ID_STRING,
                            "description": _c("Structured topical filter: the turn's primary concepts.")},
            "concept_names": {"type": "array", "items": ID_STRING,
                              "description": _p("Display names of concept_ids, for the evidence check.")},
            "document_filters": {"type": "object", "description": _c("Allowed document IDs/types/versions. Not used "
                                                                     "by V1.")},
            "evidence_summary": {"type": "string", "maxLength": 500,
                                 "description": _c("Minimum student context needed to retrieve support.")},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 10,
                      "description": _c("Maximum passages; default from the course policy (Week 3: 6).")},
            "max_passage_chars": {"type": "integer", "minimum": 500,
                                  "description": _p("Character budget; default from the course policy (12,000).")},
            "query_language": {"enum": ["en"], "description": _p("V1 is English-only.")},
            "retrieval_snapshot_id": {**ID_STRING, "description": _p("Pinned index version for the session.")},
            "course_context_ref": {"type": "object", "additionalProperties": {"type": "string"},
                                   "description": _p("Course Context identity and version used for the turn.")},
            "scope_check_text": {"type": "string", "maxLength": 2000,
                                 "description": _p("The student's own words, for the scope check only; never "
                                                   "searched or logged as text.")},
            "exclude": {"type": "object", "additionalProperties": False,
                        "required": ["question_ids", "same_problem_as_current"],
                        "properties": {"question_ids": {"type": "array", "items": ID_STRING},
                                       "same_problem_as_current": {"type": "boolean"}},
                        "description": _p("Answer-leak guard for example_lookup / practice_generation.")},
            "retrieval_plan": {"$ref": "#/$defs/RetrievalPlan",
                               "description": _p("The validated plan behind this request (rag-retrieval.md "
                                                 "Appendix C).")},
        },
        "$defs": {"RetrievalPlan": {k: v for k, v in PLAN_SCHEMA.items() if k not in ("$schema",)}},
    }


def _warning() -> dict[str, Any]:
    return {
        "type": "object", "required": ["code", "message"],
        "properties": {
            "code": {"enum": sorted(WARNING_CODES), "description": _p("Machine-readable reason (rag-retrieval.md §8).")},
            "message": {"type": "string"},
            "passage_id": {"type": "string"}, "need_id": {"type": "string"}, "source_id": {"type": "string"},
            "retryable": {"type": "boolean"},
        },
    }


def _passage() -> dict[str, Any]:
    nullable_int = {"type": ["integer", "null"], "minimum": 1}
    return {
        "type": "object", "additionalProperties": False,
        "required": ["passage_id", "document_id", "content_version", "page_number", "line_start", "line_end",
                     "passage_text", "highlight_url", "retrieval_rank"],
        "properties": {
            "passage_id": {"type": "string", "pattern": "^psg_[0-9a-f]{16}$",
                           "description": _c("Stable for a content version: hash of document, version, page, lines.")},
            "document_id": {**ID_STRING, "description": _c("Logical source document.")},
            "content_version": {**ID_STRING, "description": _c("Content version the location is valid for.")},
            "page_number": nullable_int | {"description": _c("Page. null only with a location_unavailable warning "
                                                             "(development corpus); never invented.")},
            "line_start": nullable_int | {"description": _c("First line in normalized page text; null as above.")},
            "line_end": nullable_int | {"description": _c("Last line; null as above.")},
            "passage_text": {"type": "string", "minLength": 1, "description": _c("Exact text used downstream.")},
            "highlight_url": {"type": ["string", "null"], "format": "uri",
                              "description": _c("Opens and highlights the passage; null until ingested pages exist.")},
            "relevance_score": {"type": ["number", "null"],
                                "description": _c("Comparable score if available; V1 returns null (fused ranks are "
                                                  "not calibrated).")},
            "retrieval_rank": {"type": "integer", "minimum": 1, "description": _c("Final rank, 1..n without gaps.")},
            "role": {"enum": ["primary", "context"], "description": _p("primary = returned for the request.")},
            "visibility": {"enum": ["student_visible", "engine_only"], "description": _p("Who may see the text.")},
            "document_role": {"type": "string", "description": _p("e.g. lecture_notes, textbook, ai_course_breakdown.")},
            "source_provenance": {"enum": ["source_document", "ai_generated"],
                                  "description": _p("Where the text comes from.")},
            "review_status": {"enum": ["reviewed", "unverified"], "description": _p("Human review state.")},
            "source_label": {"type": "string", "description": _p("Human-readable source name for display.")},
            "legacy_locator": {"type": "object", "description": _p("Development only: Week 3 file and LaTeX lines.")},
            "known_issues": {"type": "array", "description": _p("Open review issues inside this passage.")},
        },
    }


def grounding_bundle_schema() -> dict[str, Any]:
    status_rule = lambda status, then: {"if": {"properties": {"retrieval_status": {"const": status}}},  # noqa: E731
                                        "then": then}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "grounding-bundle.schema.json",
        "title": "GroundingBundle",
        "description": "Retrieval's answer to one RetrievalRequest (interfaces.md §9 + rag-retrieval.md §7.1). "
                       "Called RetrievedEvidence in JDP-36. Further invariants are checked in code "
                       "(records.check_bundle_invariants).",
        "x-schema-version": SCHEMA_VERSION,
        "type": "object", "additionalProperties": False,
        "required": [*ENVELOPE_REQUIRED, "grounding_bundle_id", "retrieval_request_id", "retrieval_status",
                     "passages", "query_interpretation", "warnings", "course_id", "question_id", "session_id",
                     "turn_id", "retrieval_snapshot_id"],
        "properties": {
            **_envelope("GroundingBundle", ["completed", "failed"]),
            "grounding_bundle_id": {**ID_STRING, "description": _c("Bundle identity; equals record_id.")},
            "retrieval_request_id": {**ID_STRING, "description": _c("The request answered.")},
            **_ids(nullable_session=True),
            "retrieval_status": {"enum": list(RETRIEVAL_STATUSES), "description": _c(
                "supported = every need covered; partial = passages but some needs not covered; no_support_found = "
                "the materials do not cover it or it is out of scope; failed = system fault, retryable.")},
            "retrieval_snapshot_id": {"type": ["string", "null"], "description": _p("Index version searched.")},
            "passages": {"type": "array", "items": {"$ref": "#/$defs/GroundingPassage"},
                         "description": _c("Ranked passages, possibly empty.")},
            "query_interpretation": {"type": ["object", "null"],
                                     "description": _c("Transparent query, filter and plan details.")},
            "warnings": {"type": "array", "items": {"$ref": "#/$defs/Warning"}, "description": _c("Warnings.")},
            "need_coverage": {"type": "array", "items": {"$ref": "#/$defs/NeedCoverage"},
                              "description": _p("Coverage per evidence need.")},
            "uncovered_needs": {"type": "array", "items": {"type": "string"},
                                "description": _p("need_ids whose coverage is not 'covered'.")},
        },
        "allOf": [
            status_rule("supported", {"properties": {"passages": {"minItems": 1}}}),
            status_rule("partial", {"required": ["uncovered_needs"],
                                    "properties": {"passages": {"minItems": 1}, "uncovered_needs": {"minItems": 1}}}),
            status_rule("no_support_found", {"properties": {"passages": {"maxItems": 0}}}),
            status_rule("failed", {"properties": {"passages": {"maxItems": 0}, "status": {"const": "failed"}}}),
        ],
        "$defs": {
            "GroundingPassage": _passage(),
            "Warning": _warning(),
            "NeedCoverage": {
                "type": "object", "additionalProperties": False,
                "required": ["need_id", "coverage", "passage_ids", "method"],
                "properties": {
                    "need_id": {"type": "string"},
                    "coverage": {"enum": list(COVERAGE)},
                    "passage_ids": {"type": "array", "items": {"type": "string"}},
                    "method": {"type": "string", "pattern": "^(pinned|judge|none|rule:[a-z_]+)$",
                               "description": _p("Who decided: human-pinned passage, judge, or the rule for a "
                                                 "need type.")},
                },
            },
        },
    }


def retrieval_stop_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BASE + "retrieval-stop.schema.json",
        "title": "RetrievalStop",
        "description": "[Proposed new shared record] Returned instead of a GroundingBundle when retrieval must not "
                       "run (rag-retrieval.md §7.3). It is never an empty result in disguise.",
        "x-schema-version": SCHEMA_VERSION,
        "type": "object", "additionalProperties": False,
        "required": [*ENVELOPE_REQUIRED, "retrieval_request_id", "stop_reason", "reason_code", "retryable",
                     "policy_version", "course_id", "question_id", "session_id", "turn_id"],
        "properties": {
            **_envelope("RetrievalStop", ["completed"]),
            "retrieval_request_id": {"type": "string", "description": _p("The request stopped ('unknown' if absent).")},
            "course_id": {"type": ["string", "null"], "description": _p("From the request, unchanged.")},
            "question_id": {"type": ["string", "null"], "description": _p("From the request, unchanged.")},
            "session_id": {"type": ["string", "null"], "description": _p("From the request, unchanged.")},
            "turn_id": {"type": ["string", "null"], "description": _p("From the request, unchanged.")},
            "stop_reason": {"enum": list(STOP_REASONS), "description": _p("Why retrieval did not run.")},
            "reason_code": {**ID_STRING, "description": _p("Detail code, e.g. unknown_course, ambiguous_scope.")},
            "retryable": {"type": "boolean", "description": _p("True when a retry can succeed (e.g. after the "
                                                                "student clarifies).")},
            "policy_version": {"type": "string", "description": _p("Course retrieval policy version applied.")},
            "validation_errors": {"type": "array", "items": {
                "type": "object", "required": ["field", "code", "message"],
                "properties": {"field": {"type": "string"}, "code": {"type": "string"}, "message": {"type": "string"}}},
                "description": _c("Field-level errors (interfaces.md §1.4).")},
            "clarification_prompt_hint": {"type": "string",
                                          "description": _p("What to ask the student (needs_clarification).")},
        },
    }


SCHEMAS = {
    "retrieval-request.schema.json": retrieval_request_schema,
    "grounding-bundle.schema.json": grounding_bundle_schema,
    "retrieval-stop.schema.json": retrieval_stop_schema,
}
RECORD_SCHEMA = {"RetrievalRequest": "retrieval-request.schema.json",
                 "GroundingBundle": "grounding-bundle.schema.json",
                 "RetrievalStop": "retrieval-stop.schema.json"}


def validate_record(record: dict[str, Any]) -> list[str]:
    """Validate a record against its schema (needs the `jsonschema` package). Returns readable problems."""
    import jsonschema
    schema = SCHEMAS[RECORD_SCHEMA[record.get("record_type", "")]]()
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    return [f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:200]}"
            for e in sorted(validator.iter_errors(record), key=lambda e: list(e.absolute_path))]
