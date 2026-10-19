import type { ChatAnswer, ChatTurn, FeedbackResult, Health, RunResponse } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(`Cannot reach the checker service at ${API_URL}. Is the backend running?`);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(detail);
  }
  return res.json() as Promise<T>;
}

export const getHealth = () => request<Health>("/api/health");

export type Market = "US" | "India";

export interface ReviewInput {
  useSamples: boolean;
  useAi: boolean;
  market: Market;
  artwork?: File | null;
  sheet?: File | null;
  rules?: File[];
}

export function runReview(input: ReviewInput): Promise<RunResponse> {
  const form = new FormData();
  form.set("use_samples", String(input.useSamples));
  form.set("use_ai", String(input.useAi));
  form.set("market", input.market);
  if (!input.useSamples) {
    if (input.artwork) form.set("artwork", input.artwork);
    if (input.sheet) form.set("content_sheet", input.sheet);
    for (const f of input.rules ?? []) form.append("rule_files", f);
  }
  return request<RunResponse>("/api/review", { method: "POST", body: form });
}

export function askAboutFinding(runId: string, findingId: string, question: string, history: ChatTurn[]) {
  return request<ChatAnswer>(`/api/runs/${runId}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ finding_id: findingId, question, history }),
  });
}

export function sendFeedback(runId: string, findingId: string, decision: "accepted" | "false_alarm", reason = "") {
  return request<FeedbackResult>(`/api/runs/${runId}/feedback`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ finding_id: findingId, decision, reason }),
  });
}

export function removeWaiver(waiverId: string) {
  return request<{ removed: boolean }>(`/api/waivers/${waiverId}`, { method: "DELETE" });
}
