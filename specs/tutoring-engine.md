# Tutoring Engine — V1 Module Specification

| | |
|---|---|
| **Spec ID** | `tutoring-engine` |
| **Version** | V1 draft for team review, 2026-11-03 |
| **Spec author** | Sean (Zixiang Song) |
| **Partners** | Jonathan (Interaction), Ovunc (Course Context), Sean (Retrieval), Yining (Delivery) |
| **Shared contracts** | `interfaces.md` V0.1, `architecture.md` V0.1, `student-interaction.md` V0.1, `course-context.md` 0.6.0, `rag-retrieval.md` (2026-10-29), `tutoring-delivery.md` 0.2 |
| **Policy version** | `tutoring-policy@0.1` |

**Status labels**

- **[Contract]**: already defined in a shared spec.
- **[Module]**: owned by the Tutoring Engine.
- **[Expected]**: how this spec expects another module to behave. If that module differs, integration must adapt.

MUST, SHOULD and MAY follow RFC 2119. Every number in this spec is a V1 default and lives in configuration (Appendix F).

**V1 at a glance**

1. The Engine answers one question each turn: **what should the tutor do next?**
2. It is a **fixed workflow, not an autonomous agent**. Code controls the flow. The AI model only judges the student and writes the reply.
3. **Math is checked by a tool first.** When the tool can decide, it overrules the model.
4. **Rules narrow the next action.** The model may only choose among the options the rules give.
5. **The final answer is never given** before the student solves the question, however hard they ask.
6. Every reply is **checked before it leaves the Engine**. If it fails, the Engine rewrites once, then uses a safe template.
7. Faults never stop tutoring when a safe next step exists.

**Template map** (team `README.md`): 1 Purpose → §1 · 2 Responsibilities → §2 · 3 Dependencies → §3 · 4 Inputs → §4 · 5 Functions → §5 · 6 Outputs → §6 · 7 Failures → §7 · 8 Logging → §8 · 9 Examples → §9 · 10 Open questions → §10.

---

## 1. Purpose and scope

The Engine turns validated student evidence into one structured tutoring action. It keeps a running picture of what the student has shown, compares that with what the question requires, and chooses the next step that closes the most important gap.

**V1 delivers**

- question start and one tutoring turn;
- student assessment and `LearnerState` updates;
- rule-based action selection for 18 action cards;
- a final-answer check, using a math tool where possible;
- reply writing, reply checks and safe fallbacks.

**Out of scope for V1**

- input recognition and evidence construction (Interaction);
- building course content or Question Schemas (Course Context);
- search and ranking (Retrieval);
- rendering and avatar behaviour (Delivery);
- choosing the next question, or tracking mastery across questions;
- languages other than English;
- real student use before a privacy and safety review.

## 2. Responsibilities

**The Engine owns** [Module]

- interpreting evidence as `LearnerState`;
- judging correctness and locating the student's main gap;
- choosing the next action, its goal and its limits;
- writing the exact student-facing content;
- enforcing the answer boundary;
- producing the final `RetrievalRequest` through the model's tool call;
- saving question state and reporting its own faults.

**The Engine does not own**

- what the student submitted (Interaction);
- whether an uploaded source is correct or complete (Course Context);
- which passages are found (Retrieval);
- how a reply is displayed (Delivery).

### 2.1 How the Engine connects

```mermaid
flowchart LR
    S[Student] --> I[Interaction<br/>Jonathan]
    I -->|StudentEvidence| E[Tutoring Engine]
    E -->|TutoringAction| I
    I --> D[Delivery<br/>Yining]
    D --> S
    C[Course Context<br/>Ovunc] -->|QuestionSchema| E
    E <-->|tool call and passages| R[Retrieval<br/>Sean]
    E --> T[(Session state and trace)]
```

The Engine does not call Delivery. It returns the action to Jonathan's coordinator, which forwards it.

### 2.2 Interaction boundary

Interaction answers **what the student wrote and wants**. The Engine answers **what that shows and what to do next**.

| Question | Interaction | Engine |
|---|---|---|
| What did the student write? | Recognizes and confirms it | Does not re-recognize |
| What does the student want? | Gives explicit button or intent signals when available | Infers it when absent |
| What are the steps and final answer? | Fills `observed_steps` and `final_answer` when available | Extracts them when absent |
| Is it correct? | Does not judge | Judges |
| Does the student understand? | Does not label | Records in `LearnerState` |

**Expected from Interaction** [Expected]

- Call `start_question` once when a question opens, then forward the first action.
- For a student's own question: confirm the text, call Ovunc's builder, then call `start_question`.
- Keep calling `select_action(evidence)` each turn. Do not add a Retrieval step before the Engine.
- Keep filling `prior_assistance` from `response_to_action_id`. The Engine uses it to know which help the student actually saw.
- Later, pass the optional turn understanding record from `rag-retrieval.md` §2.2 and Yining's `submission_kind`. V1 works without them.

### 2.3 Course Context boundary

The Question Schema arrives once per question and stays read-only. New misconceptions go into `LearnerState`, never back into the schema [Contract]. If the builder returns `NO_CONCEPT_MATCH`, the Engine uses generic elicitation with no target and logs the miss [Contract].

**Expected from Course Context** [Expected]: add the optional fields in §4.2, and verify `reference_answer` independently where a tool can check it.

### 2.4 Retrieval boundary

The Engine uses the **Tool only** entry point in `rag-retrieval.md` §2.5 because the writing model needs the action card and must not see the answer. Retrieval keeps the grounding policy, search, evidence check and citation check.

