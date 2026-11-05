"""T4 citation check (rag-retrieval.md §7.12) and the model-facing view of a bundle.

The model sees short labels ([P1], [P2], ...) instead of long passage IDs. After the model answers,
labels are mapped back to passage IDs and every cited passage must
  * come from a GroundingBundle of the same session and turn,
  * come from a bundle whose status is supported or partial,
  * support a need that the bundle reports as covered (partially covered is accepted with a
    warning while the evidence check runs on rules only [Proposed, development setting]).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Tutor-facing wording for preflight outcomes (the Week 3 explanations are written for developers)
TUTOR_REASONS = {
    "excluded_scope": "The student asked about material outside this course (another course, or a part not in this course).",
    "source_class_unavailable": "This course has no such source (for example lecture recordings or individual student records).",
    "no_eligible_sources": "No approved course material is available for this course yet.",
    "query_language_unsupported": "Course search works in English only.",
}
SCOPE_CODES = {"excluded_scope", "source_class_unavailable"}

LABEL = re.compile(r"\[(P\d+(?:\s*,\s*P\d+)*)\]")


@dataclass
class CitationMap:
    """Per-turn label ↔ passage_id map; labels continue across several tool calls in one turn."""

    label_to_passage: dict[str, str] = field(default_factory=dict)

    def label_for(self, passage_id: str) -> str:
        for label, pid in self.label_to_passage.items():
            if pid == passage_id:
                return label
        label = f"P{len(self.label_to_passage) + 1}"
        self.label_to_passage[label] = passage_id
        return label


def model_view(record: dict[str, Any], citations: CitationMap, request: dict[str, Any] | None = None,
               fallback: str = "") -> dict[str, Any]:
    """Compact tool result for the LLM: status, labelled passages, uncovered needs, what to do next.

    Passages that support no stated need are shown as context with `citable: false`; the citation check
    rejects them anyway, so telling the model up front avoids a rewrite.
    """
    if record["record_type"] == "RetrievalStop":
        return {"retrieval_status": "stopped", "stop_reason": record["stop_reason"], "reason_code": record["reason_code"],
                "instructions": ("Do not cite course materials this turn. "
                                 + ("Ask the student to clarify which course or part of the course they mean. "
                                    if record["stop_reason"] == "needs_clarification" else "")
                                 + (f"Fallback: {fallback}" if fallback else ""))}
    needs = {n["need_id"]: n for n in (request or {}).get("evidence_needs", [])}
    coverage = {c["need_id"]: c for c in record.get("need_coverage") or []}
    passages = []
    for p in record["passages"]:
        supports = [f"{nid} ({c['coverage']})" for nid, c in coverage.items()
                    if p["passage_id"] in c["passage_ids"] and c["coverage"] != "not_covered"]
        passages.append({"label": citations.label_for(p["passage_id"]), "citable": bool(supports),
                         "source": p.get("source_label"), "supports_needs": supports, "text": p["passage_text"][:1800]})
    status = record["retrieval_status"]
    uncovered = [needs.get(n, {}).get("description", n) for n in record.get("uncovered_needs") or []]
    code = next((w["code"] for w in record["warnings"] if w["code"] in TUTOR_REASONS), None)
    reason = TUTOR_REASONS.get(code)
    if status == "supported":
        how = "Ground course-specific statements in the citable passages and cite their labels, e.g. [P1]."
    elif status == "partial":
        how = ("Cite a citable passage only for the need it supports; never cite a passage with citable=false. "
               "For the uncovered needs, do not claim the course materials say anything. "
               + (f"Fallback: {fallback}" if fallback else ""))
    elif status == "no_support_found" and code in SCOPE_CODES:
        how = (f"{reason} Tell the student this plainly, do not cite anything, and do not search again this turn. "
               "Then steer back to the current question.")
    elif status == "no_support_found":
        how = ("The course materials do not cover this" + (f" ({reason})" if reason else "") + ". Do not cite anything. "
               + (f"Fallback: {fallback}" if fallback else ""))
    else:
        how = "Retrieval failed (system fault). Do not cite anything. " + (f"Fallback: {fallback}" if fallback else "")
    view = {"retrieval_status": status, "passages": passages, "uncovered_needs": uncovered, "instructions": how.strip()}
    if any(w["code"] == "unverified_source" for w in record["warnings"]):
        view["source_note"] = "Development corpus: AI-prepared, unverified course outline (topic lists, few full statements)."
    return view


def strip_labels(text: str, labels: list[str]) -> str:
    """Remove invalid citation labels and tidy the punctuation they leave behind (", , ", "( )", " .")."""
    for label in labels:
        text = re.sub(rf"\[{label}\]", "", text)
        text = re.sub(rf"(?<=[\[,])\s*{label}\s*,?|,\s*{label}(?=\s*\])", "", text)   # inside [P1, P9]
    text = re.sub(r"\[\s*,?\s*\]", "", text)
    text = re.sub(r"\(\s*(?:see|cf\.?|e\.g\.,?)?\s*[,;]?\s*\)", "", text)
    text = re.sub(r"(?:,\s*){2,}", ", ", text)
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    text = re.sub(r"(\b(?:in|see|from|and))\s*,", r"\1", text)
    text = re.sub(r",\s*(and|or)\b", r" \1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_labels(text: str) -> list[str]:
    labels: list[str] = []
    for group in LABEL.findall(text or ""):
        for label in re.split(r"\s*,\s*", group):
            if label not in labels:
                labels.append(label)
    return labels


def verify_grounding_refs(passage_ids: list[str], bundles: list[dict[str, Any]], *, session_id: str | None,
                          turn_id: str, allow_partial: bool = True) -> dict[str, Any]:
    accepted, rejected, warnings = [], [], []
    turn_bundles = [b for b in bundles if b.get("turn_id") == turn_id and b.get("session_id") == session_id]
    for pid in passage_ids:
        owner = next((b for b in turn_bundles if any(p["passage_id"] == pid for p in b["passages"])), None)
        if owner is None:
            rejected.append({"passage_id": pid, "code": "citation_not_from_turn_bundle"})
            continue
        if owner["retrieval_status"] not in ("supported", "partial"):
            rejected.append({"passage_id": pid, "code": "citation_not_from_turn_bundle"})
            continue
        levels = [c["coverage"] for c in owner.get("need_coverage") or [] if pid in c["passage_ids"]]
        if "covered" in levels:
            accepted.append(pid)
        elif "partially_covered" in levels and allow_partial:
            accepted.append(pid)
            warnings.append({"passage_id": pid, "code": "citation_need_partially_covered"})
        else:
            rejected.append({"passage_id": pid, "code": "citation_need_not_covered"})
    return {"ok": not rejected, "accepted": accepted, "rejected": rejected, "warnings": warnings}
