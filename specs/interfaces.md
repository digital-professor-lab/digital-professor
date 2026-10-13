# Shared Interface Specification

**Status:** Draft V0.1 for team review  
**Purpose:** Canonical records exchanged between Digital Professor components

This document defines logical contracts, not programming-language classes. Field names and meanings should remain stable across module specifications. Storage models and API payloads may add transport-specific fields, but they must not silently change these semantics.

## 1. Contract conventions

### 1.1 Common envelope

Every exchanged record must include:

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `record_id` | string/UUID | Yes | Stable identifier for this record. |
| `record_type` | string | Yes | Canonical type name from this document. |
| `schema_version` | string | Yes | Contract version, initially `0.1`. |
| `created_at` | ISO-8601 timestamp | Yes | Creation time in UTC. |
| `producer` | string | Yes | Component that created the record. |
| `status` | string | Yes | Type-specific processing or validation status. |
| `correlation_id` | string/UUID | Yes | Connects records created during one request/turn execution. |

### 1.2 Shared identifiers

| Identifier | Meaning |
|---|---|
| `user_id` | Authorized student identity or pseudonymous equivalent. |
| `course_id` | Stable course instance. |
| `session_id` | One tutoring session. |
| `question_id` | Stable assigned or student-provided question identity. |
| `turn_id` | One student-input-to-system-action cycle. |
| `attempt_id` | One answer attempt for a question. |
| `submission_id` | One captured student submission. |
| `document_id` | One logical source document. |
| `content_version` | Parsed/OCR content version used for grounding. |

Identifiers must be passed through unchanged. Components should not create a replacement identifier for an existing object.

### 1.3 Null, missing, and unknown

- A missing optional field means the producer did not supply it.
- `null` means the field applies but its value is currently unavailable.
- `unknown` should be used only where explicitly allowed as an enum value.
- Empty strings must not substitute for missing or null fields.

### 1.4 Validation result

Records that require validation should include:

| Field | Type | Meaning |
|---|---|---|
| `validation_status` | enum | `valid`, `partial`, `invalid`, or `unconfirmed`. |
| `validation_errors` | array | Machine-readable field/code/message entries. |
| `requires_human_review` | boolean | Whether automated downstream use is restricted. |

## 2. CourseContext

**Producer:** Course Context and Ingestion  
**Consumers:** Interaction, Retrieval, Tutoring Engine, Delivery

Minimum fields:

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `course_id` | string | Yes | Course instance identifier. |
| `course_name` | string | Yes | Human-readable course title. |
| `course_number` | string | No | Institutional course number. |
| `term` | string | No | Term/semester. |
| `course_overview` | string | No | Concise description from approved material. |
| `learning_objectives` | array[string] | No | Course-level objectives. |
| `topic_ids` | array[string] | No | Stable topic identifiers. |
| `source_versions` | array[object] | Yes | Approved document/content versions available to retrieval. |

Open owner decision: Ovunc should confirm whether policies, prerequisite concepts, and assessment rules belong in this record or separate records.

## 3. QuestionContext

**Producer:** Course Context and Ingestion / question-authoring workflow  
**Consumers:** Interaction, Retrieval, Tutoring Engine, Delivery

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `question_id` | string | Yes | Stable question identity. |
| `course_id` | string | Yes | Owning course. |
| `prompt` | rich text | Yes | Student-visible question. |
| `question_type` | enum | Yes | For example `worked_problem`, `conceptual`, `proof`, `open_question`. |
| `topic_ids` | array[string] | Yes | Concepts assessed or discussed. |
| `learning_objective_ids` | array[string] | No | Related objectives. |
| `expected_response_modes` | array[string] | No | Text, equation, steps, diagram, explanation, etc. |
| `reference_answer` | controlled reference | No | Instructor-approved answer or rubric reference; access may be restricted. |
| `rubric` | object/reference | No | Criteria used by the Tutoring Engine. |
| `source_refs` | array[object] | No | Course passages or document regions associated with the question. |
| `constraints` | object | No | Allowed help, tools, attempts, or disclosure level. |

