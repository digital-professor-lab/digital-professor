"""Run log: what each step of a tutoring session produced, with a plain-language note.

The Engine records the raw output of every step while a turn runs (``GroundedDemoEngine.session_trace``
and ``pipeline_turns``). This module turns those records into a step-by-step view for the ``/pipeline``
page, so a non-technical audience can follow how the system reached each reply.

The notes are fixed templates filled from the recorded values, not model-written text, so they always
describe what the code actually did.

The view is for the presenter/operator. It shows the lesson plan, the marking verdict and, on request,
the reference answer, none of which a student should see.
"""

from __future__ import annotations

from typing import Any, Sequence

from digital_professor.retrieval.course_retrieval import last_outcome
from digital_professor.tutoring.policy import DIAGNOSIS_MEANING


# ---------------------------------------------------------------------------
# Capture (called by the Engine while a turn runs)
# ---------------------------------------------------------------------------
def retrieval_snapshot(index: Any, passages: Sequence[Any], elapsed_ms: int) -> dict[str, Any]:
    """The latest search: the request sent, the record returned, and the passages kept."""
    outcome = last_outcome(index, passages)
    request = getattr(index, "last_request", None) or {}
    record = getattr(index, "last_record", None) or {}
    snapshot: dict[str, Any] = {
        "mode": outcome.get("mode"),
        "status": outcome.get("status"),
        "record_type": record.get("record_type"),
        "warnings": list(outcome.get("warnings") or []),
        "uncovered_needs": list(outcome.get("uncovered_needs") or []),
        "ms": elapsed_ms,
        "passages": [
            {
                "rank": rank,
                "page": item.passage.page_number,
                "lines": f"{item.passage.line_start}-{item.passage.line_end}",
                "text": _short(item.passage.text, 160),
                "highlight_url": item.highlight_url,
            }
            for rank, item in enumerate(passages, 1)
        ],
    }
    if outcome.get("reason_code"):
        snapshot["reason_code"] = outcome["reason_code"]
    if request:
        snapshot["request"] = {
            "query": request.get("query"),
            "query_origin": request.get("query_origin"),
            "purpose": request.get("purpose"),
            "evidence_needs": [
                f"{need.get('need_id')}: {need.get('need_type')}" for need in request.get("evidence_needs") or []
            ],
        }
    return snapshot


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
TURN_TYPE_NOTE = {
    "ANSWER": "The student submitted an answer, work or an explanation, so it will be marked.",
    "PARTIAL": "The student submitted unfinished work, so it will be marked.",
    "NEW_QUESTION": "The message is about a different problem.",
    "DEMAND": "The student asked for the answer outright. The tutor never gives it, and helps instead.",
    "CONCEPT": "The student asked about an idea rather than submitting work.",
    "HELP": "The student asked for help. Help requests are not marked.",
    "VAGUE": "The message is too unclear to act on.",
    "ACK": "The student only acknowledged (“ok”, “got it”). That is not evidence of understanding.",
    "OFF_TOPIC": "The message leaves the question or the course.",
    "INVALID": "The message has no usable content.",
}

READ_SOURCE_NOTE = {
    "code": "Fixed phrase rules settled this, with no AI call.",
    "model": "The wording was not clear-cut, so the language model read it (same call as the marking).",
    "heuristic": "No language model is configured, so a rough rule-of-thumb was used.",
    "failed": "The language model could not be reached, so a rough rule-of-thumb was used.",
}

MATH_NOTE = {
    "correct": "The algebra check (SymPy) proved the answer correct.",
    "incorrect": "The algebra check (SymPy) proved the final answer wrong.",
    "unknown": "The algebra check could not prove the work right or wrong.",
    "absent": "There is no math in the message to check.",
}

STATUS_PHRASE = {
    "supported": "found passages that cover what this step needs",
    "partial": "found relevant passages, but the automatic check could not confirm they cover everything",
    "no_support_found": "found nothing in the course material that supports this; the tutor is told so "
                        "instead of inventing a source",
    "failed": "the search itself failed (a technical fault, not missing material)",
}

ORIGIN_PHRASE = {
    "structured": "The search terms came from the lesson plan's concepts and method, not from the student's "
                  "wording.",
    "student_text": "The search terms were the question's own wording.",
}

ACTOR_RULE = "code"
ACTOR_RETRIEVAL = "retrieval"
ACTOR_MODEL = "model"
ACTOR_STUDENT = "student"
ACTOR_SYSTEM = "system"


