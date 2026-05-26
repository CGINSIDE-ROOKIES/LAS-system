"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppSidebar } from "@/components/AppSidebar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Textarea } from "@/components/ui/textarea";
import {
  absoluteApiUrl,
  applyDocumentReview,
  createDocumentReviewWithProgress,
  decideDocumentReviewSuggestion,
  getDocumentReview,
  getDocumentReviewSuggestions,
  resumeDocumentReview,
  type DocumentReviewEvent,
  type DocumentReviewStage,
  type DocumentReviewSuggestion,
  type DocumentReviewSummary,
} from "@/lib/document-review-api";
import { cn } from "@/lib/utils";
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldAlert,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";

const SUPPORTED_FORMATS = [".hwp", ".hwpx", ".doc", ".docx", ".pdf"];
const MAX_FILE_SIZE = 50 * 1024 * 1024;
const EVENT_STAGES: DocumentReviewStage[] = [
  "upload_saved",
  "parser_started",
  "parser_progress",
  "parser_completed",
  "review_started",
  "review_progress",
  "hitl_waiting",
  "apply_started",
  "apply_completed",
  "completed",
  "failed",
];

type WorkspaceState = "idle" | "uploading" | "processing" | "reviewing" | "failed";
type DecisionAction = "accept" | "reject" | "feedback";

const riskMeta: Record<string, { label: string; badge: string; card: string; marker: string }> = {
  crit: {
    label: "치명",
    badge: "bg-red-600 text-white border-red-600",
    card: "border-l-red-500",
    marker: "bg-red-600",
  },
  high: {
    label: "높음",
    badge: "bg-rose-600 text-white border-rose-600",
    card: "border-l-rose-500",
    marker: "bg-rose-600",
  },
  mid: {
    label: "보통",
    badge: "bg-amber-500 text-white border-amber-500",
    card: "border-l-amber-500",
    marker: "bg-amber-500",
  },
  low: {
    label: "낮음",
    badge: "bg-sky-600 text-white border-sky-600",
    card: "border-l-sky-500",
    marker: "bg-sky-500",
  },
  none: {
    label: "없음",
    badge: "bg-slate-500 text-white border-slate-500",
    card: "border-l-slate-300",
    marker: "bg-slate-400",
  },
};

const statusMeta = {
  pending: { label: "대기", className: "bg-slate-100 text-slate-700 border-slate-200", surface: "" },
  accepted: {
    label: "수락",
    className: "bg-emerald-50 text-emerald-700 border-emerald-200",
    surface: "border-emerald-200 bg-emerald-50/45 shadow-[inset_0_0_0_1px_rgba(16,185,129,0.12)]",
  },
  rejected: {
    label: "거절",
    className: "bg-red-50 text-red-700 border-red-200",
    surface: "border-red-200 bg-red-50/45 shadow-[inset_0_0_0_1px_rgba(239,68,68,0.10)]",
  },
  feedback: {
    label: "피드백",
    className: "bg-blue-50 text-blue-700 border-blue-200",
    surface: "border-blue-200 bg-blue-50/45 shadow-[inset_0_0_0_1px_rgba(59,130,246,0.12)]",
  },
};

const regeneratedStatusMeta = {
  label: "재검토 대기",
  className: "bg-blue-50 text-blue-700 border-blue-200",
  surface: "border-blue-200 bg-blue-50/45 shadow-[inset_0_0_0_1px_rgba(59,130,246,0.12)]",
};

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function asPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value * 100)));
}

function cacheUrl(pathOrUrl: string): string {
  const url = previewFrameUrl(pathOrUrl);
  const joiner = url.includes("?") ? "&" : "?";
  return `${url}${joiner}t=${Date.now()}`;
}