## 4. StudentSubmission

**Producer:** Interaction  
**Consumers:** Recognition pipeline, Student Evidence builder, session state

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `submission_id` | string | Yes | Submission identity. |
| `user_id`, `course_id`, `session_id`, `question_id`, `turn_id` | strings | Yes | Context identifiers. |
| `attempt_id` | string | Yes | Attempt being created or continued. |
| `parent_submission_id` | string/null | No | Prior submission directly answered or revised. |
| `response_to_action_id` | string/null | No | Tutoring Action that elicited this response. |
| `modality` | enum | Yes | `text`, `handwriting_upload`, `stylus_canvas`, or `recorded_voice` in V1. |
| `original_artifact_ref` | controlled reference | Yes | Immutable reference to original student input. |
| `submitted_text` | string/null | Conditional | Original text/TeX when the modality directly supplies text. |
| `student_explanation` | string/null | No | Explanation explicitly supplied by the student. |
| `student_uncertainty` | object/null | No | Student-stated confidence or uncertainty, not model confidence. |
| `client_metadata` | object | No | Device/channel and accessibility-relevant metadata. |
| `consent_flags` | object | No | Applicable retention or diagnostic-logging choices. |

The original artifact must not be overwritten after recognition or correction.

## 5. RecognitionResult

**Producer:** Modality-specific recognizer through Interaction  
**Consumers:** Interaction confirmation flow and Student Evidence builder

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `recognition_id` | string | Yes | Recognition operation identity. |
| `submission_id` | string | Yes | Source submission. |
| `provider` and `model_version` | strings | Yes | Recognizer provenance. |
| `raw_output_ref` | reference/null | Conditional | Raw provider response when diagnostic logging is enabled. |
| `recognized_content` | rich text | Yes | Best transcription, preserving observed mathematical content. |
| `content_format` | enum | Yes | `plain_text`, `markdown_tex`, or structured multimodal form. |
| `alternatives` | array[object] | No | Local alternatives for uncertain regions. |
| `ambiguities` | array[object] | Yes | Region, candidates, confidence if available, and whether meaning may change. |
| `recognition_status` | enum | Yes | `recognized`, `confirmation_required`, `partial`, or `failed`. |
| `latency_ms` | integer | No | End-to-end recognition time. |

Provider confidence must not be treated as mathematical correctness.

## 6. RecognitionCorrection

**Producer:** Interaction based on student confirmation, automated non-semantic normalization, or human review  
**Consumers:** Student Evidence builder and trace

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `correction_id` | string | Yes | Correction identity. |
| `recognition_id` | string | Yes | Recognition result corrected. |
| `location` | object | Yes | Region/span affected. |
| `raw_value` | string | Yes | Value before correction. |
| `corrected_value` | string | Yes | Confirmed value. |
| `correction_type` | enum | Yes | `student_confirmation`, `student_edit`, `format_normalization`, or `human_review`. |
| `reason` | string/null | No | Explanation when supplied. |
| `actor_id` | string/reference | Conditional | Student, reviewer, or system actor. |
| `meaning_changed` | boolean | Yes | Whether the correction changes semantic interpretation. |
| `created_at` | timestamp | Yes | Correction time. |

Automated processing may set `meaning_changed=false` only for transformations defined as safe normalization. A meaning-changing correction requires student confirmation or explicit human review.

## 7. StudentEvidence

**Producer:** Interaction  
**Consumer:** Learner State and Tutoring Engine

