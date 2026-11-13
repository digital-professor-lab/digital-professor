"""Tool 2 — Review Flagger (Phase 2).

Turns a *validated* CourseContext into a human-review worklist, per
`specs/course-context.validation-and-flagging.md` §4. It never modifies the
file; it reads two signals already in it — the `assumptions` log and
`provenance` — plus the "check first" list from `course-context.md` §2.5.

Rules (relaxed for v1): F-01 restricted to the high-stakes "check-first" fields
the model logged an assumption about; F-03 (wildcard assumptions as global
notes). The blanket F-02 rule is dropped — see flag() for why.
"""
from __future__ import annotations

import hashlib
import json

# "Check first" fields from course-context.md §2.5 (post-AssessmentQuestion):
# (entity, field) -> why a human should look. Only fields that affect tutoring
# correctness are here. Excluded on purpose: duration_weeks / Module.weeks (§2.5
# notes "nothing in V1 logic depends on them").
CHECK_FIRST: dict[tuple[str, str], str] = {
    ("Concept", "difficulty_notes"): "AI-inferred difficulty notes become the misconceptions in every Question Schema.",
    ("Course", "assumed_background"): "Sets what the tutor assumes about every student.",
}

# The generator self-reports a confidence (high/medium/low) per assumption.
# high-confidence items are suppressed: standard inferences a domain expert would
# almost certainly agree with (e.g. "differentiation before integration") don't
# need human review. Only low/medium — genuinely uncertain calls — reach the worklist.
# Items with no confidence value are treated as medium (shown).
_CONFIDENCE_RANK = {"low": 0, "medium": 1, None: 2, "high": 3}


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def flag(cc: dict, source_sha256: str | None = None) -> dict:
    """Return a review report (the §4.3 shape).

    Relaxed for v1 to keep the worklist focused:
    - F-01, restricted to the **check-first** fields (difficulty notes,
      prerequisites, assumed background) the generator logged a low/medium
      assumption about. High-confidence items are suppressed — routine inferences
      a domain expert would almost certainly agree with don't need review.
    - F-03 — wildcard assumptions become global notes.
    The blanket F-02 rule (flag every ai_inferred record's check-first fields) is
    dropped: in a syllabus-only file everything is ai_inferred, so it flagged
    nearly every concept and drowned the signal.
    """
    items: dict[tuple[str, str, str], dict] = {}
    global_notes: list[dict] = []

    def add(entity, rid, field, reason, confidence):
        key = (entity, rid, field)
        if key in items:
            if reason and reason not in items[key]["reason"]:
                items[key]["reason"] = (items[key]["reason"] + " " + reason).strip()
        else:
            items[key] = {"priority": "check_first", "entity": entity, "id": rid,
                          "field": field, "confidence": confidence, "reason": reason}

    for a in cc.get("assumptions", []) or []:
        if not isinstance(a, dict):
            continue
        aid = a.get("id", "")
        entity = a.get("entity", "")
        field = a.get("field", "")
        confidence = a.get("confidence")
        reason = " ".join(x for x in (a.get("assumption"), a.get("reason")) if x).strip()
        if isinstance(aid, str) and aid.endswith(".*"):
            global_notes.append({"field": field, "reason": reason})          # F-03
            continue
        if (entity, field) in CHECK_FIRST and confidence != "high":           # F-01 (check-first, uncertain only)
            add(entity, aid, field, reason, confidence)

    # order by confidence (shakiest first)
    item_list = sorted(items.values(),
                       key=lambda it: (_CONFIDENCE_RANK.get(it.get("confidence"), 2), it["id"], it["field"]))
    summary = {
        "check_first": len(item_list),
        "worth_checking": 0,
        "global_notes": len(global_notes),
    }
    return {
        "course_id": (cc.get("Course") or {}).get("id"),
        "built_from_sha256": source_sha256,
        "summary": summary,
        "items": item_list,
        "global_notes": global_notes,
    }


def format_report(report: dict) -> str:
    s = report["summary"]
    lines = [f"review: check_first={s['check_first']} worth_checking={s['worth_checking']} "
             f"global_notes={s['global_notes']}"]
    for it in report["items"]:
        conf = it.get("confidence") or "n/a"
        lines.append(f"  [{it['priority']} conf={conf}] {it['entity']}:{it['id']}.{it['field']} — {it['reason']}")
    for gn in report["global_notes"]:
        lines.append(f"  [global] {gn['field']} — {gn['reason']}")
    return "\n".join(lines)


def to_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"
