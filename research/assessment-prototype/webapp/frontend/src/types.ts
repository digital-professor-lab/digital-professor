export type Tab = "sources" | "settings" | "chat";

export interface CourseMetadata {
  course_name: string | null;
  course_number: string | null;
  semester: string | null;
  course_overview: string | null;
}

export interface TopicEntry {
  title: string;
  level: number;
  section_number: string | null;
  page_number: number | null;
}

export interface RequestMetadata {
  response_id: string | null;
  model: string;
  elapsed_seconds: number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  estimated_cost_usd: number | null;
  cost_basis: string | null;
}

export interface SourceRecord {
  id: string;
  filename: string;
  source_type: "syllabus" | "lecture_notes" | "textbook" | "document" | "handwriting";
  page_count: number;
  preview: string;
  course: CourseMetadata | null;
  topics: TopicEntry[];
  textbook_name: string | null;
  request_metadata: RequestMetadata[];
  recognition_method: "embedded_text" | "rendered_page_vision" | "tesseract_local";
  analysis_warning: string | null;
}

export interface SkillInstructions {
  tutoring_instructions: string;
  explanation_instructions: string;
  review_instructions: string;
}

export interface ProviderConfig {
  provider: string;
  model: string;
  api_key_configured: boolean;
  input_cost_per_1m: number | null;
  output_cost_per_1m: number | null;
  models: string[];
  skills: SkillInstructions;
  recognition_provider: "openai_vision" | "tesseract";
  tesseract_available: boolean;
  transcription_model: string;
  transcription_models: string[];
  transcription_provider: "openai" | "faster_whisper";
  local_transcription_models: string[];
  faster_whisper_available: boolean;
  expose_sources: boolean;
}

export interface TranscriptionResult {
  interaction_id: string;
  text: string;
  provider: string;
  model: string;
  elapsed_seconds: number;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
}

export interface SourceCitation {
  source_id: string;
  filename: string;
  page_number: number | null;
  basis: string;
}

export interface TutorResponse {
  interpreted_question: string;
  detected_equations: string[];
  answer_markdown: string;
  assumptions: string[];
  comprehension_check: string;
  citations: SourceCitation[];
  request: RequestMetadata;
}

export interface Message {
  id: string;
  role: "student" | "professor";
  text: string;
  result?: TutorResponse;
}