Student Evidence is factual and provenance-preserving. It may identify observable steps or claims but must not label mastery, misconception, or knowledge gap.

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `evidence_id` | string | Yes | Evidence record identity. |
| `user_id`, `course_id`, `session_id`, `question_id`, `turn_id` | strings | Yes | Context identifiers. |
| `attempt_id` and `submission_id` | strings | Yes | Attempt and source submission. |
| `evidence_kind` | enum | Yes | `initial_attempt`, `revision`, `follow_up`, `explanation`, or `clarification`. |
| `original_artifact_ref` | reference | Yes | Immutable original student input. |
| `confirmed_content` | rich text/null | Conditional | Student-confirmed or sufficiently unambiguous recognized content. |
| `recognition_ref` | string/null | No | Recognition operation used. |
| `correction_refs` | array[string] | Yes | Applied correction records, possibly empty. |
| `observed_steps` | array[object] | No | Ordered student-produced steps without diagnostic labels. |
| `final_answer` | rich text/null | No | Observable answer supplied by the student. |
| `student_explanation` | string/null | No | Student's own explanation. |
| `student_uncertainty` | object/null | No | Student-stated confidence/uncertainty. |
| `prior_assistance` | array[reference] | Yes | Tutoring Actions visible before this evidence. |
| `parent_evidence_id` | string/null | No | Evidence revised or followed up. |
| `validation_status` | enum | Yes | `valid`, `partial`, `invalid`, or `unconfirmed`. |
| `unresolved_ambiguities` | array[object] | Yes | Ambiguities remaining after confirmation. |

## 8. RetrievalRequest

**Proposed producer:** Interaction coordinator or Tutoring Engine; team decision required  
**Consumer:** Course Knowledge Retrieval

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `retrieval_request_id` | string | Yes | Request identity. |
| `course_id` and `question_id` | strings | Yes | Scope. |
| `turn_id` | string | Yes | Tutoring turn. |
| `query` | string | Yes | Search expression derived from question/evidence needs. |
| `topic_ids` | array[string] | No | Structured topical filters. |
| `document_filters` | object | No | Allowed document IDs/types/versions/pages. |
| `evidence_summary` | string/object | No | Minimum student context needed to retrieve relevant support. |
| `purpose` | enum | Yes | `answer_grounding`, `diagnosis_support`, `hint_support`, `citation_check`, etc. |
| `top_k` | integer | No | Maximum requested passages. |

Do not include an unrestricted full student history when a smaller evidence summary is sufficient.

## 9. GroundingPassage and GroundingBundle

**Producer:** Course Knowledge Retrieval  
**Consumers:** Tutoring Engine and, for citation display, Delivery

### GroundingPassage

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `passage_id` | string | Yes | Stable passage identity for a content version. |
| `document_id` | string | Yes | Logical source identifier, not the entire source document. |
| `content_version` | string | Yes | Parsed/OCR version. |
| `page_number` | integer | Yes | Display/PDF page. |
| `line_start` and `line_end` | integers | Yes | Lines in normalized page text. |
| `passage_text` | string | Yes | Exact retrieved text used downstream. |
| `highlight_url` | URL | Yes | Authorized link that opens and highlights the passage. |
| `relevance_score` | number/null | No | Retrieval/reranking score if comparable and available. |
| `retrieval_rank` | integer | Yes | Final rank in this response. |

### GroundingBundle

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `grounding_bundle_id` | string | Yes | Bundle identity. |
| `retrieval_request_id` | string | Yes | Request answered. |
| `retrieval_status` | enum | Yes | `supported`, `partial`, `no_support_found`, or `failed`. |
| `passages` | array[GroundingPassage] | Yes | Ranked results, possibly empty. |
| `query_interpretation` | object/null | No | Transparent query rewrite/filter details. |
| `warnings` | array[object] | Yes | Stale version, OCR quality, missing line map, etc. |

A missing source must return `no_support_found`. It must never result in a fabricated passage or page citation.

## 10. LearnerState

**Producer:** Learner State and Tutoring Engine  
**Consumers:** Tutoring Engine, coordinator, future analytics

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `learner_state_id` | string | Yes | State version identity. |
| `user_id`, `course_id`, `session_id`, `question_id` | strings | Yes | Scope. |
| `based_on_evidence_ids` | array[string] | Yes | Evidence supporting this state. |
| `demonstrated` | array[claim] | Yes | Skills/concepts supported by evidence. |
| `unresolved` | array[claim] | Yes | Items requiring more evidence. |
| `diagnostic_hypotheses` | array[object] | Yes | Possible gaps/misconceptions with confidence and evidence refs. |
| `assistance_history_summary` | object | Yes | Help already provided. |
| `state_confidence` | object | Yes | Confidence and limitations of the interpretation. |

