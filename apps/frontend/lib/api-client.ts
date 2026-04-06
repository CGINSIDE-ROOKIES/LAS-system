import { getApiBaseUrl } from "./api-config";

// ── History ──────────────────────────────────────────────────────────────────

export interface HistorySource {
  source_id: string;
  doc_type: string;
  law_name: string;
  article_no: string | null;
  rank: number;
  score: number | null;
  snippet: string | null;
  text: string | null;
}

export interface HistoryItem {
  id: string;
  session_id: string | null;
  question: string;
  answer: string;
  law_context_status: string;
  created_at: string;
  sources: HistorySource[];
}

export interface HistoryListResponse {
  items: HistoryItem[];
  total: number;
}

export async function getHistory(params?: {
  q?: string;
  session_id?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}): Promise<HistoryListResponse> {
  const query = new URLSearchParams();
  if (params?.q) query.set("q", params.q);
  if (params?.session_id) query.set("session_id", params.session_id);
  if (params?.date_from) query.set("date_from", params.date_from);
  if (params?.date_to) query.set("date_to", params.date_to);
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.offset != null) query.set("offset", String(params.offset));

  const res = await fetch(`${getApiBaseUrl()}/api/v1/qa/history?${query}`);
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function getHistoryItem(id: string): Promise<HistoryItem> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/qa/history/${id}`);
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function deleteHistoryItem(id: string): Promise<void> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/qa/history/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) await throwApiError(res);
}

export async function deleteHistoryItems(ids: string[]): Promise<{ deleted: number }> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/qa/history`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

// ── Q&A ──────────────────────────────────────────────────────────────────────

export interface AskRequest {
  question: string;
  doc_types?: string[];
  law_names?: string[];
}

export interface RetrievedDoc {
  rank: number;
  source_id: string;
  doc_type: string;
  law_name: string;
  article_no: string;
  score: number | null;
  snippet: string;
  text?: string;
}

export type LawContextStatus = "ok" | "missing" | "supplemented";

export interface AskResponse {
  answer: string;
  retrieved_docs: RetrievedDoc[];
  law_context_status: LawContextStatus;
}

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type SseChunkEvent = { type: "chunk"; content: string };
export type SseDoneEvent = {
  type: "done";
  retrieved_docs: RetrievedDoc[];
  law_context_status: string;
  qa_id: string | null;
};
export type SseStatusEvent = { type: "status"; code: string; message: string };
export type SseErrorEvent = { type: "error"; code: string; error: string };
export type SseEvent = SseChunkEvent | SseDoneEvent | SseStatusEvent | SseErrorEvent;

async function throwApiError(res: Response): Promise<never> {
  const body = await res.json().catch(() => ({ code: "INTERNAL_ERROR", error: res.statusText }));
  console.error(`[LAS:API] ${res.status} ${res.url} — ${body.code}: ${body.error}`);
  throw new ApiError(body.code ?? "INTERNAL_ERROR", body.error ?? res.statusText, res.status);
}

export async function submitFeedback(
  qaId: string,
  body: { thumbs_up: boolean; comment?: string }
): Promise<void> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/qa/${qaId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwApiError(res);
}

export async function ask(request: AskRequest): Promise<AskResponse> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/qa/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function* askStream(
  request: AskRequest,
  signal?: AbortSignal
): AsyncGenerator<SseEvent> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/qa/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!res.ok) await throwApiError(res);
  if (!res.body) throw new ApiError("NO_BODY", "응답 본문이 없습니다.", res.status);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6).trim();
          if (!data) continue;
          try {
            yield JSON.parse(data) as SseEvent;
          } catch {
            // 파싱 불가 청크는 무시
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
