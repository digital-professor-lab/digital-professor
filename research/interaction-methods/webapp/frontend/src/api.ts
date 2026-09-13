import type { ProviderConfig, SkillInstructions, SourceRecord, TutorResponse } from "./types";

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
  upload: (file: File, sourceType: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_type", sourceType);
    return request<SourceRecord>("/api/sources", { method: "POST", body: form });
  },
  removeSource: (id: string) => request<void>(`/api/sources/${id}`, { method: "DELETE" }),
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
