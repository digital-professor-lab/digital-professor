"""Tool 1 — Validator (Phase 2).

Checks a generated CourseContext against the conformance rules in
`specs/course-context.validation-and-flagging.md` §3. Pure function of the
input: no network, no model, deterministic. Every finding is an ERROR (blocks
publication) or a WARN (reported, does not block).

Rules implemented (spec IDs): V-01..V-10. V-10 here enforces only the two useful
checks — provenance is present and is a valid enum value; the weakest-link
"source_backed vs an assumptions entry" check is intentionally dropped.
Warnings (W-01, W-02) are disabled in v1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --- schema knowledge (mirrors course-context.md §1.2 / §1.3) ---------------

ARRAYS = ["Module", "Concept", "LearningObjective", "Source"]
TOP_LEVEL_REQUIRED = ["course_context_schema_version", "Course", *ARRAYS]
TOP_LEVEL_OPTIONAL = ["assumptions"]

# required fields per record (schema 1.0 core; `provenance` is added in 1.1)
REQUIRED: dict[str, list[str]] = {
    "Course": ["id", "title", "level", "duration_weeks", "assumed_background", "module_ids"],
    "Module": ["id", "course_id", "title", "goal", "weeks", "concept_ids"],
    "Concept": ["id", "module_id", "name", "summary", "key_definitions",
                "prerequisite_ids", "objective_ids", "difficulty_notes", "source_ids"],
    "LearningObjective": ["id", "concept_id", "text", "bloom_level"],
    "Source": ["id", "type", "citation", "section", "text_chunk"],
}
# array fields that MUST hold at least one element (everything else may be empty)
NONEMPTY_ARRAYS = {"Course": ["module_ids"], "Module": ["concept_ids"]}
# array fields allowed to be empty (MUST* in the spec)
STAR_ARRAYS = {"key_definitions", "prerequisite_ids", "objective_ids",
               "difficulty_notes", "source_ids"}

BLOOM = {"remember", "understand", "apply", "analyze", "evaluate", "create"}
SOURCE_TYPE = {"syllabus", "textbook", "lecture_notes", "reading", "other"}
PROVENANCE = {"source_backed", "ai_inferred"}
ASSUMPTION_KEYS = {"entity", "id", "field", "assumption", "reason"}
CONFIDENCE = {"high", "medium", "low"}          # optional per-assumption self-rating

WEEKS_RE = re.compile(r"^\d+(-\d+)?$")
LO_RE = re.compile(r"\.lo\d+$")


@dataclass
class Finding:
    rule: str
    severity: str          # "error" | "warn"
    where: str             # e.g. "Concept:calc1.02-limits.continuity"
    message: str

    def line(self) -> str:
        tag = "ERROR" if self.severity == "error" else "WARN "
        return f"{tag} {self.rule} {self.where}: {self.message}"


def counts(cc: dict) -> dict[str, int]:
    out = {k: len(cc.get(k, []) or []) for k in ARRAYS}
    out["assumptions"] = len(cc.get("assumptions", []) or [])
    return out


def validate(cc: object) -> list[Finding]:
    """Return every ERROR/WARN finding for a CourseContext dict."""
    f: list[Finding] = []

    # V-01 — top-level shape. If this fails badly, deeper rules can't run.
    if not isinstance(cc, dict):
        return [Finding("V-01", "error", "<file>", "top level is not a JSON object")]
    _v01_top_level(cc, f)

    ver = str(cc.get("course_context_schema_version", "")).strip()
    is_11 = ver == "1.1"

    # collect records and id indexes
    records = _record_list(cc)                       # [(type, record), ...]
    ids_by_type = _ids_by_type(records)
    all_ids = {rid for s in ids_by_type.values() for rid in s}

    _v02_v08_fields(cc, records, is_11, f)           # presence / unknown / empties / TBD
    _v03_enums(records, is_11, f)                    # enums + weeks/duration/difficulty shape
    _v04_ids(cc, records, f)                         # uniqueness + id patterns
    _v05_references(cc, records, ids_by_type, f)     # links resolve
    _v06_reverse_links(cc, records, f)               # forward/reverse agree
    _v07_prerequisites(cc, f)                        # acyclic + ordering
    _v09_assumptions(cc, all_ids, f)                 # assumptions shape + resolve
    _v10_provenance(cc, records, is_11, f)           # provenance present + valid enum
    return f


# --- rule implementations ---------------------------------------------------

def _v01_top_level(cc: dict, f: list[Finding]) -> None:
    keys = set(cc.keys())
    allowed = set(TOP_LEVEL_REQUIRED) | set(TOP_LEVEL_OPTIONAL)
    for k in TOP_LEVEL_REQUIRED:
        if k not in keys:
            f.append(Finding("V-01", "error", "<file>", f"missing top-level key {k!r}"))
    for k in keys - allowed:
        f.append(Finding("V-01", "error", "<file>", f"unexpected top-level key {k!r}"))
    ver = str(cc.get("course_context_schema_version", "")).strip()
    if ver and not re.match(r"^1\.\d+$", ver):
        f.append(Finding("V-01", "error", "<file>",
                         f"course_context_schema_version {ver!r} is not 1.x"))


def _v02_v08_fields(cc: dict, records, is_11: bool, f: list[Finding]) -> None:
    for rtype, rec in records:
        where = f"{rtype}:{rec.get('id', '?')}" if isinstance(rec, dict) else rtype
        if not isinstance(rec, dict):
            f.append(Finding("V-02", "error", rtype, "record is not an object"))
            continue
        allowed = set(REQUIRED[rtype]) | {"provenance"}
        # V-02 required present + unknown fields + provenance/version coupling
        for field in REQUIRED[rtype]:
            if field not in rec:
                f.append(Finding("V-02", "error", where, f"missing required field {field!r}"))
        for field in set(rec.keys()) - allowed:
            f.append(Finding("V-02", "error", where, f"unknown field {field!r}"))
        if "provenance" in rec and not is_11:
            f.append(Finding("V-02", "error", where,
                             "provenance present but course_context_schema_version is not 1.1"))
        # V-08 empties / TBD
        for field in REQUIRED[rtype]:
            if field not in rec:
                continue
            val = rec[field]
            if field in STAR_ARRAYS:
                continue                              # empty allowed
            if field in NONEMPTY_ARRAYS.get(rtype, []):
                if not isinstance(val, list) or len(val) == 0:
                    f.append(Finding("V-08", "error", where, f"{field} must have at least one entry"))
                continue
            if val is None or (isinstance(val, str) and val.strip() in ("", "TBD")):
                f.append(Finding("V-08", "error", where, f"{field} is empty or 'TBD'"))


def _v03_enums(records, is_11: bool, f: list[Finding]) -> None:
    for rtype, rec in records:
        if not isinstance(rec, dict):
            continue
        where = f"{rtype}:{rec.get('id', '?')}"
        if rtype == "LearningObjective" and rec.get("bloom_level") not in BLOOM:
            f.append(Finding("V-03", "error", where, f"bloom_level {rec.get('bloom_level')!r} not in {sorted(BLOOM)}"))
        if rtype == "Source" and rec.get("type") not in SOURCE_TYPE:
            f.append(Finding("V-03", "error", where, f"Source.type {rec.get('type')!r} not in {sorted(SOURCE_TYPE)}"))
        if rtype == "Course":
            dw = rec.get("duration_weeks")
            if not isinstance(dw, int) or isinstance(dw, bool) or dw < 1:
                f.append(Finding("V-03", "error", where, f"duration_weeks {dw!r} is not an integer >= 1"))
        if rtype == "Module":
            wk = rec.get("weeks")
            if not isinstance(wk, str) or not WEEKS_RE.match(wk):
                f.append(Finding("V-03", "error", where, f"weeks {wk!r} is not 'N' or 'N-M'"))
        if rtype == "Concept":
            for dn in rec.get("difficulty_notes", []) or []:
                if not isinstance(dn, dict) or set(dn.keys()) != {"misconception", "mitigation"}:
                    f.append(Finding("V-03", "error", where,
                                     "difficulty_notes entry is not exactly {misconception, mitigation}"))


def _v04_ids(cc: dict, records, f: list[Finding]) -> None:
    seen: set[str] = set()
    for rtype, rec in records:
        if not isinstance(rec, dict):
            continue
        rid = rec.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        if rid in seen:
            f.append(Finding("V-04", "error", f"{rtype}:{rid}", "duplicate id"))
        seen.add(rid)
        # light structural id-pattern checks
        if rtype == "Module":
            cid = (cc.get("Course") or {}).get("id")
            if cid and not rid.startswith(f"{cid}."):
                f.append(Finding("V-04", "error", f"Module:{rid}", f"id does not start with '{cid}.'"))
        if rtype == "Concept":
            mid = rec.get("module_id")
            if isinstance(mid, str) and mid and not rid.startswith(f"{mid}."):
                f.append(Finding("V-04", "error", f"Concept:{rid}", f"id does not start with module_id '{mid}.'"))
        if rtype == "LearningObjective":
            if not LO_RE.search(rid):
                f.append(Finding("V-04", "error", f"LearningObjective:{rid}", "id does not end with '.lo<n>'"))


def _v05_references(cc: dict, records, ids_by_type, f: list[Finding]) -> None:
    course = cc.get("Course") or {}
    checks = [
        ("Course", course.get("id", "Course"), "module_ids", course.get("module_ids"), "Module"),
    ]
    for rtype, rec in records:
        if not isinstance(rec, dict):
            continue
        rid = rec.get("id", "?")
        if rtype == "Module":
            checks.append(("Module", rid, "course_id", rec.get("course_id"), "Course"))
            checks.append(("Module", rid, "concept_ids", rec.get("concept_ids"), "Concept"))
        elif rtype == "Concept":
            checks.append(("Concept", rid, "module_id", rec.get("module_id"), "Module"))
            checks.append(("Concept", rid, "prerequisite_ids", rec.get("prerequisite_ids"), "Concept"))
            checks.append(("Concept", rid, "objective_ids", rec.get("objective_ids"), "LearningObjective"))
            checks.append(("Concept", rid, "source_ids", rec.get("source_ids"), "Source"))
        elif rtype == "LearningObjective":
            checks.append(("LearningObjective", rid, "concept_id", rec.get("concept_id"), "Concept"))
    for rtype, rid, field, value, target in checks:
        targets = ids_by_type.get(target, set())
        refs = value if isinstance(value, list) else ([value] if value else [])
        for ref in refs:
            if ref not in targets:
                f.append(Finding("V-05", "error", f"{rtype}:{rid}",
                                 f"{field} -> {ref!r} does not exist as {target}"))


def _v06_reverse_links(cc: dict, records, f: list[Finding]) -> None:
    course = cc.get("Course") or {}
    modules = cc.get("Module") or []
    concepts = cc.get("Concept") or []
    objectives = cc.get("LearningObjective") or []

    # Course.module_ids <-> Module.course_id
    module_ids = {m.get("id") for m in modules if isinstance(m, dict)}
    declared = set(course.get("module_ids") or [])
    for mid in module_ids - declared:
        f.append(Finding("V-06", "error", f"Module:{mid}", "not listed in Course.module_ids"))
    for m in modules:
        if isinstance(m, dict) and m.get("course_id") != course.get("id"):
            f.append(Finding("V-06", "error", f"Module:{m.get('id')}",
                             f"course_id {m.get('course_id')!r} != Course.id {course.get('id')!r}"))

    # Module.concept_ids <-> Concept.module_id
    _reverse_set(modules, "concept_ids", concepts, "module_id", "Module", "Concept", f)
    # Concept.objective_ids <-> LearningObjective.concept_id
    _reverse_set(concepts, "objective_ids", objectives, "concept_id", "Concept", "LearningObjective", f)


def _reverse_set(parents, child_list_field, children, child_back_field,
                 ptype, ctype, f: list[Finding]) -> None:
    for p in parents:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        declared = set(p.get(child_list_field) or [])
        actual = {c.get("id") for c in children
                  if isinstance(c, dict) and c.get(child_back_field) == pid}
        for cid in actual - declared:
            f.append(Finding("V-06", "error", f"{ptype}:{pid}",
                             f"{ctype} {cid} has {child_back_field}={pid} but is not in {child_list_field}"))


def _v07_prerequisites(cc: dict, f: list[Finding]) -> None:
    course = cc.get("Course") or {}
    concepts = {c.get("id"): c for c in (cc.get("Concept") or []) if isinstance(c, dict)}
    order = {mid: i for i, mid in enumerate(course.get("module_ids") or [])}

    def mod_index(concept):
        return order.get(concept.get("module_id"), -1)

    for cid, c in concepts.items():
        ci = mod_index(c)
        for pre in c.get("prerequisite_ids") or []:
            if pre == cid:
                f.append(Finding("V-07", "error", f"Concept:{cid}", "prerequisite points to itself"))
            tgt = concepts.get(pre)
            if tgt is not None and ci >= 0 and mod_index(tgt) > ci:
                f.append(Finding("V-07", "error", f"Concept:{cid}",
                                 f"prerequisite {pre} is in a later module"))
    # cycle detection (DFS over existing prereq edges)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {cid: WHITE for cid in concepts}

    def dfs(node: str) -> bool:
        color[node] = GREY
        for pre in concepts[node].get("prerequisite_ids") or []:
            if pre not in concepts:
                continue
            if color[pre] == GREY:
                f.append(Finding("V-07", "error", f"Concept:{node}",
                                 f"prerequisite cycle via {pre}"))
                return True
            if color[pre] == WHITE and dfs(pre):
                return True
        color[node] = BLACK
        return False

    for cid in concepts:
        if color[cid] == WHITE:
            dfs(cid)


def _v09_assumptions(cc: dict, all_ids: set[str], f: list[Finding]) -> None:
    for a in cc.get("assumptions", []) or []:
        if not isinstance(a, dict):
            f.append(Finding("V-09", "error", "assumptions", f"entry is not an object: {a}"))
            continue
        keys = set(a.keys())
        missing = ASSUMPTION_KEYS - keys
        extra = keys - (ASSUMPTION_KEYS | {"confidence"})
        if missing or extra:
            f.append(Finding("V-09", "error", "assumptions",
                             f"entry keys must be {sorted(ASSUMPTION_KEYS)} (+ optional 'confidence'); got {sorted(keys)}"))
            continue
        conf = a.get("confidence")
        if conf is not None and conf not in CONFIDENCE:
            f.append(Finding("V-09", "error", "assumptions",
                             f"confidence {conf!r} not in {sorted(CONFIDENCE)}"))
        aid = a.get("id", "")
        if isinstance(aid, str) and aid.endswith(".*"):
            prefix = aid[:-2]
            if not any(rid == prefix or rid.startswith(prefix + ".") or rid.startswith(prefix)
                       for rid in all_ids):
                f.append(Finding("V-09", "error", "assumptions", f"wildcard id {aid!r} matches no record"))
        elif aid not in all_ids:
            f.append(Finding("V-09", "error", "assumptions", f"id {aid!r} does not resolve to a record"))


def _v10_provenance(cc: dict, records, is_11: bool, f: list[Finding]) -> None:
    """V-10: provenance present (schema 1.1) and a valid enum value.

    The spec's third clause — a source_backed record must not be named by an
    assumptions entry — is intentionally NOT enforced in v1.
    """
    if not is_11:
        return
    for rtype, rec in records:
        if not isinstance(rec, dict):
            continue
        where = f"{rtype}:{rec.get('id', '?')}"
        if "provenance" not in rec:
            f.append(Finding("V-10", "error", where, "missing provenance (schema 1.1)"))
            continue
        prov = rec.get("provenance")
        if prov not in PROVENANCE:
            shown = (prov[:30] + "…") if isinstance(prov, str) and len(prov) > 30 else prov
            f.append(Finding("V-10", "error", where, f"provenance {shown!r} not in {sorted(PROVENANCE)}"))


# --- helpers & reporting -----------------------------------------------------

def _record_list(cc: dict):
    out = []
    if isinstance(cc.get("Course"), dict):
        out.append(("Course", cc["Course"]))
    for t in ARRAYS:
        for rec in cc.get(t, []) or []:
            out.append((t, rec))
    return out


def _ids_by_type(records) -> dict[str, set]:
    idx: dict[str, set] = {"Course": set(), **{t: set() for t in ARRAYS}}
    for rtype, rec in records:
        if isinstance(rec, dict) and isinstance(rec.get("id"), str):
            idx[rtype].add(rec["id"])
    return idx


def error_findings(findings: list[Finding]) -> list[Finding]:
    return [x for x in findings if x.severity == "error"]


def error_messages(findings: list[Finding]) -> list[str]:
    return [x.line() for x in error_findings(findings)]


def summary_line(findings: list[Finding], cc: dict, name: str = "course-context.json") -> str:
    errs = sum(1 for x in findings if x.severity == "error")
    warns = sum(1 for x in findings if x.severity == "warn")
    return f"{name}: {errs} error(s), {warns} warning(s)  records={counts(cc)}"


def format_report(findings: list[Finding], cc: dict, name: str = "course-context.json") -> str:
    lines = [x.line() for x in findings]
    lines.append(summary_line(findings, cc, name))
    return "\n".join(lines)