# ---------------------------------------------------------------------------
# Building the view
# ---------------------------------------------------------------------------
def build_pipeline_view(session: Any) -> dict[str, Any]:
    engine = session.engine
    start = engine.session_trace or {}
    model = _model_name(engine)
    gap_labels = {gap["gap_id"]: gap["requirement"] for gap in start.get("gaps") or []}
    return {
        "session_id": session.session_id,
        "course_name": session.course.course_name,
        "question": session.question.prompt,
        "started_at": start.get("created_at"),
        "model": model,
        "start": {"steps": _start_steps(start, model)},
        "turns": [_turn_view(trace, model, gap_labels) for trace in engine.pipeline_turns],
    }


def _start_steps(start: dict[str, Any], model: str | None) -> list[dict[str, Any]]:
    if not start:
        return []
    model_label = model or "The language model"
    steps = [_step(
        ACTOR_STUDENT, "Question received",
        "The student opened a session with this question. The course version is fixed for the whole session.",
        {"question": start.get("question"), "course": start.get("course_name")},
    )]

    steps.append(_retrieval_step(
        start.get("initial_retrieval") or {}, "First search: the question as typed",
        "Nothing is known about the question yet, so the retrieval tool searches the course material with the "
        "question's own words.",
    ))

    builder = start.get("schema_builder") or {}
    qs = start.get("question_schema") or {}
    status = builder.get("status")
    if status == "built":
        concepts = qs.get("concept_names") or []
        steps.append(_step(
            ACTOR_MODEL, "Lesson plan written (QuestionSchema)",
            f"{model_label} matched the question to the course concept “{concepts[0] if concepts else '?'}” and "
            f"wrote a lesson plan: the method to use, prerequisites, likely misconceptions and a reference answer. "
            f"The reference answer is never shown to the student; it is used only to mark their work. "
            f"Took {_secs(builder.get('ms'))}.",
            {
                "record_type": "QuestionSchema",
                "question_id": qs.get("question_id"),
                "concepts": concepts,
                "method": (qs.get("correct_approach") or {}).get("technique", ""),
                "prerequisites": [p.get("name") or p.get("concept_id") for p in qs.get("prerequisite_concepts") or []],
                "learning_objectives": [lo.get("text") for lo in qs.get("learning_objectives") or []],
                "common_misconceptions": [
                    _short(m.get("description") or m.get("misconception") or "", 120)
                    for m in qs.get("common_misconceptions") or []
                ],
                "reference_answer": "(hidden, use the button below)",
            },
            secret={"label": "Show reference answer", "value": qs.get("reference_answer")},
        ))
    else:
        reason = {
            "failed": f"The model could not build a lesson plan ({builder.get('error', 'unknown error')}).",
            "no_model": "No language model is configured.",
            "no_course_context": "The course has no CourseContext.",
        }.get(status, "The lesson plan was not built.")
        steps.append(_step(
            ACTOR_SYSTEM, "Placeholder lesson plan",
            f"{reason} The system used a generic placeholder plan built from the course's first concepts.",
            {"record_type": "QuestionSchema", "status": qs.get("status"), "concepts": qs.get("concept_names")},
        ))

    if start.get("structured_retrieval"):
        steps.append(_retrieval_step(
            start["structured_retrieval"], "Second search: guided by the lesson plan",
            "The search now uses the lesson plan's concept names and method instead of the student's wording, so "
            "it reaches the right textbook section even when the question is phrased vaguely.",
        ))

    gaps = start.get("gaps") or []
    steps.append(_step(
        ACTOR_RULE, "Learning checklist created",
        f"The tutor turns the lesson plan into {len(gaps)} things the student needs to show. Each starts as "
        f"“open” and is updated after every turn.",
        [{"item": _short(g["requirement"], 110), "kind": g["gap_type"], "status": g["status"]} for g in gaps],
    ))
    return steps


