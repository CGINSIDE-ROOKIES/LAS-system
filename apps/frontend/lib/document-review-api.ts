import { getApiBaseUrl } from "./api-config";

export type DocumentReviewStatus = "queued" | "running" | "hitl_waiting" | "applying" | "completed" | "failed";
export type DocumentReviewStage =
  | "upload_saved"
  | "parser_started"
  | "parser_completed"
  | "review_started"
  | "review_progress"
  | "hitl_waiting"
  | "apply_started"
  | "apply_completed"
  | "completed"
  | "failed";

export type DocumentReviewOptions = {
  relevance_mode?: "disabled" | "keyword_only" | "keyword_then_llm";
  boundary_review_enabled?: boolean;
  label_review_enabled?: boolean;
  parser_max_concurrent_workers?: number;
  parser_llm_repair_max_attempts?: number;
  prompt_profile?: string;
  top_k?: number;
  max_clauses?: number | null;
  max_clause_chars?: number;
  max_source_text_chars?: number;
  max_sources_per_finding?: number;
  max_concurrent_risk_reviews?: number;
  max_generation_repair_attempts?: number;
  max_generation_provider_retry_attempts?: number;
  generation_provider_retry_base_delay_sec?: number;
  doc_types?: string[] | null;
  law_names?: string[] | null;
  source_doc_type?: "subcontract" | "employment" | "service" | "nda" | "other" | null;
  include_review_html?: boolean;
  review_title?: string;
  hitl_min_risk_level?: "none" | "low" | "mid" | "high" | "crit";
};

export type CreateDocumentReviewResponse = {
  review_id: string;
  status: DocumentReviewStatus;
  events_url: string;
};

export type DocumentReviewSummary = {
  review_id: string;
  status: DocumentReviewStatus;
  stage: DocumentReviewStage;
  progress: number;
  source_name: string;
  source_doc_type: string | null;
  current_preview_kind: "parser" | "risk" | "edited" | null;
  risk_counts: Record<string, number>;
  artifact_flags: Record<string, boolean>;
  preview_url: string;
  events_url: string;
  suggestions_url: string;
  download_url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type DocumentReviewSuggestion = {
  finding_id: string;
  request_id: string | null;
  clause_id: string | null;
  risk_level: string | null;
  status: "pending" | "accepted" | "rejected" | "feedback";
  title: string;
  kind: string;
  prompt: string;
  guidance: string;
  selected_text: string;
  diff: string | null;
  source_citations: string[];
  proposed_edit: Record<string, unknown> | null;
  allowed_actions: string[];
  payload: Record<string, unknown>;
};

export type DocumentReviewEvent = {
  type: DocumentReviewStage;
  seq: number;
  timestamp?: string | null;
  progress?: number;
  reviewed_clauses?: number;
  total_clauses?: number;
  preview_url?: string;
  suggestions_url?: string;
  download_url?: string;
  finding_id?: string;
  action?: string;
  error?: string;
  [key: string]: unknown;
};

export type ApplyDocumentReviewResponse = {
  review_id: string;
  status: DocumentReviewStatus;
  stage: DocumentReviewStage;
  edits_applied: number;
  skipped_conflicts: string[];
  download_url: string | null;
  preview_url: string;
  warnings: string[];
};

export class DocumentReviewApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly body: unknown
  ) {
    super(message);
    this.name = "DocumentReviewApiError";
  }
}

export function absoluteApiUrl(pathOrUrl: string): string {
  if (/^https?:\/\//.test(pathOrUrl)) return pathOrUrl;
  return `${getApiBaseUrl()}${pathOrUrl}`;
}

export async function createDocumentReview(
  file: File,
  options?: DocumentReviewOptions
): Promise<CreateDocumentReviewResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (options) formData.append("options", JSON.stringify(options));
  const res = await fetch(`${getApiBaseUrl()}/api/v1/document-reviews`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) await throwDocumentReviewApiError(res);
  return res.json();
}

export async function getDocumentReview(reviewId: string): Promise<DocumentReviewSummary> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/document-reviews/${reviewId}`);
  if (!res.ok) await throwDocumentReviewApiError(res);
  return res.json();
}

export async function getDocumentReviewSuggestions(reviewId: string): Promise<DocumentReviewSuggestion[]> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/document-reviews/${reviewId}/suggestions`);
  if (!res.ok) await throwDocumentReviewApiError(res);
  const data = await res.json();
  return Array.isArray(data.items) ? data.items : [];
}

export async function decideDocumentReviewSuggestion(
  reviewId: string,
  findingId: string,
  body: { action: "accept" | "reject" | "feedback"; comment?: string }
): Promise<DocumentReviewSuggestion> {
  const res = await fetch(
    `${getApiBaseUrl()}/api/v1/document-reviews/${reviewId}/suggestions/${encodeURIComponent(findingId)}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!res.ok) await throwDocumentReviewApiError(res);
  return res.json();
}

export async function resumeDocumentReview(reviewId: string): Promise<{
  review_id: string;
  status: DocumentReviewStatus;
  stage: DocumentReviewStage;
  decisions_applied: number;
}> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/document-reviews/${reviewId}/resume`, {
    method: "POST",
  });
  if (!res.ok) await throwDocumentReviewApiError(res);
  return res.json();
}

export async function applyDocumentReview(reviewId: string): Promise<ApplyDocumentReviewResponse> {
  const res = await fetch(`${getApiBaseUrl()}/api/v1/document-reviews/${reviewId}/apply`, {
    method: "POST",
  });
  if (!res.ok) await throwDocumentReviewApiError(res);
  return res.json();
}

async function throwDocumentReviewApiError(res: Response): Promise<never> {
  const body = await res.json().catch(() => null);
  const detail = body && typeof body === "object" && "error" in body
    ? String((body as { error?: unknown }).error)
    : body && typeof body === "object" && "detail" in body
      ? String((body as { detail?: unknown }).detail)
      : res.statusText;
  throw new DocumentReviewApiError(res.status, detail || res.statusText, body);
}