The Engine supplies `action_type`, `pedagogical_goal`, the `TurnContext` fields and two flags: `states_course_content` and `checks_course_convention`. `HINT_POINT` sets `states_course_content = false`, so its search becomes optional.

**Expected from Retrieval** [Expected]: expose the fallback search and citation helpers for this entry point. If they cannot be reused, add an `instructions` parameter to `run_turn` so the Engine can pass its action card. The Engine MUST also run with Retrieval turned off.

### 2.5 Delivery boundary

The Engine writes the exact content. Delivery presents it and does not add teaching. Yining's proposed fields fit inside the existing objects in `TutoringAction`:

| `interfaces.md` field | Holds | Yining's field |
|---|---|---|
| `content` | Text in V1; blocks later | `presentation` |
| `response_expected` | Expected response, format, input modes, links to prior attempts | `response_spec` |
| `constraints` | `content_policy`, `answer_disclosure`, `hint_level`, `prohibited_additions` | `constraints` |
| `grounding_refs` | Passage IDs | `sources` |

| Engine action | Delivery display type |
|---|---|
| `elicit`, `inspect`, `probe` | `PROBE` |
| `hint` | `HINT` |
| `explain`, `demonstrate`, `verify` | `EXPLAIN` |
| `retry` | `RETRY` |
| `check_understanding`, `transfer` | `CHECK_UNDERSTANDING` |

**Expected from Delivery** [Expected]: present V1 content as plain text with math, using this mapping. A help button sends a request to Interaction; Delivery never creates help itself.

## 3. Dependencies

| Dependency | Use | If unavailable |
|---|---|---|
| Main AI model | Assessment and writing. Not chosen yet; any model with structured output and tool calling | Retry, then fallback (§7) |
| SymPy | Final-answer check | `check_math` returns `unknown` |
| Retrieval | Course grounding | Teach without citations |
| Question Schema | Target for the question | Stop grounded tutoring and return a structured failure |
| State store | `LearnerState` and question state. In-memory in V1, behind a replaceable interface | Do not publish the action |
| Configuration | Limits, model roles, feature flags | Use Appendix F defaults |

## 4. Inputs

### 4.1 `StudentEvidence` [Contract]

| `validation_status` | Engine behaviour |
|---|---|
| `valid` | Normal turn |
| `partial` | Assess confirmed parts only. Actions limited to `probe` or `inspect` |
| `unconfirmed` | No diagnosis. Use `ASK_WORK` to ask the student to confirm or rewrite |
| `invalid` | Should not arrive. Log it and use `ASK_WORK` |

### 4.2 `QuestionSchema` [Contract + Expected additions]

| Field | Engine use | Writer can see it? |
|---|---|---|
| `correct_approach`, `alternative_approaches` | Create the method gap and accept valid methods | No |
| `prerequisite_concepts` | Create prerequisite gaps and review questions | Yes |
| `common_misconceptions` | `cue` raises a hypothesis; `mitigation` supports hints | `mitigation` only |
| `learning_objectives` | Scope of checks and transfer questions | Yes |
| `reference_answer` | Judge the answer | No |
| `provenance` | Avoid firm claims when AI-inferred and unverified | No |
| `constraints` | Merge into the action card | Yes |

Three optional additions make tutoring safer. V1 test questions include all of them (Appendix G). Field shapes are in Appendix B.

| Added field | Purpose | If absent |
|---|---|---|
| `answer_check` | Lets the tool judge the final answer | `check_math` returns `unknown` |
| `solution_outline` | Finds the first error and lists facts the reply must not reveal | Diagnosis relies on the model |
| `teaching_assets` | Verified similar example and transfer problems | Skip `DEMO_SIMILAR`; finish without transfer (§5.5) |

### 4.3 Optional understanding signals

| Signal | Source | Use |
|---|---|---|
| `submission_kind` | Delivery control through Interaction | Overrides turn type when explicit |
| Turn understanding record | Interaction | Skips inferred intent and topic |
| `final_answer`, `observed_steps` | Interaction | Skip `extract_work` |

### 4.4 Teaching policy

The rules in §5.4 to §5.8 are versioned data (`tutoring-policy@0.1`), not scattered code. A rule change MUST bump this version and be recorded in the trace.

## 5. Functions and expected behaviour

### 5.1 One turn

```mermaid
flowchart TD
    A[StudentEvidence] --> B[Precheck]
    B --> C[Load context]
    C --> D[Check math]
    D --> E[Assess student]
    E --> F[Update LearnerState]
    F --> G[Choose action card]
    G --> H[Search if policy allows]
    H --> I[Write reply]
    I --> J{Reply passes?}
    J -->|Yes| K[Save and return TutoringAction]
    J -->|No, first time| I
    J -->|No, second time| L[Use template]
    L --> K
```

Steps 1 to 4 run before search, so Retrieval receives a real `action_type`. Search and writing share one model conversation. A normal turn uses 2 model calls. A worst-case turn uses 6, before any retries.

| Function | Run by | Job |
|---|---|---|
| `start_question(session_id, question_schema)` | Code | Create gaps and state, then return the first action |
| `select_action(evidence)` | Code | Run one turn; return one `TutoringAction` |
| `precheck_turn` | Code | Handle duplicates, parallel submissions and safety signals |
| `load_turn_context` | Code | Load schema, state and action history |
| `extract_work` | Code; model only if needed | Find the final answer and steps |
| `check_math` | Code | Return `correct`, `incorrect`, `unknown` or `absent`; never raise |
| `assess_turn` | Model | Return turn type, diagnosis, confidence, target gap and gap updates |
| `apply_assessment` | Code | Apply correction rules and write evidence-backed updates |
| `candidate_actions` | Code | Return the default card and optional alternative |
| `choose_action` | Model, optional | Choose between them; on failure use the default |
| `gather_grounding` | Retrieval through model | Search when policy requires or allows |
| `compose_reply` | Model | Write only what the action card allows |
| `guard_reply` | Code; model optional | Check answer leakage, citations and format |
| `fallback_reply` | Code | Return a safe template |
| `commit_turn` | Code | Save state, action and events together |