def _turn_view(trace: dict[str, Any], model: str | None, gap_labels: dict[str, str]) -> dict[str, Any]:
    writer = trace.get("writer") or {}
    judge = trace.get("judge") or {}
    model_label = writer.get("model") or judge.get("model") or model or "The language model"
    evidence = trace.get("evidence") or {}
    read = trace.get("read") or {}
    turn_type = trace.get("turn_type") or "?"
    decision = trace.get("decision") or {}
    situation = decision.get("situation") or "?"
    move = writer.get("move") or situation
    assessment = trace.get("assessment")
    math = trace.get("math_check") or {}
    retrieval = trace.get("retrieval") or {}
    before_state = trace.get("state_before") or {}
    steps: list[dict[str, Any]] = []

    # 1. Input
    steps.append(_step(
        ACTOR_STUDENT, "Student message received",
        "The message is saved as evidence and linked to the previous turn, so the tutor always knows what it is "
        "responding to.",
        {"record_type": "StudentEvidence", "turn": trace.get("turn_id"), "text": evidence.get("confirmed_content"),
         "input": evidence.get("modality"), "kind": evidence.get("evidence_kind"),
         "follows_evidence": evidence.get("parent_evidence_id")},
    ))

    # 2. Reading the message and checking the math
    extra = [i for i in read.get("intents") or [] if i != turn_type]
    note = TURN_TYPE_NOTE.get(turn_type, f"Read as {turn_type}.")
    if trace.get("opening"):
        note = ("This is the problem itself, not an attempt at it. Nothing is marked, and the tutor will not "
                "hint at a method.")
    if extra:
        note += f" It also shows: {', '.join(extra)}."
    steps.append(_step(
        ACTOR_RULE if read.get("source") == "code" else ACTOR_MODEL if read.get("source") == "model" else ACTOR_SYSTEM,
        "Reading: what kind of message is this?",
        f"{note} {READ_SOURCE_NOTE.get(read.get('source'), '')} {MATH_NOTE.get(math.get('status'), '')}".strip(),
        {"record_type": "TurnRead", "message_type": turn_type, "all_intents": read.get("intents"),
         "final_answer_read": read.get("final_answer"), "shows_work": read.get("has_work"),
         "read_by": read.get("source"), "algebra_check": math,
         "answer_check_used": trace.get("answer_check")},
    ))

    # 3. Marking
    if assessment is not None:
        diagnosis = assessment.get("diagnosis")
        summary = assessment.get("summary") or ""
        steps.append(_step(
            ACTOR_MODEL, "Marking: where is the student now?",
            f"{model_label} compared the message with the lesson plan and the reference answer and returned a "
            f"fixed-format record. Its verdict: {diagnosis} ({DIAGNOSIS_MEANING.get(diagnosis, diagnosis)}), "
            f"confidence {assessment.get('confidence', '?')}." + (f" Its note: “{summary}”" if summary else "")
            + " What it found right and where the first problem is are passed to the writer; the reference "
              "answer is not."
            + (f" The first record was invalid, so it was asked again ({judge.get('attempts')} attempts)."
               if (judge.get("attempts") or 1) > 1 else "")
            + f" Took {_secs(judge.get('ms'))}.",
            {"record_type": "TurnAssessment", **assessment},
        ))
    else:
        why = {
            "turn_type": "Not run: only answers and partial work are marked.",
            "opening": "Not run: the student has only posed the problem.",
            "no_model": "Not run: no language model is configured, so only the algebra check is available.",
            "failed": f"The marking call failed ({judge.get('error') or 'unknown error'}). The tutor continues "
                      f"on the algebra check alone and does not count a faulty turn against the student.",
        }.get(trace.get("assessment_skipped"), "Not run.")
        steps.append(_step(ACTOR_MODEL, "Marking: skipped", why, {"skipped": trace.get("assessment_skipped")},
                           skipped=True))

    # 4. Checklist
    before = trace.get("gaps_before") or {}
    after = trace.get("gaps_after_assessment") or {}
    changes = [{"item": _short(gap_labels.get(gap_id, gap_id), 90), "from": before.get(gap_id, "new"), "to": status}
               for gap_id, status in after.items() if before.get(gap_id) != status]
    updates = trace.get("gap_updates") or {}
    rejected = updates.get("rejected") or []
    counts = {name: sum(1 for v in after.values() if v == name) for name in ("open", "partial", "closed")}
    if changes:
        listed = "; ".join(f"“{c['item']}” {c['from']} → {c['to']}" for c in changes)
        explain = (f"{len(changes)} item(s) changed: {listed}. A change proposed by the model is accepted only "
                   f"when it quotes the student's own words; solving the problem changes the method item by rule.")
    else:
        explain = "No item changed this turn."
    if rejected:
        explain += (f" {len(rejected)} proposed change(s) were rejected "
                    f"({'; '.join(sorted({r['why'] for r in rejected}))}).")
    steps.append(_step(ACTOR_RULE, "Learning checklist updated", explain,
                       {"changes": changes, "rejected_proposals": rejected, "checklist": counts}))

    # 5. Decision
    notes = " ".join(decision.get("notes") or [])
    if decision.get("fixed_text"):
        bounds = "This situation has a fixed reply, so no AI writes anything."
    else:
        bounds = ("Code only works out the situation and keeps the counters. How to help, and how much, is "
                  "the tutor model's judgment; the reply checks enforce that the student does the solving.")
    steps.append(_step(
        ACTOR_RULE, "Decision: what situation is this?",
        f"{notes} {bounds}".strip(),
        {
            "situation": situation, "combined_verdict": decision.get("diagnosis"),
            "verdict_decided_by": decision.get("verdict_source"),
            "help_given_so_far": decision.get("help_given"),
            "help_requests": decision.get("help_requests"),
            "method_may_be_named": decision.get("may_name_method"),
            "working_on": _short(gap_labels.get(_gap_id(decision.get("target_gap"), gap_labels), "") or
                                 str(decision.get("target_gap")), 90),
            "phase": f"{before_state.get('phase')} → {decision.get('next_phase')}",
            "turns_without_progress": decision.get("stall_count"),
            "brief_for_the_writer": decision.get("brief"),
        },
    ))

    # 6. Retrieval
    if retrieval.get("status") == "not_run" and retrieval.get("skipped"):
        steps.append(_step(
            ACTOR_RETRIEVAL, "Retrieval: not needed this turn",
            f"The course material was not searched: {retrieval['skipped']}.",
            {"retrieval_status": "not_run", "reason": retrieval["skipped"]}, skipped=True))
    else:
        dropped = retrieval.get("dropped") or []
        lead = ("Textbook passages are fetched so the tutor model can base an explanation on them and send "
                "the student to one, if it decides to teach.")
        if retrieval.get("reused"):
            lead += " The same search was already run for this question, so its result is reused."
        if dropped:
            lead += (f" {len(dropped)} of {retrieval.get('found')} passages found were set aside ("
                     + "; ".join(sorted({d['why'] for d in dropped})) + ").")
        steps.append(_retrieval_step(retrieval, "Retrieval tool searches the course material", lead))

    # 7. Writing
    checks = trace.get("reply_checks") or {}
    if writer.get("fixed_text"):
        steps.append(_step(ACTOR_RULE, "Reply: fixed text",
                           "A fixed sentence written by the team. No AI call and no search, so there is "
                           "nothing that could give the answer away.",
                           {"model": None, "reply": trace.get("reply")}))
    elif writer.get("model"):
        attached = writer.get("passage_attached")
        steps.append(_step(
            ACTOR_MODEL, "Writing the reply: the tutor model chooses how to teach",
            f"{writer['model']} is told where things stand (the situation, what the marking found, the help "
            f"given so far) and gets {writer.get('passages_given', 0)} textbook passage(s). It is never given "
            f"the reference answer. It decided what to do (“{move}”) and wrote the reply in its own words."
            + (f" It asked for passage {attached} to be shown to the student, so that passage is attached "
               f"under the reply." if attached else "")
            + f" Took {_secs(writer.get('latency_ms'))}, {writer.get('input_tokens')} + "
              f"{writer.get('output_tokens')} tokens.",
            {"model": writer["model"], "move_chosen": move, "course_passages_given": writer.get("passages_given", 0),
             "passage_shown_to_student": attached, "latency_ms": writer.get("latency_ms"),
             "tokens": {"in": writer.get("input_tokens"), "out": writer.get("output_tokens")}}))
    else:
        steps.append(_step(ACTOR_SYSTEM, "Writing the reply",
                           "No language model is configured, so a template reply for this situation was used.",
                           {"model": None, "reply": trace.get("reply")}))

    # 8. Reply checks
    if checks:
        failed = checks.get("failed_first_draft") or []
        guard = checks.get("guard") or {}
        if checks.get("fallback"):
            outcome = ("The draft failed the checks (" + "; ".join(failed) + ") and so did the rewrite, so the "
                       "draft was thrown away and a safe fixed sentence was sent instead.")
        elif failed:
            outcome = ("The first draft failed (" + "; ".join(failed) + "). It was rewritten once and the "
                       "rewrite passed.")
        else:
            outcome = "The draft passed."
        if not checks.get("guard_enabled"):
            guard_note = ""
        elif not checks.get("guard_ran"):
            guard_note = (" The second AI check (the guard) was not needed: the reply contains no math the "
                          "student has not written.")
        elif guard.get("leak") is False:
            guard_note = (" A second AI call (the guard) also confirmed that it does not do the student's work "
                          "and that the tutor's own math is right.")
        else:
            guard_note = " The guard could not be reached." if guard.get("leak") is None else ""
        steps.append(_step(
            ACTOR_RULE, "Reply checks before sending",
            f"Before anything reaches the student, code checks the draft: no final answer (verified by the "
            f"algebra check), no hint in the opening reply, and no method name while the student is still "
            f"finding their own way. "
            f"{outcome}{guard_note}",
            {"failed_on_first_draft": failed, "rewrites_used": checks.get("rewrites_used"),
             "guard": guard or None, "sent_fallback_template": checks.get("fallback"),
             "reply_sent": trace.get("reply")}))

    # 9. Delivery and commit
    state = trace.get("state_after") or {}
    open_n = len(state.get("open_gaps") or [])
    closed_n = len(state.get("closed_gaps") or [])
    partial_n = sum(1 for gap in state.get("open_gaps") or [] if gap.get("status") == "partial")
    steps.append(_step(
        ACTOR_SYSTEM, "Delivered and state saved",
        f"The reply was shown to the student. Only after delivery does the tutor save its new view of the "
        f"student: phase {state.get('phase')}, "
        f"{closed_n} of {open_n + closed_n} checklist items done"
        f"{f', {partial_n} partly shown' if partial_n else ''}. This turn used {trace.get('model_calls', 0)} AI "
        f"call(s), {_secs(trace.get('model_ms'))} in total.",
        {"DeliveryResult": (trace.get("delivery") or {}).get("status"), "LearnerState": "committed",
         "phase": state.get("phase"), "outcome": state.get("outcome"), "help_level": state.get("help_level"),
         "checklist_done": f"{closed_n}/{open_n + closed_n}", "last_verdict": state.get("last_diagnosis"),
         "state_version": state.get("state_version")},
    ))

    return {
        "turn_id": trace.get("turn_id"),
        "created_at": trace.get("created_at"),
        "student_text": evidence.get("confirmed_content"),
        "reply": trace.get("reply"),
        "flow": {"message_type": "OPENING" if trace.get("opening") else turn_type,
                 "verdict": decision.get("diagnosis"), "move": move,
                 "retrieval": retrieval.get("status") or "not_run"},
        "steps": steps,
    }


