"""Runtime invariants for the small retrieval/status contract (no extra dependency)."""


def validate_report_contract(report: dict) -> None:
    required = {"schema_version", "question", "status", "message", "not_found_reason",
                "scope_assessment", "evidence_assessment", "results", "context", "retrieval_queries"}
    if required - report.keys():
        raise ValueError(f"Retrieval report missing fields: {sorted(required - report.keys())}")
    status = report["status"]
    if status not in {"found", "not_found", "needs_clarification"}:
        raise ValueError("Invalid retrieval status")
    if not isinstance(report["results"], list) or not isinstance(report["context"], str):
        raise ValueError("Results must be a list and context must be text")
    assessment = report["scope_assessment"]
    if assessment["decision"] not in {"retrieve", "not_found", "needs_clarification"}:
        raise ValueError("Invalid request decision")
    if status == "found":
        if not report["results"] or not report["context"] or assessment["decision"] != "retrieve":
            raise ValueError("Found requires evidence and an allowed request")
        if report["not_found_reason"] is not None:
            raise ValueError("Found must not carry a Not found reason")
    else:
        if report["results"] or report["context"]:
            raise ValueError("Blocked/empty retrieval must not hand off answer evidence")
        if status == "not_found" and not report["not_found_reason"]:
            raise ValueError("Not found requires a reason")
        if status == "needs_clarification" and (assessment["decision"] != status or report["not_found_reason"] is not None):
            raise ValueError("Clarification must be distinguished from Not found")
    for result in report["results"]:
        if not isinstance(result["score"], (int, float)) or not result["raw_latex"]:
            raise ValueError("Evidence requires a numeric ranking score and original text")
        if result["line_start"] > result["line_end"]:
            raise ValueError("Invalid evidence source span")
    if report["evidence_assessment"]["status"] not in {"not_assessed", "no_selected_evidence"}:
        raise ValueError("This retriever cannot claim semantic evidence sufficiency")
