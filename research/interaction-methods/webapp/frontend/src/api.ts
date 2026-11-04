import type { ConfirmedHandwritingTurn, HandwritingContext, HandwritingReview, TurnRequest, TurnResult } from "./types";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) throw new Error(body.detail ?? body.message ?? "Request failed.");
  return body as T;
}

export const api = {
  runTurn: (body: TurnRequest) => request<TurnResult>("/api/turns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
  recognizeHandwriting: (file: File, context: HandwritingContext) => {
    const form = new FormData();
    form.append("file", file);
    Object.entries(context).forEach(([key, value]) => {
      if (value !== null) form.append(key, String(value));
    });
    return request<HandwritingReview>("/api/handwriting/recognitions", {
      method: "POST",
      body: form,
    });
  },
  confirmHandwriting: (
    recognitionId: string,
    confirmedContent: string,
    ambiguityResolutions: Record<string, string>,
  ) => request<ConfirmedHandwritingTurn>(`/api/handwriting/recognitions/${recognitionId}/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      confirmed_content: confirmedContent,
      actor_id: "browser-student",
      ambiguity_resolutions: ambiguityResolutions,
    }),
  }),
};