function previewFrameUrl(pathOrUrl: string): string {
  if (!/^https?:\/\//.test(pathOrUrl)) return pathOrUrl;
  try {
    const url = new URL(pathOrUrl);
    if (url.pathname.startsWith("/api/")) {
      return `${url.pathname}${url.search}`;
    }
  } catch {
    return pathOrUrl;
  }
  return pathOrUrl;
}

function eventProgress(event: DocumentReviewEvent): number | null {
  if (typeof event.progress === "number") return Math.max(0, Math.min(1, event.progress));
  if (
    typeof event.reviewed_clauses === "number" &&
    typeof event.total_clauses === "number" &&
    event.total_clauses > 0
  ) {
    return Math.max(0, Math.min(1, event.reviewed_clauses / event.total_clauses));
  }
  return null;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "요청 처리 중 오류가 발생했습니다.";
}

function hasRegeneratedFeedback(suggestion: DocumentReviewSuggestion): boolean {
  const regeneration = suggestion.payload?.feedback_regeneration;
  return Boolean(
    regeneration &&
      typeof regeneration === "object" &&
      "status" in regeneration &&
      regeneration.status === "completed"
  );
}

function suggestionStatusMeta(suggestion: DocumentReviewSuggestion) {
  if (suggestion.status === "pending" && hasRegeneratedFeedback(suggestion)) {
    return regeneratedStatusMeta;
  }
  return statusMeta[suggestion.status];
}

function clearPreviewHoverTarget(frame: HTMLIFrameElement | null) {
  const doc = frame?.contentDocument;
  if (!doc) return;
  doc.querySelectorAll("[data-las-card-hover-target='true']").forEach((element) => {
    element.classList.remove("las-card-hover-target");
    element.removeAttribute("data-las-card-hover-target");
  });
}

function markPreviewTarget(
  frame: HTMLIFrameElement | null,
  suggestion: DocumentReviewSuggestion,
  scrollContainer?: HTMLElement | null
): DOMRect | null {
  const doc = frame?.contentDocument;
  if (!frame || !doc?.body) return null;
  clearPreviewHoverTarget(frame);
  ensurePreviewHoverStyle(doc);

  const target = findPreviewTargetElement(doc, suggestion);
  if (!target) return null;

  target.classList.add("las-card-hover-target");
  target.setAttribute("data-las-card-hover-target", "true");
  const targetRect = target.getBoundingClientRect();
  if (scrollContainer) {
    const frameRect = frame.getBoundingClientRect();
    const containerRect = scrollContainer.getBoundingClientRect();
    const targetTop =
      targetRect.top + frameRect.top - containerRect.top + scrollContainer.scrollTop;
    scrollContainer.scrollTo({
      top: Math.max(0, targetTop - scrollContainer.clientHeight / 2 + targetRect.height / 2),
      behavior: "smooth",
    });
  } else {
    target.scrollIntoView({ block: "center", inline: "nearest" });
  }
  return targetRect;
}

function ensurePreviewHoverStyle(doc: Document) {
  if (doc.getElementById("las-card-hover-style")) return;
  const style = doc.createElement("style");
  style.id = "las-card-hover-style";
  style.textContent = `
    .las-card-hover-target {
      outline: 2px solid rgba(37, 99, 235, 0.55) !important;
      outline-offset: 2px !important;
      box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.14), 0 6px 18px rgba(15, 23, 42, 0.12) !important;
      background-color: rgba(191, 219, 254, 0.55) !important;
      border-radius: 4px !important;
      transition: box-shadow 120ms ease, background-color 120ms ease, outline-color 120ms ease !important;
    }
  `;
  doc.head.appendChild(style);
}

function ensurePreviewFrameStyle(doc: Document) {
  if (doc.getElementById("las-preview-frame-style")) return;
  const style = doc.createElement("style");
  style.id = "las-preview-frame-style";
  style.textContent = `
    html,
    body {
      width: 100% !important;
      max-width: none !important;
      min-width: 0 !important;
      overflow: hidden !important;
      box-sizing: border-box !important;
    }

    body {
      margin-left: auto !important;
      margin-right: auto !important;
    }

    body > * {
      width: 100% !important;
      max-width: 100% !important;
      box-sizing: border-box !important;
    }

    p,
    div,
    section,
    article,
    main,
    table,
    td,
    th,
    img,
    svg,
    canvas {
      max-width: 100% !important;
      box-sizing: border-box !important;
    }

    table {
      width: 100% !important;
      table-layout: auto !important;
    }
  `;
  doc.head.appendChild(style);
}

function findPreviewTargetElement(doc: Document, suggestion: DocumentReviewSuggestion): HTMLElement | null {
  const selectedText = normalizePreviewText(suggestion.selected_text || "");
  if (selectedText) {
    const marked = findElementContainingText(doc.querySelectorAll("mark"), selectedText);
    if (marked) return marked;
    const inline = findElementContainingText(doc.querySelectorAll("span"), selectedText);
    if (inline) return inline;
    const paragraph = findElementContainingText(doc.querySelectorAll("p, td, li"), selectedText);
    if (paragraph) return paragraph;
  }

  const targetId = proposedEditTargetId(suggestion);
  if (targetId) {
    const node = Array.from(doc.querySelectorAll<HTMLElement>("[data-node-id]")).find(
      (element) => element.getAttribute("data-node-id") === targetId
    );
    if (node) return node;
  }

  return null;
}

function findElementContainingText(elements: NodeListOf<Element>, normalizedText: string): HTMLElement | null {
  let best: HTMLElement | null = null;
  let bestLength = Number.POSITIVE_INFINITY;
  elements.forEach((element) => {
    const htmlElement = element as HTMLElement;
    const text = normalizePreviewText(htmlElement.textContent || "");
    if (!text.includes(normalizedText)) return;
    if (text.length < bestLength) {
      best = htmlElement;
      bestLength = text.length;
    }
  });
  return best;
}

function normalizePreviewText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function proposedEditTargetId(suggestion: DocumentReviewSuggestion): string {
  const edit = suggestion.proposed_edit;
  if (edit && typeof edit === "object" && "target_id" in edit && typeof edit.target_id === "string") {
    return edit.target_id;
  }
  return "";
}

export default function ContractReviewPage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [state, setState] = useState<WorkspaceState>("idle");
  const [isDragging, setIsDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [parserProgress, setParserProgress] = useState(0);
  const [reviewProgress, setReviewProgress] = useState(0);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [eventsUrl, setEventsUrl] = useState<string | null>(null);
  const [summary, setSummary] = useState<DocumentReviewSummary | null>(null);
  const [suggestions, setSuggestions] = useState<DocumentReviewSuggestion[]>([]);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [lastEvent, setLastEvent] = useState<DocumentReviewEvent | null>(null);
  const [feedbackOpen, setFeedbackOpen] = useState<Record<string, boolean>>({});
  const [feedbackText, setFeedbackText] = useState<Record<string, string>>({});
  const [previewFrameHeight, setPreviewFrameHeight] = useState(720);
  const [busyFindingId, setBusyFindingId] = useState<string | null>(null);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const previewScrollRef = useRef<HTMLDivElement | null>(null);
  const previewFrameRef = useRef<HTMLIFrameElement | null>(null);
  const hoveredSuggestionRef = useRef<DocumentReviewSuggestion | null>(null);

  const counts = useMemo(() => {
    const accepted = suggestions.filter((item) => item.status === "accepted").length;
    const rejected = suggestions.filter((item) => item.status === "rejected").length;
    const feedback = suggestions.filter((item) => item.status === "feedback" || hasRegeneratedFeedback(item)).length;
    const pending = suggestions.filter((item) => item.status !== "accepted" && item.status !== "rejected").length;
    return {
      total: suggestions.length,
      accepted,
      rejected,
      feedback,
      pending,
      decided: accepted + rejected,
    };
  }, [suggestions]);

  const reviewReady = summary?.status === "hitl_waiting" || Boolean(summary?.artifact_flags?.risk_preview);
  const reviewComplete = counts.total > 0 && counts.pending === 0;
  const hasAcceptedEdits = suggestions.some((item) => item.status === "accepted" && item.proposed_edit);
  const sourceName = summary?.source_name || selectedFile?.name || "계약서";

  const resizePreviewFrame = useCallback(() => {
    const frame = previewFrameRef.current;
    const doc = frame?.contentDocument;
    if (!frame || !doc?.body) return;
    ensurePreviewFrameStyle(doc);
    const html = doc.documentElement;
    const nextHeight = Math.ceil(
      Math.max(
        720,
        html.scrollHeight,
        html.offsetHeight,
        doc.body.scrollHeight,
        doc.body.offsetHeight
      )
    );
    setPreviewFrameHeight(nextHeight);
  }, []);

  const refreshSummary = useCallback(async (id: string) => {
    const next = await getDocumentReview(id);
    setSummary(next);
    setDownloadUrl(next.download_url ? absoluteApiUrl(next.download_url) : null);
    if (next.preview_url) setPreviewUrl(cacheUrl(next.preview_url));
    return next;
  }, []);

  const refreshSuggestions = useCallback(async (id: string) => {
    const items = await getDocumentReviewSuggestions(id);
    setSuggestions(items);
    return items;
  }, []);

  const resetReview = useCallback(() => {
    setSelectedFile(null);
    setState("idle");
    setUploadProgress(0);
    setParserProgress(0);
    setReviewProgress(0);
    setReviewId(null);
    setEventsUrl(null);
    setSummary(null);
    setSuggestions([]);
    setPreviewUrl(null);
    setDownloadUrl(null);
    setLastEvent(null);
    setFeedbackOpen({});
    setFeedbackText({});
    setPreviewFrameHeight(720);
    setBusyFindingId(null);
    setIsFinalizing(false);
    setError(null);
    hoveredSuggestionRef.current = null;
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const validateFile = useCallback((file: File): string | null => {
    const extension = fileExtension(file.name);
    if (!SUPPORTED_FORMATS.includes(extension)) {
      return `지원 형식은 ${SUPPORTED_FORMATS.join(", ")} 입니다.`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return "파일 크기는 50MB 이하만 지원합니다.";
    }
    return null;
  }, []);

  const startReview = useCallback(
    async (file: File) => {
      const validationError = validateFile(file);
      if (validationError) {
        toast.error(validationError);
        setError(validationError);
        return;
      }

      setSelectedFile(file);
      setState("uploading");
      setError(null);
      setUploadProgress(0);
      setParserProgress(0);
      setReviewProgress(0);
      setSuggestions([]);
      setSummary(null);
      setPreviewUrl(null);
      setDownloadUrl(null);

      try {
        const created = await createDocumentReviewWithProgress(
          file,
          {
            include_review_html: true,
            hitl_min_risk_level: "low",
            max_concurrent_risk_reviews: 8,
          },
          setUploadProgress
        );
        setReviewId(created.review_id);
        setEventsUrl(created.events_url);
        setState("processing");
        await refreshSummary(created.review_id).catch(() => null);
      } catch (err) {
        const message = errorMessage(err);
        setState("failed");
        setError(message);
        toast.error(message);
      }
    },
    [refreshSummary, validateFile]
  );

  useEffect(() => {
    if (!reviewId || !eventsUrl) return;

    const source = new EventSource(absoluteApiUrl(eventsUrl));

    const handleEvent = (message: MessageEvent) => {
      const event = JSON.parse(message.data) as DocumentReviewEvent;
      setLastEvent(event);

      if (event.type === "parser_progress") {
        const progress = eventProgress(event);
        if (progress !== null) setParserProgress(progress);
      }

      if (event.type === "parser_completed") {
        setParserProgress(1);
      }

      if (event.type === "review_progress") {
        const progress = eventProgress(event);
        if (progress !== null) setReviewProgress(progress);
      }

      if (event.type === "hitl_waiting" || event.type === "completed") {
        setReviewProgress(1);
        setState("reviewing");
      }

      if (event.preview_url) setPreviewUrl(cacheUrl(event.preview_url));
      if (event.download_url) setDownloadUrl(absoluteApiUrl(event.download_url));
      if (event.error) setError(String(event.error));

      if (
        event.type === "parser_completed" ||
        event.type === "review_progress" ||
        event.type === "hitl_waiting" ||
        event.type === "apply_completed" ||
        event.type === "completed" ||
        event.type === "failed"
      ) {
        void refreshSummary(reviewId).catch(() => null);
      }

      if (event.suggestions_url || event.type === "hitl_waiting" || event.type === "completed") {
        void refreshSuggestions(reviewId).catch(() => null);
      }

      if (event.type === "failed") {
        setState("failed");
        source.close();
      }
    };

    EVENT_STAGES.forEach((stage) => source.addEventListener(stage, handleEvent as EventListener));
    source.onerror = () => {
      if (state !== "reviewing") return;
      source.close();
    };

    return () => {
      EVENT_STAGES.forEach((stage) => source.removeEventListener(stage, handleEvent as EventListener));
      source.close();
    };
  }, [eventsUrl, refreshSummary, refreshSuggestions, reviewId, state]);

  const handleFileInput = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (file) void startReview(file);
    },
    [startReview]
  );

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsDragging(false);
      const file = event.dataTransfer.files?.[0];
      if (file) void startReview(file);
    },
    [startReview]
  );

  const handleDecision = useCallback(
    async (suggestion: DocumentReviewSuggestion, action: DecisionAction, comment?: string) => {
      if (!reviewId) return;
      if (action === "feedback" && !comment?.trim()) {
        toast.error("피드백 내용을 입력해주세요.");
        return;
      }

      setBusyFindingId(suggestion.finding_id);
      try {
        const updated = await decideDocumentReviewSuggestion(reviewId, suggestion.finding_id, {
          action,
          comment: comment?.trim(),
        });
        setSuggestions((items) =>
          items.map((item) => (item.finding_id === updated.finding_id ? updated : item))
        );
        setFeedbackOpen((items) => ({ ...items, [suggestion.finding_id]: false }));
        if (action === "feedback") {
          setFeedbackText((items) => ({ ...items, [suggestion.finding_id]: "" }));
          toast.success("피드백을 반영한 새 수정안을 생성했습니다. 다시 검토해주세요.");
        }
      } catch (err) {
        toast.error(errorMessage(err));
      } finally {
        setBusyFindingId(null);
      }
    },
    [reviewId]
  );

  const finalizeReview = useCallback(async () => {
    if (!reviewId || !reviewComplete) return;
    setIsFinalizing(true);
    try {
      await resumeDocumentReview(reviewId).catch((err) => {
        const message = errorMessage(err);
        if (!message.includes("waiting for HITL")) throw err;
      });

      if (!hasAcceptedEdits) {
        await refreshSummary(reviewId).catch(() => null);
        toast.info("수락한 수정안이 없어 생성할 수정본이 없습니다.");
        return;
      }

      const applied = await applyDocumentReview(reviewId);
      setDownloadUrl(applied.download_url ? absoluteApiUrl(applied.download_url) : null);
      setPreviewUrl(cacheUrl(applied.preview_url));
      await refreshSummary(reviewId).catch(() => null);
      toast.success("수정본을 생성했습니다.");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setIsFinalizing(false);
    }
  }, [hasAcceptedEdits, refreshSummary, reviewComplete, reviewId]);

  const handleCardHover = useCallback(
    (suggestion: DocumentReviewSuggestion) => {
      hoveredSuggestionRef.current = suggestion;
      window.requestAnimationFrame(() => {
        markPreviewTarget(previewFrameRef.current, suggestion, previewScrollRef.current);
      });
    },
    []
  );

  const handleCardLeave = useCallback(() => {
    hoveredSuggestionRef.current = null;
    clearPreviewHoverTarget(previewFrameRef.current);
  }, []);

  const handlePreviewLoad = useCallback(() => {
    resizePreviewFrame();
    window.setTimeout(resizePreviewFrame, 50);
    window.setTimeout(resizePreviewFrame, 250);
    const suggestion = hoveredSuggestionRef.current;
    if (!suggestion) return;
    markPreviewTarget(previewFrameRef.current, suggestion, previewScrollRef.current);
  }, [resizePreviewFrame]);

  useEffect(() => {
    setPreviewFrameHeight(720);
    const timer = window.setTimeout(resizePreviewFrame, 0);
    return () => window.clearTimeout(timer);
  }, [previewUrl, resizePreviewFrame]);

  useEffect(() => {
    if (!previewUrl || !previewScrollRef.current) return;
    const container = previewScrollRef.current;
    const observer = new ResizeObserver(() => {
      window.requestAnimationFrame(resizePreviewFrame);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [previewUrl, resizePreviewFrame]);

  return (
    <SidebarProvider>
      <div className="flex h-screen w-full overflow-hidden bg-background">
        <AppSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-10 shrink-0 items-center border-b border-border bg-background px-2">
            <SidebarTrigger />
            <div className="ml-2 truncate text-sm font-medium">계약서 검토</div>
          </header>

          {!reviewReady ? (
            <main className="min-h-0 flex-1 overflow-auto bg-muted/30 p-6">
              {selectedFile ? (
                <ReviewLoadingWindow
                  fileName={selectedFile.name}
                  uploadProgress={uploadProgress}
                  parserProgress={parserProgress}
                  reviewProgress={reviewProgress}
                  uploadDone={Boolean(reviewId)}
                  parserDone={parserProgress >= 1 || Boolean(summary?.artifact_flags?.parser_preview)}
                  reviewDone={reviewProgress >= 1 || Boolean(summary?.artifact_flags?.risk_preview)}
                  uploadActive={state === "uploading"}
                  parserActive={state === "processing" && parserProgress < 1}
                  reviewActive={state === "processing" && parserProgress >= 1}
                  reviewDetail={
                    lastEvent?.type === "review_progress" &&
                    typeof lastEvent.reviewed_clauses === "number" &&
                    typeof lastEvent.total_clauses === "number"
                      ? `${lastEvent.reviewed_clauses}/${lastEvent.total_clauses} 조항`
                      : undefined
                  }
                  error={error}
                  onCancel={resetReview}
                />
              ) : (
                <div className="mx-auto flex max-w-4xl flex-col gap-5">
                  <div>
                    <h1 className="text-2xl font-semibold">계약서 검토</h1>
                    <p className="mt-1 text-sm text-muted-foreground">
                      계약서를 업로드하면 문서 구조 분석과 조항별 리스크 검토가 순차적으로 진행됩니다.
                    </p>
                  </div>

                  <section
                    onDragOver={(event) => {
                      event.preventDefault();
                      setIsDragging(true);
                    }}
                    onDragLeave={() => setIsDragging(false)}
                    onDrop={handleDrop}
                    className={cn(
                      "rounded-lg border-2 border-dashed bg-background p-8 transition-colors",
                      isDragging ? "border-primary bg-accent" : "border-border"
                    )}
                  >
                    <div className="flex flex-col items-center text-center">
                      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-primary">
                        <Upload className="h-7 w-7" />
                      </div>
                      <div className="mt-4 text-base font-medium">검토할 계약서를 업로드하세요</div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        HWP, HWPX, DOC, DOCX, PDF · 최대 50MB
                      </div>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept={SUPPORTED_FORMATS.join(",")}
                        className="hidden"
                        onChange={handleFileInput}
                      />
                      <Button className="mt-5" onClick={() => fileInputRef.current?.click()}>
                        <FileText className="h-4 w-4" />
                        파일 선택
                      </Button>
                    </div>
                  </section>
                </div>
              )}
            </main>
          ) : (
            <main className="flex min-h-0 flex-1 flex-col overflow-hidden bg-muted/30">
              <ResizablePanelGroup
                direction="horizontal"
                autoSaveId="contract-review-layout"
                className="min-h-0 flex-1 overflow-hidden"
              >
                <ResizablePanel defaultSize={68} minSize={45} className="min-w-0">
                  <section className="flex h-full min-w-0 flex-col overflow-hidden">
                    <div className="flex h-12 shrink-0 items-center justify-between border-b bg-background px-4">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{sourceName}</div>
                        <div className="text-xs text-muted-foreground">
                          {summary?.current_preview_kind === "edited" ? "수정본 미리보기" : "리스크 하이라이트 미리보기"}
                        </div>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => summary?.preview_url && setPreviewUrl(cacheUrl(summary.preview_url))}
                      >
                        <RefreshCw className="h-4 w-4" />
                        새로고침
                      </Button>
                    </div>
                    <div
                      ref={previewScrollRef}
                      className="scrollbar-styled min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-4"
                    >
                      {previewUrl ? (
                        <iframe
                          ref={previewFrameRef}
                          key={previewUrl}
                          src={previewUrl}
                          onLoad={handlePreviewLoad}
                          scrolling="no"
                          style={{ height: `${previewFrameHeight}px` }}
                          className="block w-full rounded-lg border bg-white shadow-sm"
                          title="계약서 검토 미리보기"
                        />
                      ) : (
                        <div className="flex h-full min-h-[520px] items-center justify-center rounded-lg border bg-background text-sm text-muted-foreground">
                          미리보기를 준비 중입니다.
                        </div>
                      )}
                    </div>
                  </section>
                </ResizablePanel>

                <ResizableHandle withHandle className="bg-border/80" />

                <ResizablePanel defaultSize={32} minSize={22} maxSize={45} className="min-w-[320px]">
                  <aside className="flex h-full w-full flex-col bg-background">
                    <div className="shrink-0 border-b p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="text-sm font-semibold">검토 카드</div>
                          <div className="text-xs text-muted-foreground">
                            {counts.decided}/{counts.total} 처리됨
                          </div>
                        </div>
                        <Badge variant="outline">{counts.pending} 대기</Badge>
                      </div>
                    </div>
                    <div className="scrollbar-styled min-h-0 flex-1 overflow-y-auto p-3">
                      {suggestions.length === 0 ? (
                        <div className="flex h-full min-h-[360px] flex-col items-center justify-center rounded-lg border border-dashed text-center text-sm text-muted-foreground">
                          <ShieldAlert className="mb-2 h-6 w-6" />
                          표시할 검토 항목이 없습니다.
                        </div>
                      ) : (
                        <div className="space-y-3">
                          {suggestions.map((suggestion) => (
                            <ReviewCard
                              key={suggestion.finding_id}
                              suggestion={suggestion}
                              busy={busyFindingId === suggestion.finding_id}
                              feedbackOpen={Boolean(feedbackOpen[suggestion.finding_id])}
                              feedbackText={feedbackText[suggestion.finding_id] || ""}
                              onFeedbackTextChange={(value) =>
                                setFeedbackText((items) => ({ ...items, [suggestion.finding_id]: value }))
                              }
                              onToggleFeedback={() =>
                                setFeedbackOpen((items) => ({
                                  ...items,
                                  [suggestion.finding_id]: !items[suggestion.finding_id],
                                }))
                              }
                              onHoverStart={handleCardHover}
                              onHoverEnd={handleCardLeave}
                              onDecision={(action, comment) => handleDecision(suggestion, action, comment)}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  </aside>
                </ResizablePanel>
              </ResizablePanelGroup>

              <BottomDock
                counts={counts}
                summary={summary}
                reviewComplete={reviewComplete}
                hasAcceptedEdits={hasAcceptedEdits}
                downloadUrl={downloadUrl}
                isFinalizing={isFinalizing}
                onFinalize={finalizeReview}
              />
            </main>
          )}
        </div>
      </div>
    </SidebarProvider>
  );
}

function ReviewLoadingWindow({
  fileName,
  uploadProgress,
  parserProgress,
  reviewProgress,
  uploadDone,
  parserDone,
  reviewDone,
  uploadActive,
  parserActive,
  reviewActive,
  reviewDetail,
  error,
  onCancel,
}: {
  fileName: string;
  uploadProgress: number;
  parserProgress: number;
  reviewProgress: number;
  uploadDone: boolean;
  parserDone: boolean;
  reviewDone: boolean;
  uploadActive: boolean;
  parserActive: boolean;
  reviewActive: boolean;
  reviewDetail?: string;
  error: string | null;
  onCancel: () => void;
}) {
  return (
    <div className="flex min-h-[calc(100vh-88px)] items-center justify-center">
      <section className="w-full max-w-xl rounded-lg border bg-background p-6 shadow-lg">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1 text-center">
            <h1 className="text-lg font-semibold">계약서를 검토중입니다...</h1>
            <p className="mt-1 truncate text-sm text-muted-foreground">{fileName}</p>
          </div>
          <Button variant="ghost" size="icon" onClick={onCancel} className="shrink-0">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="mt-6 space-y-5">
          <LoadingProgressRow
            title="업로드"
            value={uploadProgress}
            done={uploadDone}
            active={uploadActive}
          />
          <LoadingProgressRow
            title="문서 구조 분석"
            value={parserProgress}
            done={parserDone}
            active={parserActive}
          />
          <LoadingProgressRow
            title="리스크 검토"
            value={reviewProgress}
            done={reviewDone}
            active={reviewActive}
            detail={reviewDetail}
          />
        </div>

        {error && (
          <div className="mt-5 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </section>
    </div>
  );
}

function LoadingProgressRow({
  title,
  value,
  done,
  active,
  detail,
}: {
  title: string;
  value: number;
  done: boolean;
  active: boolean;
  detail?: string;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <StageIndicator done={done} active={active} />
        <div className="min-w-0 flex-1 text-sm font-medium">{title}</div>
        <div className="text-xs tabular-nums text-muted-foreground">{done ? 100 : asPercent(value)}%</div>
      </div>
      <Progress value={done ? 100 : asPercent(value)} className="h-2" />
      <div className="pl-8 text-xs text-muted-foreground">{detail || (done ? "완료" : active ? "진행 중" : "대기")}</div>
    </div>
  );
}

function StageIndicator({ done, active }: { done: boolean; active: boolean }) {
  if (done) return <CheckCircle2 className="h-5 w-5 text-emerald-600" />;
  if (active) return <Loader2 className="h-5 w-5 animate-spin text-primary" />;
  return <div className="h-5 w-5 rounded-full border border-muted-foreground/40" />;
}

function ReviewCard({
  suggestion,
  busy,
  feedbackOpen,
  feedbackText,
  onFeedbackTextChange,
  onToggleFeedback,
  onHoverStart,
  onHoverEnd,
  onDecision,
}: {
  suggestion: DocumentReviewSuggestion;
  busy: boolean;
  feedbackOpen: boolean;
  feedbackText: string;
  onFeedbackTextChange: (value: string) => void;
  onToggleFeedback: () => void;
  onHoverStart: (suggestion: DocumentReviewSuggestion) => void;
  onHoverEnd: () => void;
  onDecision: (action: DecisionAction, comment?: string) => void;
}) {
  const risk = riskMeta[suggestion.risk_level || "none"] || riskMeta.none;
  const status = suggestionStatusMeta(suggestion);
  const proposedText = getProposedText(suggestion);
  const canAccept = Boolean(suggestion.proposed_edit);
  const regenerated = hasRegeneratedFeedback(suggestion);

  return (
    <article
      onMouseEnter={() => onHoverStart(suggestion)}
      onMouseLeave={onHoverEnd}
      className={cn("rounded-lg border border-l-4 bg-background p-4 shadow-sm transition-colors", risk.card, status.surface)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={cn("rounded-md", risk.badge)}>{risk.label}</Badge>
            <Badge variant="outline" className={status.className}>
              {status.label}
            </Badge>
          </div>
          <h3 className="mt-2 text-sm font-semibold leading-snug">{suggestion.title || "검토 항목"}</h3>
        </div>
      </div>

      {suggestion.selected_text && (
        <div className="mt-3 rounded-md border bg-muted/40 p-3">
          <div className="mb-1 text-xs font-medium text-muted-foreground">문제 문구</div>
          <p className="text-sm leading-relaxed">{suggestion.selected_text}</p>
        </div>
      )}

      {suggestion.guidance && (
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{suggestion.guidance}</p>
      )}

      {proposedText && (
        <div
          className={cn(
            "mt-3 rounded-md border p-3",
            suggestion.status === "accepted"
              ? "border-emerald-200 bg-emerald-50 text-emerald-950"
              : "bg-background"
          )}
        >
          <div className="mb-1 flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <span className={cn("h-2 w-2 rounded-full", suggestion.status === "accepted" ? "bg-emerald-600" : risk.marker)} />
            {regenerated ? "피드백 반영 수정안" : "제안 수정안"}
          </div>
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{proposedText}</p>
        </div>
      )}

      {suggestion.source_citations.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {suggestion.source_citations.slice(0, 4).map((citation) => (
            <Badge key={citation} variant="secondary" className="max-w-full truncate rounded-md">
              {citation}
            </Badge>
          ))}
        </div>
      )}

      <div className="mt-4 grid grid-cols-3 gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={busy || !canAccept}
          onClick={() => onDecision("accept")}
          className="border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 hover:text-emerald-800"
        >
          <Check className="h-4 w-4" />
          수락
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => onDecision("reject")}
          className="border-red-200 bg-red-50 text-red-700 hover:bg-red-100 hover:text-red-800"
        >
          <X className="h-4 w-4" />
          거절
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={onToggleFeedback}
          className="border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 hover:text-blue-800"
        >
          <MessageSquare className="h-4 w-4" />
          피드백
        </Button>
      </div>

      {feedbackOpen && (
        <div className="mt-3 space-y-2">
          <Textarea
            value={feedbackText}
            onChange={(event) => onFeedbackTextChange(event.target.value)}
            placeholder="수정 방향이나 반영할 조건을 입력하세요."
            className="min-h-[96px] resize-none"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={busy || !feedbackText.trim()}
            onClick={() => onDecision("feedback", feedbackText)}
            className="w-full border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 hover:text-blue-800"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            제출
          </Button>
        </div>
      )}
    </article>
  );
}

function BottomDock({
  counts,
  summary,
  reviewComplete,
  hasAcceptedEdits,
  downloadUrl,
  isFinalizing,
  onFinalize,
}: {
  counts: { total: number; accepted: number; rejected: number; feedback: number; pending: number; decided: number };
  summary: DocumentReviewSummary | null;
  reviewComplete: boolean;
  hasAcceptedEdits: boolean;
  downloadUrl: string | null;
  isFinalizing: boolean;
  onFinalize: () => void;
}) {
  return (
    <footer className="flex h-20 shrink-0 items-center justify-between gap-4 border-t bg-background px-4">
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold">{summary?.source_name || "계약서"}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{counts.decided}/{counts.total} 검토 완료</span>
          <span>수락 {counts.accepted}</span>
          <span>거절 {counts.rejected}</span>
          <span>피드백 반영 {counts.feedback}</span>
          {counts.pending > 0 && <span>대기 {counts.pending}</span>}
        </div>
      </div>

      <div className="hidden min-w-0 flex-1 justify-center gap-2 lg:flex">
        {Object.entries(summary?.risk_counts || {}).map(([level, count]) => {
          if (!count) return null;
          const risk = riskMeta[level] || riskMeta.none;
          return (
            <Badge key={level} variant="outline" className="rounded-md">
              <span className={cn("mr-1.5 h-2 w-2 rounded-full", risk.marker)} />
              {risk.label} {count}
            </Badge>
          );
        })}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {downloadUrl ? (
          <Button asChild>
            <a href={downloadUrl}>
              <Download className="h-4 w-4" />
              다운로드
            </a>
          </Button>
        ) : (
          <Button disabled={!reviewComplete || isFinalizing || !hasAcceptedEdits} onClick={onFinalize}>
            {isFinalizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            수정본 생성
          </Button>
        )}
      </div>
    </footer>
  );
}

function getProposedText(suggestion: DocumentReviewSuggestion): string {
  const edit = suggestion.proposed_edit;
  if (edit && typeof edit === "object" && "new_text" in edit && typeof edit.new_text === "string") {
    return edit.new_text;
  }
  if (typeof suggestion.payload?.recommendation === "string") return suggestion.payload.recommendation;
  return "";
}