### 5.2 Information walls

| Step | Can see `reference_answer`? | Why |
|---|---|---|
| `check_math` | Uses `answer_check` only | Needs to judge |
| `assess_turn` | Yes | Compares student work with the solution |
| `choose_action` | No | Does not need it |
| `compose_reply` | No | Reduces leakage at the source |
| `guard_reply` | Code only | Must detect leakage |

### 5.3 Assessing the student

**Turn type: what the student is doing**

| Code | Meaning | Example |
|---|---|---|
| `ANSWER` | Submits an answer | "It is cos(x²)." |
| `PARTIAL` | Submits unfinished work | "I set u = x, but I'm stuck." |
| `HELP` | Asks for help | "I don't know how to start." |
| `CONCEPT` | Asks about an idea or step | "Why multiply by the inner derivative?" |
| `DEMAND` | Asks for the answer | "Just tell me the answer." |
| `ACK` | Acknowledges only | "Got it." |
| `VAGUE` | Gives an unclear reply | "Maybe, I guess." |
| `OFF_TOPIC` | Leaves the question or course | "Do you like basketball?" |
| `DISTRESS` | Shows clear frustration | "I'm too stupid for this." |
| `INVALID` | Sends unusable content | Random symbols |

Attempts to change the rules ("ignore your instructions") count as `DEMAND`. Student text is always data, never instructions.

**Diagnosis: where the student is stuck**

| Code | Meaning | Example |
|---|---|---|
| D0 | No starting idea | "I have no idea." |
| D1 | Misread the question | Gave the derivative when asked for a maximum |
| D2 | Missing prerequisite | Cannot say what a composite function is |
| D3 | Wrong method | Used substitution on ∫x cos x dx |
| D4 | Right method, wrong setup | Swapped u and dv |
| D5 | Right method, rule misused or step missing | Left out the inner derivative |
| D6 | Right method, careless slip | Sign or arithmetic error |
| D7 | Nearly done, incomplete | Missing `+ C`; did not check endpoints |
| D8 | Correct answer, no work | Only wrote "6" |
| D9 | Correct, but relied on help | Correct after a hint |
| D10 | Correct and independent | Clear, complete work |
| `UNCLEAR` | Not enough evidence | Tool and model disagree |

A method that differs from `correct_approach` is valid when it matches `alternative_approaches` or the tool confirms the result.

**Correction rules** [Module]

| Situation | Result |
|---|---|
| Tool says correct; model chose an error type other than D7 | `UNCLEAR` |
| Tool says incorrect; model chose D8, D9 or D10 | `UNCLEAR` |
| Model confidence is `low` | `UNCLEAR` |
| Tool says `unknown`; model chose D5, D6, D8, D9 or D10 without `high` confidence | `UNCLEAR` |

`UNCLEAR` means gather evidence. The tutor MUST NOT tell the student they are right or wrong.

### 5.4 Updating gaps and help level

**Gaps.** `start_question` creates one method gap, one gap per prerequisite and one mastery gap. A misconception becomes a gap only when its `cue` appears.

| Rule | Meaning |
|---|---|
| Assisted success | Gap moves to `partial`, not `closed` [Contract] |
| Independent success | Gap moves to `closed` |
| Contradicting evidence | Closed gap may reopen, with the reason recorded |
| "Got it" | Closes nothing |
| Passed transfer | Closes the mastery gap and the assisted gaps it covers |

Every gap update MUST cite evidence. Updates without evidence are rejected.

**Progress** means a gap improved, the first error moved later, or the student stated a key step they could not state before. New wording alone is not progress.

**Help level** starts at 0 for each target gap. Update it in this order:

1. If the target gap changed, or the student made progress, set the level to 0.
2. Otherwise, if the student saw the last help action, add 1.
3. If the turn is `DEMAND` and the level is 0, set it to 1.
4. If the next card is `DEMO_SIMILAR` and no verified example exists, skip it and add 1.

An undelivered action does not count, because it never appears in `prior_assistance`.

### 5.5 Question phases

```mermaid
stateDiagram-v2
    [*] --> ATTEMPTING
    ATTEMPTING --> REMEDIATING: error or unclear
    ATTEMPTING --> SOLVED_CHECK: correct
    REMEDIATING --> SOLVED_CHECK: correct
    SOLVED_CHECK --> TRANSFER: can explain
    TRANSFER --> RESOLVED: correct and independent
    TRANSFER --> REMEDIATING: wrong
    REMEDIATING --> PARKED: ladder ends or turn limit
    PARKED --> REMEDIATING: student returns
    RESOLVED --> [*]
```

| Rule | Behaviour |
|---|---|
| Entering `SOLVED_CHECK` | D8 gets `ASK_WORK`; D9 and D10 get `CONFIRM_ASK_WHY` |
| Leaving `SOLVED_CHECK` | Move to `TRANSFER` after D9 or D10, or after 2 weak checks |
| Transfer problem | Check it against that problem's own `answer_check` |
| Transfer budget | At most 2 transfer problems. After the second failure, use `PARK` |
| No transfer problem | Use `WRAP_UP`, then set phase to `PARKED` with reason `no_transfer_available`; mastery stays `partial` |
| Turn limit | The 15th student turn on a question uses `PARK` |
| Student returns | Reset the turn count and lower the help level by 1 |
| `RESOLVED` | Only when `open_gaps` is empty [Contract] |