This record may contain interpretation. It must cite the Student Evidence used and must not rewrite that evidence.

## 11. TutoringAction

**Producer:** Learner State and Tutoring Engine  
**Consumer:** Delivery

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `action_id` | string | Yes | Action identity. |
| `session_id`, `question_id`, `turn_id` | strings | Yes | Scope. |
| `learner_state_id` | string | Yes | State that motivated the action. |
| `action_type` | enum | Yes | `question`, `hint`, `explanation`, `retry_request`, `comprehension_check`, or `transfer_problem`. |
| `pedagogical_goal` | string | Yes | Intended learning effect. |
| `content` | structured rich text | Yes | Approved student-facing content or generation instructions. |
| `grounding_refs` | array[string] | Yes | Passage IDs supporting course-specific claims. |
| `response_expected` | object | Yes | What type of student response should follow. |
| `allowed_presentations` | array[string] | Yes | Text, speech, avatar, flashcard, etc. |
| `constraints` | object | No | Detail/disclosure limits, retry rules, safety/accessibility constraints. |

The Delivery layer may reformat this action but must not change its pedagogical goal or mathematical content without returning an adaptation failure.

## 12. DeliveryResult

**Producer:** Delivery  
**Consumer:** Interaction coordinator and trace

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `delivery_result_id` | string | Yes | Result identity. |
| `action_id` | string | Yes | Action presented. |
| `channel` | enum | Yes | `chat`, `speech`, `avatar`, `flashcard`, etc. |
| `presentation_status` | enum | Yes | `presented`, `partially_presented`, `unsupported_presentation`, or `failed`. |
| `presented_content_ref` | reference | Yes | Exact representation shown/heard by the student. |
| `presented_at` | timestamp/null | Conditional | Successful presentation time. |
| `adaptations` | array[object] | Yes | Formatting/accessibility adaptations applied. |
| `next_input_capabilities` | array[string] | Yes | Modalities currently available for the response. |

## 13. InteractionTrace and InteractionTraceEvent

`InteractionTrace` is the ordered view of activity for a session or tutoring turn. It contains:

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `trace_id` | string | Yes | Trace identity. |
| `session_id` | string | Yes | Session represented. |
| `turn_id` | string/null | No | Turn represented when the trace is turn-scoped. |
| `event_ids` | array[string] | Yes | Ordered `InteractionTraceEvent` identifiers. |
| `logging_configuration_ref` | string | Yes | Configuration controlling optional diagnostic persistence. |
| `trace_status` | enum | Yes | `active`, `complete`, `partial`, or `failed`. |

The trace is an index over records and events, not a duplicate copy of every payload.

### InteractionTraceEvent

**Producer:** Any component through the session/trace service  
**Consumer:** Session continuity and optional diagnostics

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `event_id` | string | Yes | Event identity. |
| `session_id`, `turn_id`, `correlation_id` | strings | Yes | Trace scope. |
| `event_type` | string | Yes | Submission, recognition, correction, retrieval, state update, action, delivery, retry, failure, etc. |
| `record_refs` | array[string] | Yes | Records involved. |
| `operational_required` | boolean | Yes | Whether the event is necessary for session continuity. |
| `diagnostic_payload_ref` | reference/null | No | Optional details persisted only when logging is enabled. |
| `duration_ms` | integer/null | No | Component/request duration. |
| `cost` | object/null | No | Provider cost estimate and currency when rates/usage are available. |

