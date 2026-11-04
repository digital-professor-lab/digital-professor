export interface TurnRequest {
  user_id: string;
  course_id: string;
  session_id: string;
  turn_id: string;
  question_id: string;
  attempt_id: string;
  submitted_text: string;
  evidence_kind: "initial_attempt" | "revision";
  parent_submission_id: string | null;
  parent_evidence_id: string | null;
  response_to_action_id: string | null;
  student_explanation: string | null;
  student_uncertainty: { level: string };
}

export interface TurnResult {
  handoff_status: "complete";
  submission: { submission_id: string; submitted_text: string };
  evidence: { evidence_id: string; validation_status: string; confirmed_content: string };
  action: { action_id: string; action_type: string; content: { format: string; text: string } };
  delivery: { presentation_status: string };
  trace_events: Array<{ event_id: string; event_type: string }>;
}

export interface RecognitionAmbiguity {
  ambiguity_id: string;
  page_number?: number | null;
  region?: string | null;
  raw_value?: string;
  candidates?: string[];
  confidence?: number | null;
  meaning_may_change: boolean;
  description?: string;
}

export interface HandwritingReview {
  confirmation_required: boolean;
  submission: {
    submission_id: string;
    original_artifact_ref: string;
    modality: "handwriting_upload" | "stylus_canvas";
  };
  recognition: {
    recognition_id: string;
    recognized_content: string;
    recognition_status: "recognized" | "confirmation_required" | "partial";
    provider: string;
    model_version: string;
    ambiguities: RecognitionAmbiguity[];
    page_count: number;
    processed_pages: number[];
    latency_ms: number | null;
  };
}

export interface HandwritingContext {
  user_id: string;
  course_id: string;
  session_id: string;
  turn_id: string;
  question_id: string;
  attempt_id: string;
  evidence_kind: "initial_attempt" | "revision";
  parent_submission_id: string | null;
  parent_evidence_id: string | null;
  response_to_action_id: string | null;
  student_explanation: string | null;
  student_uncertainty: string;
  modality: "handwriting_upload" | "stylus_canvas";
}

export interface ConfirmedHandwritingTurn {
  corrections: Array<{ correction_id: string; correction_type: string; meaning_changed: boolean }>;
  result: TurnResult;
}