### 5.6 Choosing the next action

**Error states.** Each row is a ladder. No progress moves one step right. At level 0 the model may choose the option in brackets; from level 1 on, the rules decide alone.

| Diagnosis | Level 0 (option) | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| D0 | `ELICIT_START` (`PREREQ_CHECK`) | `HINT_POINT` | `HINT_TEACH` | `DEMO_SIMILAR` | `PREREQ_REVIEW` | `PARK` |
| D1 | `REVIEW_PROBLEM` (`ASK_WORK`) | `HINT_POINT` | `HINT_TEACH` | `DEMO_SIMILAR` | `PARK` | |
| D2 | `PREREQ_CHECK` (`PREREQ_REVIEW`) | `PREREQ_REVIEW` | `DEMO_SIMILAR` | `PARK` | | |
| D3 | `ASK_REASON` (`HINT_POINT`) | `HINT_TEACH` | `DEMO_SIMILAR` | `PREREQ_REVIEW` | `PARK` | |
| D4 | `HINT_POINT` (`ASK_REASON`) | `HINT_TEACH` | `DEMO_SIMILAR` | `PREREQ_REVIEW` | `PARK` | |
| D5 | `HINT_POINT` (`ASK_WORK`) | `HINT_TEACH` | `DEMO_SIMILAR` | `PREREQ_REVIEW` | `PARK` | |
| D6 | `RETRY_CHECK` (`HINT_POINT`) | `HINT_POINT` | `HINT_TEACH` | `DEMO_SIMILAR` | `PARK` | |
| D7 | `RETRY_CHECK` | `HINT_POINT` | `HINT_TEACH` | `DEMO_SIMILAR` | `PARK` | |
| `UNCLEAR` | `ASK_WORK` (`CLARIFY`) | `CLARIFY` | `HINT_POINT` | `HINT_TEACH` | `PARK` | |

**Correct states.** See §5.5. D9 and D10 may have `TRANSFER` as an option when the student has already explained why.

**Non-answer turns**

| Turn type | Behaviour |
|---|---|
| `HELP` | Use the current ladder. With no diagnosis, use D0 |
| `CONCEPT` | `ANSWER_CONCEPT`, then return to the same question. Do not apply the idea to finish this question |
| `DEMAND` | Say the answer cannot be given, then use the next ladder step |
| `ACK` | In `SOLVED_CHECK`: `CONFIRM_ASK_WHY`. Otherwise `RETRY_FULL` |
| `VAGUE` | At level 0: `CLARIFY` with a two-choice question. Otherwise `HINT_POINT` |
| `OFF_TOPIC` | `REDIRECT` |
| `DISTRESS` | Add encouragement, then use the current ladder with a smaller step |
| `INVALID` | `ASK_WORK` |

### 5.7 Action cards

An action card tells the writer exactly what to do. "Search" follows `rag-retrieval.md` Appendix A.

| Card | Action | What the student gets | Search | Disclosure limit |
|---|---|---|---|---|
| `ELICIT_START` | `elicit` | Asked for the plan or first step | No | Nothing |
| `ASK_WORK` | `inspect` | Asked for key steps; no verdict yet | Blocked | Nothing |
| `ASK_REASON` | `probe` | Asked why this method was chosen | Optional | Nothing |
| `CLARIFY` | `probe` | A two-choice question | Optional | Nothing |
| `REVIEW_PROBLEM` | `probe` | Asked what the question wants | Optional | Nothing |
| `PREREQ_CHECK` | `probe` | One small prerequisite question | Optional | Nothing |
| `PREREQ_REVIEW` | `explain` | Short review of class knowledge | Required | Concept only |
| `HINT_POINT` | `hint` | Where to look; no rule stated | Optional | Location only |
| `HINT_TEACH` | `hint` | General rule, not applied to this question | Required | Rule only |
| `ANSWER_CONCEPT` | `explain` | Answer to the concept question | Required | Concept only |
| `DEMO_SIMILAR` | `demonstrate` | Full solution of a similar problem | Required | Similar problem only |
| `RETRY_CHECK` | `retry` | Asked to recheck one place | No | Location only |
| `RETRY_FULL` | `retry` | Asked to try again | No | Nothing |
| `CONFIRM_ASK_WHY` | `check_understanding` | Confirms correctness and asks why | Optional | May confirm |
| `TRANSFER` | `transfer` | A new related problem | Optional | Nothing |
| `WRAP_UP` | `verify` | Summary and full solution | Blocked | Full, after solving only |
| `PARK` | `verify` | Suggests a pause or asking the instructor; keeps progress | Blocked | Nothing |
| `REDIRECT` | `elicit` | Brief reply, then back to the question | No | Nothing |

V1 enables 10 of the 12 action types. `diagnose` is now an internal step. `contrast` waits for V2 because it needs verified contrast problems.

### 5.8 Fixed teaching rules

1. Before the student solves the question, never give its final answer.
2. Concepts, general rules and similar problems are allowed. Key steps of this question are not.
3. After two "I don't know" replies, the next reply MUST add new information.
4. Each reply asks at most one question and moves one small step.
5. Start by acknowledging what is already correct, when something is.
6. "I understand" is not evidence of understanding.
7. Do not comment on a student's ability.
8. Only tool-confirmed or high-confidence results may be stated as right or wrong.

### 5.9 Reply checks

| Check | Failure action |
|---|---|
| No final answer or equivalent expression before solving | Rewrite |
| No `solution_outline` key expression the student has not yet produced | Rewrite |
| Disclosure within the card's limit | Rewrite |
| At most one question | Rewrite |
| Citations pass `verify_grounding_refs` | Remove the citation, then rewrite if needed |
| No claim of course support without citations | Rewrite |
| No more than 120 words, except `DEMO_SIMILAR` and `WRAP_UP` | Rewrite |

