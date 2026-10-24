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
