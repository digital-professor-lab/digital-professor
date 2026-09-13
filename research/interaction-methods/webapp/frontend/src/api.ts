import type { ProviderConfig, SkillInstructions, SourceRecord, TranscriptionResult, TutorResponse } from "./types";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? "Request failed.");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  config: () => request<ProviderConfig>("/api/config"),
  sources: () => request<SourceRecord[]>("/api/sources"),
  upload: (file: File, sourceType: string, recognitionProvider = "openai_vision") => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_type", sourceType);
    form.append("recognition_provider", recognitionProvider);
    return request<SourceRecord>("/api/sources", { method: "POST", body: form });
  },
  removeSource: (id: string) => request<void>(`/api/sources/${id}`, { method: "DELETE" }),
  transcribe: (file: File, provider: string, model: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("model", model);
    form.append("provider", provider);
    return request<TranscriptionResult>("/api/transcriptions", { method: "POST", body: form });
  },
  chat: (body: {
    question: string;
    model: string;
    input_cost_per_1m: number | null;
    output_cost_per_1m: number | null;
    skills: SkillInstructions;
  }) =>
    request<TutorResponse>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};