Math in the reply is compared by value, so a different format cannot bypass the check. A second failure discards the draft and uses `fallback_reply`.

## 6. Outputs

### 6.1 `TutoringAction` [Contract]

| Field | V1 content |
|---|---|
| `action_type` | One of the 10 enabled types |
| `pedagogical_goal` | The card's goal for the target gap |
| `content` | `{"format": "text", "text": "..."}` in V1 |
| `grounding_refs` | Accepted passage IDs; may be empty |
| `response_expected` | Expected response, input modes and any revised submission |
| `allowed_presentations` | `["text"]` in V1 |
| `constraints` | `content_policy: verbatim`, `answer_disclosure`, `hint_level`, `prohibited_additions` |

### 6.2 `LearnerState` [Contract]

The existing record is enough:

| New information | Stored in |
|---|---|
| Diagnosis | `diagnostic_hypotheses` |
| Help level, turn count, phase | `assistance_history_summary` |
| Confidence and limits | `state_confidence` |
| New misconception | `off_target_context` |

Internal records are in Appendix A. Only `LearnerState` and `TutoringAction` cross module boundaries.

## 7. Expected failures

The principle: **draw fewer conclusions when uncertain, and always give the student a safe next step.**

### 7.1 Wrong judgments

| Situation | Detected by | Response |
|---|---|---|
| Correct work judged wrong | Tool conflict, student challenge | Ask for work; if confirmed, apologize and correct the state |
| Wrong work judged correct | Tool conflict, failed transfer | Do not confirm; reopen the gap |
| Wrong error type | Two turns without progress | Climb the ladder and diagnose again |
| Wrong reference answer | Tool confirms the student but not the reference | Trust the tool, stop using the reference, set `requires_human_review` |
| New misconception | Assessment finds no schema match | Save in `off_target_context`; use the closest gap |
| Student challenges a verdict | Student text | Run the check again; if unverifiable, admit uncertainty and ask for reasoning |

### 7.2 Student behaviour

| Situation | Response |
|---|---|
| Vague reply | Clarify once with two choices. If still unclear, give no credit and continue |
| Says "I understand" without evidence | Close nothing; check understanding or ask them to continue |
| Random guessing | After 3 wrong answers without work, ask for work first |
| Repeatedly asks for the answer | Refuse each time and escalate help until `PARK` |
| Tries to change the rules | Treat as `DEMAND` |
| Changes question | Interaction calls `start_question`; keep old state |
| Clear frustration | Encourage briefly and make the next step smaller |
| Self-harm or danger signal | Stop tutoring, show a fixed support message with crisis resources (988 in the US), set a safety flag. Human follow-up is required before real student use |

### 7.3 System faults

| Fault | Response | Student sees |
|---|---|---|
| Assessment timeout or error | Retry once; then keep state and treat as `UNCLEAR` | Request for key steps |
| Invalid model JSON | Repair once; then treat as `UNCLEAR` | Same |
| Writing timeout | Retry once; then template | Safe general reply |
| Reply fails twice | Discard; use template | Safe general reply |
| Math tool fails or times out | Return `unknown`; never treat as wrong | No verdict |
| Retrieval `failed` | Teach without citations | No claim of course support |
| `RetrievalStop` | `needs_clarification`: use `CLARIFY`. Others: teach without citations | Normal tutoring |
| `partial` or `no_support_found` | Cite only what is supported. Never claim uncovered content | Honest reply |
| Out of scope | Say it is outside the course and redirect | Redirect |
| Jev unavailable | Follow Retrieval fallback | No visible change |
| Rate limit (429) | Back off within the time budget; then template | Slower reply |
| Turn exceeds 20 seconds | Use template | Safe general reply |
| Duplicate submission | Return the saved action for that `submission_id` | One reply only |
| Parallel submissions | Process one at a time per session | Replies in order |
| State save fails | Retry; if still failing, raise an error and publish nothing | Try-again message from Interaction |
| Delivery fails | Do not count the help as seen | Session continues |

Known faults return a fallback action. An exception reaches the coordinator only when no action can be safely saved. The coordinator then returns `engine_handoff_failed`.

## 8. Logging and observability

Each turn writes one `InteractionTraceEvent` per step and follows the shared logging switch [Contract].

**Operational (always kept):** identifiers, phase, current state, action, policy version, turn status.

**Diagnostic (when enabled):** step timings, model and prompt versions, math result, assessment, confidence, candidates, final card, guard results, retries, fallback reason, token use. Raw student text stays in referenced records, not repeated in each event.

**V1 metrics**

| Metric | Initial target |
|---|---|
| Final-answer leakage | 0 in the test set |
| Correct answers wrongly rejected when the tool applies | 0 |
| Diagnosis agreement on Appendix G turns | At least 80% |
| Math errors in replies | Tracked; every case reviewed |
| Turn time | p50 up to 6 s; p95 up to 12 s |

Latency targets come from earlier retrieval tests (model 1.6–4.6 s per turn, retrieval up to 0.5 s) and must be recalibrated. Appendix F lists step limits.

## 9. Examples

### 9.1 One question from start to finish

Question: differentiate sin(x²).

