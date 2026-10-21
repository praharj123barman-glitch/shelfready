import type { ChatAnswer, ChatTurn, FeedbackResult, Health, RunResponse } from "./types";

// 127.0.0.1, not localhost: uvicorn listens on IPv4 only, and browsers try IPv6 (::1) first
// for "localhost", which cost about 300 ms on every new connection to the API
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// artwork files the checker reads: PDFs, and photos or scans (read by OCR, see backend artwork/ocr.py)
export const ARTWORK_ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp";

export class ApiError extends Error {}

/** FastAPI sends a string for our own errors and a list for validation errors. */
function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => {
        const field = Array.isArray(d?.loc) ? d.loc[d.loc.length - 1] : "input";
        return `${field}: ${d?.msg ?? "invalid value"}`;
      })
      .join("; ");
  }
  return `Request failed (${status})`;
}

// How long to wait before telling the user, instead of spinning forever. A review with fresh AI calls
// takes 10 to 40 s; the slowest case (every free model busy, then retried) can take a few minutes.
const QUICK_MS = 20_000;
const REVIEW_MS = 300_000;
const CHAT_MS = 120_000;
// a gateway (the demo's tunnel, or a host) answering because the checker did not
const GATEWAY_STATUSES = new Set([502, 503, 504, 524, 530]);

async function request<T>(path: string, init?: RequestInit, timeoutMs = QUICK_MS): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  } catch (e) {
    if (e instanceof DOMException && e.name === "TimeoutError")
      throw new ApiError(`The checker did not answer within ${Math.round(timeoutMs / 1000)} s. Please try again in a minute.`);
    throw new ApiError(
      `The checker service cannot be reached (${API_URL}). If you are using the live demo, the checker runs on the ` +
      "author's computer and may be offline: try again later, or run ShelfReady locally (see the README).",
    );
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    if (body?.detail === undefined && GATEWAY_STATUSES.has(res.status))
      throw new ApiError(`The checker is offline or restarting (HTTP ${res.status}). Please try again in a minute.`);
    throw new ApiError(errorMessage(body?.detail, res.status));
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
  return request<RunResponse>("/api/review", { method: "POST", body: form }, REVIEW_MS);
}

/** A finished review again (after a page refresh), with the current waivers applied. */
export const getRun = (runId: string) => request<RunResponse>(`/api/runs/${encodeURIComponent(runId)}`, undefined, CHAT_MS);

export function askAboutFinding(runId: string, findingId: string, question: string, history: ChatTurn[]) {
  return request<ChatAnswer>(`/api/runs/${runId}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ finding_id: findingId, question, history }),
  }, CHAT_MS);
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

export interface CompareInput {
  useAi: boolean;
  useSampleV2: boolean;
  artwork?: File | null;
}

export function compareProof(previousRunId: string, input: CompareInput): Promise<RunResponse> {
  const form = new FormData();
  form.set("use_ai", String(input.useAi));
  form.set("use_sample_v2", String(input.useSampleV2));
  if (!input.useSampleV2 && input.artwork) form.set("artwork", input.artwork);
  return request<RunResponse>(`/api/runs/${previousRunId}/compare`, { method: "POST", body: form }, REVIEW_MS);
}
