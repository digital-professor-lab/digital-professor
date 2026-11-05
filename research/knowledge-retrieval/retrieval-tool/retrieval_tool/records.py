"""Shared records for the retrieval tool, following `interfaces.md` V0.1 and `rag-retrieval.md` V1.

Records are plain dicts so they serialize to the team's JSON examples unchanged.
Fields marked [Proposed] in the V1 spec are included but optional.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "0.1"
PRODUCER = "retrieval"

# --- vocabularies -------------------------------------------------------------
RETRIEVAL_STATUSES = ("supported", "partial", "no_support_found", "failed")
STOP_REASONS = ("invalid_request", "needs_clarification", "course_not_ready", "version_mismatch")

# interfaces.md §8 + [Proposed] additions in rag-retrieval.md §2.2
PURPOSES = (
    "answer_grounding", "diagnosis_support", "hint_support", "citation_check",
    "definition_lookup", "example_lookup", "prerequisite_review", "practice_generation",
    "approach_grounding",
)
# rag-retrieval.md §6.4
NEED_TYPES = (
    "formula_statement", "definition", "theorem_statement", "worked_example", "exercise",
    "method_guidance", "prerequisite_explanation", "notation_convention", "course_policy",
)
COVERAGE = ("covered", "partially_covered", "not_covered")
TUTORING_ACTIONS = (
    "elicit", "probe", "inspect", "diagnose", "hint", "contrast", "explain", "demonstrate",
    "retry", "verify", "check_understanding", "transfer",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def envelope(record_type: str, *, record_id: str, correlation_id: str, status: str,
             producer: str = PRODUCER) -> dict[str, Any]:
    return {
        "record_id": record_id, "record_type": record_type, "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(), "producer": producer, "status": status,
        "correlation_id": correlation_id,
    }


def passage_identity(document_id: str, content_version: str, page_number: int | None,
                     line_start: int, line_end: int) -> str:
    """rag-retrieval.md §5.1: deterministic hash of the five location values (includes content_version)."""
    key = f"{document_id}|{content_version}|{page_number}|{line_start}|{line_end}"
    return "psg_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def warning(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **{k: v for k, v in extra.items() if v is not None}}


def grounding_bundle(*, request: dict[str, Any], retrieval_status: str, passages: list[dict[str, Any]],
                     warnings: list[dict[str, Any]], need_coverage: list[dict[str, Any]] | None = None,
                     query_interpretation: dict[str, Any] | None = None,
                     snapshot_id: str | None = None) -> dict[str, Any]:
    if retrieval_status not in RETRIEVAL_STATUSES:
        raise ValueError(f"unknown retrieval_status {retrieval_status}")
    bundle_id = new_id("gb")
    bundle = {
        **envelope("GroundingBundle", record_id=bundle_id, correlation_id=request["correlation_id"],
                   status="failed" if retrieval_status == "failed" else "completed"),
        "grounding_bundle_id": bundle_id,
        "retrieval_request_id": request["retrieval_request_id"],
        "retrieval_status": retrieval_status,
        "retrieval_snapshot_id": snapshot_id or request.get("retrieval_snapshot_id"),
        "passages": passages,
        "query_interpretation": query_interpretation,
        "warnings": warnings,
        # identifiers of the request, passed through unchanged (interfaces.md §1.2); session/turn scope is
        # also what the T4 citation check matches on
        "course_id": request.get("course_id"),
        "question_id": request.get("question_id"),
        "session_id": request.get("session_id"),
        "turn_id": request["turn_id"],
    }
    if need_coverage is not None:
        bundle["need_coverage"] = need_coverage
        bundle["uncovered_needs"] = [n["need_id"] for n in need_coverage if n["coverage"] != "covered"]
    return bundle


def retrieval_stop(*, request: dict[str, Any], stop_reason: str, reason_code: str, retryable: bool,
                   policy_version: str, validation_errors: list[dict[str, Any]] | None = None,
                   clarification_prompt_hint: str | None = None) -> dict[str, Any]:
    if stop_reason not in STOP_REASONS:
        raise ValueError(f"unknown stop_reason {stop_reason}")
    stop_id = new_id("rs")
    record = {
        **envelope("RetrievalStop", record_id=stop_id, correlation_id=request.get("correlation_id", "unknown"),
                   status="completed"),
        "retrieval_request_id": request.get("retrieval_request_id", "unknown"),
        "stop_reason": stop_reason, "reason_code": reason_code, "retryable": retryable,
        "policy_version": policy_version,
        "course_id": request.get("course_id"),
        "question_id": request.get("question_id"),
        "session_id": request.get("session_id"),
        "turn_id": request.get("turn_id"),
    }
    if validation_errors:
        record["validation_errors"] = validation_errors
    if clarification_prompt_hint:
        record["clarification_prompt_hint"] = clarification_prompt_hint
    return record


def check_bundle_invariants(bundle: dict[str, Any]) -> list[str]:
    """rag-retrieval.md §8.1 invariants; returns a list of violations (empty = OK)."""
    problems = []
    status, passages = bundle["retrieval_status"], bundle["passages"]
    needs = bundle.get("need_coverage") or []
    if status == "supported" and (not passages or any(n["coverage"] != "covered" for n in needs)):
        problems.append("supported requires passages and every need covered")
    if status == "partial" and (not passages or not bundle.get("uncovered_needs")):
        problems.append("partial requires passages and uncovered_needs")
    if status in ("no_support_found", "failed") and passages:
        problems.append(f"{status} must have no passages")
    if [p["retrieval_rank"] for p in passages] != list(range(1, len(passages) + 1)):
        problems.append("retrieval_rank must be 1..n without gaps")
    for p in passages:
        if p.get("source_provenance") == "ai_generated" and not any(
                w["code"] == "unverified_source" and w.get("passage_id") == p["passage_id"]
                for w in bundle["warnings"]):
            problems.append(f"{p['passage_id']} is ai_generated without unverified_source warning")
    if status == "no_support_found" and any(w["code"] in COMPONENT_FAULT_CODES for w in bundle["warnings"]):
        problems.append("component faults must not be reported as no_support_found")
    return problems


COMPONENT_FAULT_CODES = {"index_unavailable", "encoder_unavailable", "index_encoder_mismatch",
                         "resolver_unavailable", "timeout"}

# Every warning code a GroundingBundle may carry (rag-retrieval.md §8). The JSON Schema uses this list as an
# enum, so a new code must be added here first. "reserved" codes are in the spec but not emitted by V1 yet.
WARNING_CODES = {
    # sources and provenance
    "unverified_source": "emitted", "location_unavailable": "emitted", "source_quality_warning": "emitted",
    "reference_only": "emitted", "no_ingested_sources": "emitted", "no_eligible_sources": "emitted",
    "stale_version": "reserved", "revoked_source": "reserved", "text_mismatch": "reserved",
    # scope and request
    "excluded_scope": "emitted", "source_class_unavailable": "emitted", "query_language_unsupported": "emitted",
    # quality and budget
    "sufficiency_uncertain": "emitted", "budget_truncated": "emitted", "semantic_channel_unavailable": "emitted",
    # component faults (always with retrieval_status = failed)
    "index_unavailable": "emitted", "encoder_unavailable": "emitted", "index_encoder_mismatch": "emitted",
    "resolver_unavailable": "reserved", "timeout": "reserved",
}
