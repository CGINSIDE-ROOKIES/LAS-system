import { getApiBaseUrl } from "./api-config";

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
  score: number | null;
  snippet: string;
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
};
export type SseErrorEvent = { type: "error"; code: string; error: string };
export type SseEvent = SseChunkEvent | SseDoneEvent | SseErrorEvent;

async function throwApiError(res: Response): Promise<never> {
  const body = await res.json().catch(() => ({ code: "INTERNAL_ERROR", error: res.statusText }));
  throw new ApiError(body.code ?? "INTERNAL_ERROR", body.error ?? res.statusText, res.status);
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