| Turn | Student | Engine result | Tutor |
|---|---|---|---|
| Start | — | `ELICIT_START`; phase `ATTEMPTING` | "What would your first step be?" |
| 1 | "cos(x²)" | Tool `incorrect`; D5; `HINT_POINT` | "Your outer derivative is right. Look again at what sits inside the sine. Did you account for it?" |
| 2 | "Just tell me the answer." | `DEMAND`; level 1; `HINT_TEACH` | "I can't give you the answer, but here is the rule: for f(g(x)), multiply f′(g(x)) by g′(x). What is g(x) here?" |
| 3 | "2x cos(x²)" | Tool `correct`; D9; `CONFIRM_ASK_WHY` | "That's correct. Why do you need the 2x?" |
| 4 | "x² is the inside function, so its derivative multiplies." | D9; `TRANSFER` | "Now try: differentiate e^(3x²)." |
| 5 | "6x e^(3x²), the same inner-derivative idea." | Tool `correct`; D10; gaps closed | `WRAP_UP`: summary and full solution |

### 9.2 Normal handoff

The student chose u = cos x on ∫x cos x dx. The Engine returns:

```json
{
  "record_id": "action-709",
  "record_type": "TutoringAction",
  "schema_version": "0.1",
  "created_at": "2026-11-03T15:00:04Z",
  "producer": "tutoring-engine",
  "status": "selected",
  "correlation_id": "corr-88",
  "action_id": "action-709",
  "session_id": "session-20",
  "question_id": "calc1.06-integral-applications.by-parts.adhoc-d7df1b60",
  "turn_id": "turn-4",
  "learner_state_id": "state-41",
  "action_type": "hint",
  "pedagogical_goal": "Help the student notice that the new integral became harder.",
  "content": {"format": "text", "text": "Your use of the formula is sound. Compare the new integral with the original. Which one is simpler?"},
  "grounding_refs": [],
  "response_expected": {"expected_kind": "math_with_explanation", "input_modes": ["text"]},
  "allowed_presentations": ["text"],
  "constraints": {"content_policy": "verbatim", "answer_disclosure": "none", "hint_level": 1, "prohibited_additions": ["final answer", "correct u and dv"]}
}
```

### 9.3 Uncertain handoff

Evidence arrives as `unconfirmed` because `x²` and `x₂` are both plausible. The Engine does not diagnose. It keeps state, uses `ASK_WORK`, and asks the student to confirm the expression.

### 9.4 Failed handoff

`assess_turn` times out twice. The Engine keeps the previous `LearnerState`, treats the turn as `UNCLEAR`, and returns `ASK_WORK` with the template reply. The trace records `fallback_reason: assess_timeout`. The student still receives a useful next step.

## 10. Decisions and future work

### 10.1 Decisions taken

| Topic | V1 decision |
|---|---|
| Who calls Retrieval | The Engine |
| Who produces the final `RetrievalRequest` | The Engine, through the model's tool call and Retrieval's system fields |
| Engine entry | Keep `select_action(evidence)`; add `start_question` |
| Student-owned questions | Interaction calls the builder before `start_question` |
| Typed answers | `final_answer` and `observed_steps` are optional; Engine extracts when absent |
| Question Schema additions | Optional, and used whenever present |
| Prerequisite detail | Split until each item is one thing a student can get wrong |
| Delivery format | Text first, then blocks; 10 actions map to 5 display types |
| Limits | 15 turns per question; 2 transfer problems |
| State storage | In memory in V1, behind a replaceable interface |
| Models | Configurable by role; not fixed in this spec |
| External processing | Synthetic data only in V1. Real student text needs approval first |
| General knowledge | Labelled in development. In production, if off and no source exists, the tutor says so and continues with questions |
| After solving | The full solution may be shown |

### 10.2 Still open

| Item | Needed before |
|---|---|
| Final main model choice | Model comparison |
| Human safety process and approved wording | Any real student use |
| Production state store | Multi-user pilot |

### 10.3 Future work

| Version | Addition | Why |
|---|---|---|
| V1.1 | Use Interaction's turn understanding directly | Saves a model call |
| V1.1 | Verify builder answers at question start | Protects the tutoring target |
| V1.1 | Simulated students for regression tests | Finds failures at scale |
| V2 | Dispute handling | Corrects verdicts when challenged |
| V2 | Resume with a recap | Smoother return after a pause |
| V2 | Verified generation of similar and transfer problems | Supports any question |
| V2 | Hint start level from recent performance | Avoids hints that are too weak or strong |
| V2 | Repeated-error detection | Finds stable misconceptions |
| V2 | Model routing and circuit breakers | Better reliability |
| V2 | Human review queue | Reviews risky judgments |
| V2 | Enable `contrast` | Requires verified contrast problems |
| V3 | Mastery across questions and next-question choice | Adds the outer tutoring loop |
| V3 | Instructor views and live experiments | Measures real learning impact |

---

## Appendix A. Internal records

Field meanings are binding. Storage format is an implementation choice.

**`ParsedWork`**

```json
{"final_answer": "x sin(x) + cos(x)", "steps": ["u = x", "dv = cos(x) dx"], "source": "evidence | extracted | none"}
```

**`MathCheck`**

```json
{"status": "correct | incorrect | unknown | absent", "reason": "parse_failed | timeout | no_answer_check | null", "flags": ["missing_constant"]}
```

**`TurnAssessment`**

```json
{
  "turn_type": "ANSWER",
  "diagnosis": "D4",
  "confidence": "high",
  "first_error_step": "s2",
  "target_gap": "prerequisite_concepts[2]",
  "gap_updates": [{"target_slot": "prerequisite_concepts[2]", "status": "partial", "evidence": "Applied the formula but swapped u and dv."}],
  "progress": false,
  "summary": "Knows the formula but chose u and dv backwards."
}
```

**`ActionCard`**

