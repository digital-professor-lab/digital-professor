import type { TurnRequest, TurnResult } from "./types";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({ detail: response.statusText }));
  if (!response.ok) throw new Error(body.detail ?? "Request failed.");
  return body as T;
}

export const api = {
  runTurn: (body: TurnRequest) => request<TurnResult>("/api/turns", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
};