def _gap_id(slot: str | None, gap_labels: dict[str, str]) -> str:
    """The gap id for a target slot, e.g. ``prerequisite_concepts[1]`` -> ``prereq_1``."""
    if slot == "correct_approach":
        return "method"
    if slot and "[" in slot:
        prefix = "prereq" if slot.startswith("prerequisite") else "misconception"
        return f"{prefix}_{slot.split('[')[1].rstrip(']')}"
    return slot or ""


def _retrieval_step(snapshot: dict[str, Any], title: str, lead: str) -> dict[str, Any]:
    status = snapshot.get("status") or "not_run"
    phrase = STATUS_PHRASE.get(status, f"stopped before searching ({status})")
    request = snapshot.get("request") or {}
    origin = ORIGIN_PHRASE.get(request.get("query_origin") or "", "")
    passages = snapshot.get("passages") or []
    pages = ", ".join(f"p.{p['page']}" for p in passages)
    index = ""
    if snapshot.get("mode") == "retrieval_tool":
        index = " Index: Retrieval V1 (vector + keyword search)."
    elif snapshot.get("mode"):
        index = " Index: fallback keyword index."
    result = (f"Result: {status}, {phrase}. {len(passages)} passage(s)"
              f"{f' ({pages})' if pages else ''} in {snapshot.get('ms', '?')} ms.{index}")
    explain = " ".join(part for part in (lead, origin, result) if part)
    output: dict[str, Any] = {}
    if request:
        output["RetrievalRequest"] = request
    output[snapshot.get("record_type") or "result"] = {
        "retrieval_status": status,
        "warnings": snapshot.get("warnings"),
        "uncovered_needs": snapshot.get("uncovered_needs"),
        "passages": [{k: p[k] for k in ("rank", "page", "lines", "text")} for p in passages],
    }
    links = [{"label": f"p.{p['page']} · lines {p['lines']}", "url": p["highlight_url"]}
             for p in passages if p.get("highlight_url")]
    return _step(ACTOR_RETRIEVAL, title, explain, output, links=links)


def _step(actor: str, title: str, explain: str, output: Any, *, secret: dict[str, Any] | None = None,
          links: list[dict[str, Any]] | None = None, skipped: bool = False) -> dict[str, Any]:
    step: dict[str, Any] = {"actor": actor, "title": title, "explain": explain, "output": output}
    if secret and secret.get("value"):
        step["secret"] = secret
    if links:
        step["links"] = links
    if skipped:
        step["skipped"] = True
    return step


def _model_name(engine: Any) -> str | None:
    for trace in engine.pipeline_turns:
        model = (trace.get("writer") or {}).get("model") or (trace.get("judge") or {}).get("model")
        if model:
            return model
    config = getattr(getattr(engine, "provider", None), "config", None)
    return getattr(config, "model", None)


def _short(text: str, limit: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _secs(ms: Any) -> str:
    return f"{ms / 1000:.1f} s" if isinstance(ms, (int, float)) else "?"