## 14. LoggingConfiguration

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `diagnostic_logging_enabled` | boolean | Yes | Enables optional diagnostic persistence. |
| `retain_raw_artifacts` | boolean | Yes | Whether raw audio/images/provider output may persist beyond processing. |
| `retention_policy_id` | string | Yes | Applicable retention policy. |
| `redaction_policy_id` | string | Yes | Required redaction behavior. |
| `cost_tracking_enabled` | boolean | Yes | Whether token/provider usage is converted to cost. |

Operational records required to run the tutoring session are not optional logs and must be defined separately in storage/retention policy.

## 15. Example: confirmed handwriting revision

### StudentSubmission

```json
{
  "record_id": "sub-102",
  "record_type": "StudentSubmission",
  "schema_version": "0.1",
  "created_at": "2026-10-13T14:00:00Z",
  "producer": "interaction",
  "status": "received",
  "correlation_id": "corr-55",
  "submission_id": "sub-102",
  "user_id": "student-7",
  "course_id": "calc-1-fa26",
  "session_id": "session-20",
  "question_id": "q-derivative-4",
  "turn_id": "turn-3",
  "attempt_id": "attempt-2",
  "parent_submission_id": "sub-088",
  "response_to_action_id": "action-12",
  "modality": "stylus_canvas",
  "original_artifact_ref": "artifact://sub-102/original.png",
  "submitted_text": null,
  "student_explanation": "I used the product rule this time.",
  "student_uncertainty": {"level": "unsure", "note": "I may have dropped a term."}
}
```

### StudentEvidence

```json
{
  "record_id": "evidence-102",
  "record_type": "StudentEvidence",
  "schema_version": "0.1",
  "created_at": "2026-10-13T14:00:18Z",
  "producer": "interaction",
  "status": "ready",
  "correlation_id": "corr-55",
  "evidence_id": "evidence-102",
  "user_id": "student-7",
  "course_id": "calc-1-fa26",
  "session_id": "session-20",
  "question_id": "q-derivative-4",
  "turn_id": "turn-3",
  "attempt_id": "attempt-2",
  "submission_id": "sub-102",
  "evidence_kind": "revision",
  "original_artifact_ref": "artifact://sub-102/original.png",
  "confirmed_content": "d/dx[x sin(x)] = sin(x) + x cos(x)",
  "recognition_ref": "recognition-102",
  "correction_refs": ["correction-33"],
  "observed_steps": [
    {"order": 1, "content": "d/dx[x sin(x)]"},
    {"order": 2, "content": "sin(x) + x cos(x)"}
  ],
  "final_answer": "sin(x) + x cos(x)",
  "student_explanation": "I used the product rule this time.",
  "student_uncertainty": {"level": "unsure", "note": "I may have dropped a term."},
  "prior_assistance": ["action-12"],
  "parent_evidence_id": "evidence-088",
  "validation_status": "valid",
  "unresolved_ambiguities": []
}
```

The correction record explains which handwritten symbol was confirmed. The evidence does not state that the derivative is correct; that judgment belongs to the Tutoring Engine.

## 16. Compatibility and change process

- Backward-compatible additions increment the minor schema version.
- Renaming/removing a required field or changing its meaning requires a major schema version.
- Module documents should link to this file rather than redefine shared field meanings.
- Proposed changes should name affected producers and consumers and include a migration example.
- An unresolved field must be marked as an open question; teams must not use different meanings under the same name.

## 17. Review requests

### Ovunc

- Confirm `CourseContext` and `QuestionContext` fields and ownership.
- Define source-page normalization and stable line mapping.
- Confirm which question/rubric information may be sent to each downstream component.

### Sean

- Confirm `RetrievalRequest`, `GroundingPassage`, and `GroundingBundle`.
- Decide whether scores are comparable enough to expose and how `highlight_url` will resolve.
- Specify chunk identifiers, indexing versions, and behavior when no support is found.

### Team

- Assign retrieval-request ownership.
- Define minimum `LearnerState` and `TutoringAction` contracts.
- Agree on retention when diagnostic logging is disabled.
- Approve enum names and V0.1 schema/version strategy.