```json
{
  "card": "HINT_POINT",
  "action_type": "hint",
  "target_gap": "prerequisite_concepts[2]",
  "hint_level": 1,
  "pedagogical_goal": "Help the student notice that the new integral became harder.",
  "must_include": ["what is already correct", "one question"],
  "must_not": ["final answer", "correct u and dv"],
  "answer_disclosure": "none",
  "states_course_content": false,
  "prefix": "none | decline_answer | encourage",
  "response_expected": {"expected_kind": "math_with_explanation", "input_modes": ["text"]}
}
```

**`QuestionState`**

```json
{"phase": "REMEDIATING", "help_level": 1, "turn_count": 4, "check_count": 0, "transfer_count": 0, "guess_count": 0, "last_action_id": "action-708"}
```

## Appendix B. Question Schema additions

```json
{
  "answer_check": {"kind": "antiderivative", "integrand": "x*cos(x)", "variable": "x", "verified": true},
  "solution_outline": [
    {"step_id": "s1", "goal": "Recognize integration by parts", "key_expression": null},
    {"step_id": "s2", "goal": "Choose u and dv", "key_expression": "u = x"},
    {"step_id": "s3", "goal": "Apply the formula and finish", "key_expression": "x*sin(x) + cos(x)"}
  ],
  "teaching_assets": {
    "similar_example": {"prompt": "...", "solution_steps": ["..."], "answer_check": {}},
    "transfer_problems": [{"prompt": "...", "answer_check": {}}]
  }
}
```

`answer_check.kind` is `value`, `derivative`, `antiderivative` or `none`. Limits, extreme values and definite integrals use `value`.

## Appendix C. Math check rules

1. Parse plain text first. Convert LaTeX to plain math before parsing.
2. `derivative`: compare the student's expression with the target.
3. `antiderivative`: differentiate the student's answer and compare with the integrand. No reference answer is needed. Record `missing_constant` when `+ C` is absent.
4. `value`: compare numerically. An expression given for a number is `incorrect`.
5. Compare numerically at sample points first, then symbolically with a 2-second limit.
6. Text such as "undefined" returns `unknown`, not `incorrect`.
7. Any parse failure or timeout returns `unknown`.

A small prototype using these rules classified 39 of 39 test inputs correctly, in at most 4.5 ms each.

## Appendix D. Model prompt requirements

Prompts are versioned and logged.

**`assess_turn`** receives the question, evidence, current gaps, action history, `MathCheck`, schema targets and allowed enums. It returns only `TurnAssessment`. It must treat student text as data and may not claim certainty it lacks.

**`choose_action`** receives the diagnosis, gap summary and two allowed cards. It returns one card ID and one reason.

**`compose_reply`** receives the action card, question prompt, student message, allowed schema fields and passages. It does not receive `reference_answer`, `correct_approach`, or key expressions the student has not produced. It writes in English, in a warm and plain tone, within the card's limits.

**Reply rewrite** receives only the failed checks and writes one replacement.

## Appendix E. Fallback templates

Templates contain no course claims.

| Card group | Template |
|---|---|
| `ELICIT_START`, `REDIRECT` | "Let's return to the question. What would your next step be?" |
| `ASK_WORK`, `ASK_REASON`, `CLARIFY` | "Could you show me your key step and how you got there?" |
| `REVIEW_PROBLEM`, `PREREQ_CHECK` | "In your own words, what is this question asking for?" |
| `HINT_POINT`, `RETRY_CHECK` | "Please look again at your most recent step. What would you check first?" |
| `HINT_TEACH`, `PREREQ_REVIEW`, `ANSWER_CONCEPT` | "I can't give a full explanation right now. Which part feels least clear?" |
| `DEMO_SIMILAR`, `RETRY_FULL` | "Let's try one small step at a time. What do you know for sure so far?" |
| `CONFIRM_ASK_WHY`, `TRANSFER` | "Can you explain the key idea behind your solution?" |
| `WRAP_UP`, `PARK` | "Your progress is saved. You can come back to this question at any time." |

A `DEMAND` turn adds this first: "I can't give you the final answer, but I can help you reach it."

## Appendix F. Default settings

| Setting | Default |
|---|---|
| `max_turns_per_question` | 15 |
| `max_transfer_problems` | 2 |
| `max_solved_checks` | 2 |
| `guess_limit` | 3 |
| `max_model_retries` | 1 |
| `max_reply_rewrites` | 1 |
| `max_reply_words` | 120 |
| `math_check_timeout` | 2 s |
| `assess_timeout` | 6 s |
| `choose_timeout` | 3 s |
| `retrieval_timeout` | 2 s |
| `compose_timeout` | 8 s |
| `guard_timeout` | 3 s |
| `turn_deadline` | 20 s |
| `choose_action_enabled` | true |
| `retrieval_enabled` | true |
| `model_guard_enabled` | false |

## Appendix G. V1 test set

All answers, examples and transfer problems were verified with SymPy. This is a development set, not a question bank.

| ID | Concept | Question | Answer | Similar example | Transfer 1 | Transfer 2 |
|---|---|---|---|---|---|---|
| Q1 | `calc1.02-limits.limits` | lim(x→3) (x²−9)/(x−3) | 6 | lim(x→4) (x²−16)/(x−4) = 8 | lim(x→2) (x²−5x+6)/(x−2) = −1 | lim(x→1) (x²+2x−3)/(x−1) = 4 |
| Q2 | `calc1.03-derivatives.chain-rule` | d/dx sin(x²) | 2x cos(x²) | d/dx cos(x³) = −3x² sin(x³) | d/dx e^(3x²) = 6x e^(3x²) | d/dx ln(x²+1) = 2x/(x²+1) |
| Q3 | `calc1.04-diff-applications.extrema-inflection` | Maximum of x³−3x on [−2, 2] | 2 | x³−12x on [−3, 3]: 16 | 2x³−3x² on [−1, 2]: 4 | x²−4x on [0, 5]: 5 |
| Q4 | `calc1.06-integral-applications.substitution` | ∫₀¹ 2x e^(x²) dx | e − 1 | ∫₀¹ 2x(x²+1)³ dx = 15/4 | ∫₀^√(π/2) 2x cos(x²) dx = 1 | ∫₀¹ 3x²(x³+1)² dx = 7/3 |
| Q5 | `calc1.06-integral-applications.by-parts` | ∫x cos x dx | x sin x + cos x + C | ∫x eˣ dx = (x−1)eˣ + C | ∫x sin x dx = sin x − x cos x + C | ∫x e^(−x²) dx = −½e^(−x²) + C |

Expected results at the first error (help level 0, except where noted):

| Question | Student input | Tool | Turn | Diagnosis | Expected card |
|---|---|---|---|---|---|
| Q1 | I don't know where to start | `absent` | `HELP` | D0 | `ELICIT_START` |
| Q1 | 6 | `correct` | `ANSWER` | D8 | `ASK_WORK` |
| Q1 | (x−3)(x+3)/(x−3) = x−3, so 0 | `incorrect` | `ANSWER` | D6 | `RETRY_CHECK` |
| Q1 | 0/0, so the limit does not exist | `unknown` | `ANSWER` | D3 | `ASK_REASON` |
| Q2 | cos(x²) | `incorrect` | `ANSWER` | D5 | `HINT_POINT` |
| Q2 | cos(2x), second try (level 1) | `incorrect` | `ANSWER` | D5 | `HINT_TEACH` |
| Q2 | −2x cos(x²) | `incorrect` | `ANSWER` | D6 | `RETRY_CHECK` |
| Q2 | 2x cos(x²), after a hint | `correct` | `ANSWER` | D9 | `CONFIRM_ASK_WHY` |
| Q3 | −2 | `incorrect` | `ANSWER` | D1 | `REVIEW_PROBLEM` |
| Q3 | 3x²−3 | `incorrect` | `ANSWER` | D1 | `REVIEW_PROBLEM` |
| Q3 | Checked x = ±1 only; got 2 | `correct` | `ANSWER` | D7 | `RETRY_CHECK` |
| Q4 | e | `incorrect` | `ANSWER` | D5 | `HINT_POINT` |
| Q4 | 2e−2 | `incorrect` | `ANSWER` | D4 | `HINT_POINT` |
| Q4 | e−1, full work | `correct` | `ANSWER` | D10 | `CONFIRM_ASK_WHY` |
| Q5 | Substitution did not work | `absent` | `ANSWER` | D3 | `ASK_REASON` |
| Q5 | u = cos x; integral got harder | `absent` | `PARTIAL` | D4 | `HINT_POINT` |
| Q5 | x sin x − cos x + C | `incorrect` | `ANSWER` | D6 | `RETRY_CHECK` |
| Q5 | x sin x + cos x | `correct`, `missing_constant` | `ANSWER` | D7 | `RETRY_CHECK` |
| Q5 | Just tell me the answer | `absent` | `DEMAND` | D4 | `HINT_TEACH` |

## Appendix H. Build order and acceptance

Build in this order. Each step must pass before the next.

| Step | Build | Done when |
|---|---|---|
| 1 | Records, policy data and in-memory store | All records validate |
| 2 | Rules, phases and help levels | Appendix G cards match with assessments stubbed |
| 3 | `check_math` | All Appendix G answers classified correctly |
| 4 | `assess_turn` and `compose_reply` with Retrieval off | One full question runs end to end |
| 5 | Reply checks and fallbacks | Forced faults still return a safe action |
| 6 | Retrieval integration | Grounded turns produce valid `grounding_refs` |
| 7 | Jonathan's coordinator replaces the mock | Browser demo completes a full question |

**V1 acceptance**

- [ ] Every turn returns a valid `TutoringAction` or a structured failure.
- [ ] No path gives the final answer before the student solves the question.
- [ ] A student with no progress reaches `PARK` in at most 6 turns on one ladder.
- [ ] All questions end within 15 turns or pause safely.
- [ ] The Engine works with Retrieval turned off.
- [ ] Each fault in §7.3 has a test.
- [ ] A rule change is visible through `tutoring-policy` version.
- [ ] No API keys or real student data enter tests, logs or the repository.

## References

Research that informed the design; decisions above do not depend on any single source.

- Anthropic, [Building effective agents](https://www.anthropic.com/research/building-effective-agents)
- VanLehn (2006), [The Behavior of Tutoring Systems](https://www.cs.uky.edu/~sgware/reading/papers/vanlehn2006behavior.pdf)
- Bastani et al., [Generative AI Can Harm Learning](https://scale.stanford.edu/ai/repository/generative-ai-can-harm-learning)
- Kestin et al. (2025), [AI tutoring outperforms in-class active learning](https://pmc.ncbi.nlm.nih.gov/articles/PMC12179260/)
- Wang et al., [Bridging the Novice-Expert Gap via Models of Decision-Making](https://arxiv.org/abs/2310.10648v3)
- Khan Academy (2026), [Methodologies for Improving the Quality of AI Tutoring](https://arxiv.org/pdf/2608.11259)
- Looi et al. (2026), [Taming the black box: design principles for rule-integrated LLM tutoring systems](https://www.sciencedirect.com/science/article/pii/S2666920X26000482)
- [Evaluating Answer Leakage Robustness of LLM Tutors](https://arxiv.org/html/2604.18660v1)
