import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  CheckCircle2,
  CircleDashed,
  Download,
  FileSearch,
  Loader2,
  MessageSquare,
  Play,
  RefreshCw,
  Send,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { AppSidebar } from "@/components/AppSidebar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Textarea } from "@/components/ui/textarea";
import {
  absoluteApiUrl,
  applyDocumentReview,
  createDocumentReview,
  decideDocumentReviewSuggestion,
  DocumentReviewEvent,
  DocumentReviewOptions,
  DocumentReviewStage,
  DocumentReviewSuggestion,
  DocumentReviewSummary,
  getDocumentReview,
  getDocumentReviewSuggestions,
  resumeDocumentReview,
} from "@/lib/document-review-api";
import { cn } from "@/lib/utils";

const EVENT_NAMES: DocumentReviewStage[] = [
  "upload_saved",
  "parser_started",
  "parser_completed",
  "review_started",
  "review_progress",
  "hitl_waiting",
  "apply_started",
  "apply_completed",
  "completed",
  "failed",
];

const DEFAULT_OPTIONS = JSON.stringify(
  {
    top_k: 8,
    max_clauses: 6,
    max_concurrent_risk_reviews: 2,
    hitl_min_risk_level: "low",
    include_review_html: true,
  },
  null,
  2
);

const SUMMARY_POLL_INTERVAL_MS = 15_000;

export default function DocumentReviewTest() {
  const [file, setFile] = useState<File | null>(null);
  const [optionsText, setOptionsText] = useState(DEFAULT_OPTIONS);
  const [reviewId, setReviewId] = useState("");
  const [summary, setSummary] = useState<DocumentReviewSummary | null>(null);
  const [suggestions, setSuggestions] = useState<DocumentReviewSuggestion[]>([]);
  const [events, setEvents] = useState<DocumentReviewEvent[]>([]);
  const [previewKind, setPreviewKind] = useState<"latest" | "parser" | "risk" | "edited">("latest");
  const [busy, setBusy] = useState<string | null>(null);
  const [commentByFinding, setCommentByFinding] = useState<Record<string, string>>({});
  const eventSourceRef = useRef<EventSource | null>(null);
  const seenEventKeysRef = useRef<Set<string>>(new Set());
  const toastedEventKeysRef = useRef<Set<string>>(new Set());
  const sseErrorNotifiedRef = useRef(false);

  const progress = Math.round((summary?.progress ?? 0) * 100);
  const previewFlag = summary ? previewFlagFor(previewKind, summary) : null;
  const previewAvailable = Boolean(reviewId && summary && previewFlag && summary.artifact_flags?.[previewFlag]);
  const previewSrc = useMemo(() => {
    if (!reviewId || !previewAvailable) return "";
    const safeReviewId = encodeURIComponent(reviewId);
    const cacheKey = summary?.updated_at ? `&t=${encodeURIComponent(summary.updated_at)}` : "";
    return absoluteApiUrl(`/api/v1/document-reviews/${safeReviewId}/preview.html?kind=${previewKind}${cacheKey}`);
  }, [previewAvailable, previewKind, reviewId, summary?.updated_at]);
  const acceptedEditableCount = suggestions.filter((item) => item.status === "accepted" && item.proposed_edit).length;

  const refreshAll = useCallback(async (nextReviewId = reviewId) => {
    if (!nextReviewId) return;
    const nextSummary = await getDocumentReview(nextReviewId);
    setSummary(nextSummary);
    const nextSuggestions = await getDocumentReviewSuggestions(nextReviewId);
    setSuggestions(nextSuggestions);
  }, [reviewId]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (!reviewId || !summary || !isActivelyProcessing(summary.status)) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void refreshAll(reviewId);
    }, SUMMARY_POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [refreshAll, reviewId, summary?.status]);

  function connectEvents(nextReviewId: string, eventsUrl?: string) {
    eventSourceRef.current?.close();
    sseErrorNotifiedRef.current = false;
    const source = new EventSource(absoluteApiUrl(eventsUrl ?? `/api/v1/document-reviews/${nextReviewId}/events`));
    eventSourceRef.current = source;

    for (const name of EVENT_NAMES) {
      source.addEventListener(name, (event) => {
        try {
          const payload = JSON.parse((event as MessageEvent).data) as DocumentReviewEvent;
          const eventKey = `${payload.seq}:${payload.type}`;
          const isNewEvent = !seenEventKeysRef.current.has(eventKey);
          if (isNewEvent) {
            seenEventKeysRef.current.add(eventKey);
            setEvents((prev) => [payload, ...prev].slice(0, 100));
          }
          void refreshAll(nextReviewId);
          if (isNewEvent && !toastedEventKeysRef.current.has(eventKey)) {
            toastedEventKeysRef.current.add(eventKey);
            if (payload.type === "failed") toast.error(payload.error || "Document review failed.");
            if (payload.type === "hitl_waiting") toast.info("HITL decisions are ready.");
            if (payload.type === "completed") toast.success("Document review completed.");
          }
          if (payload.type === "completed" || payload.type === "failed") {
            source.close();
            if (eventSourceRef.current === source) eventSourceRef.current = null;
          }
        } catch {
          // Ignore malformed event payloads in the test harness.
        }
      });
    }

    source.onerror = () => {
      if (eventSourceRef.current !== source || source.readyState === EventSource.CLOSED) return;
      if (!sseErrorNotifiedRef.current) {
        sseErrorNotifiedRef.current = true;
        toast.warning("Event stream disconnected; status polling is still active.");
      }
    };
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      toast.error("Select a document first.");
      return;
    }

    let options: DocumentReviewOptions;
    try {
      options = JSON.parse(optionsText || "{}") as DocumentReviewOptions;
    } catch {
      toast.error("Options JSON is invalid.");
      return;
    }

    setBusy("upload");
    setEvents([]);
    setSuggestions([]);
    setSummary(null);
    seenEventKeysRef.current.clear();
    toastedEventKeysRef.current.clear();
    sseErrorNotifiedRef.current = false;
    try {
      const created = await createDocumentReview(file, options);
      setReviewId(created.review_id);
      connectEvents(created.review_id, created.events_url);
      await refreshAll(created.review_id);
      toast.success("Review job created.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setBusy(null);
    }
  }

  async function handleDecision(findingId: string, action: "accept" | "reject" | "feedback") {
    if (!reviewId) return;
    if (action === "feedback" && !commentByFinding[findingId]?.trim()) {
      toast.error("Enter a feedback comment first.");
      return;
    }

    setBusy(`${action}:${findingId}`);
    try {
      const updated = await decideDocumentReviewSuggestion(reviewId, findingId, {
        action,
        comment: commentByFinding[findingId] || undefined,
      });
      setSuggestions((prev) =>
        prev.map((item) => (item.finding_id === findingId ? updated : item))
      );
      await refreshAll();
      toast.success(`${statusLabel(actionToStatus(action))}.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Decision failed.");
    } finally {
      setBusy(null);
    }
  }

  async function handleResume() {
    if (!reviewId) return;
    setBusy("resume");
    try {
      await resumeDocumentReview(reviewId);
      await refreshAll();
      toast.success("Review resumed.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Resume failed.");
    } finally {
      setBusy(null);
    }
  }

  async function handleApply() {
    if (!reviewId) return;
    setBusy("apply");
    try {
      await applyDocumentReview(reviewId);
      await refreshAll();
      setPreviewKind("latest");
      toast.success("Accepted edits applied.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Apply failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-10 items-center border-b border-border px-2">
            <SidebarTrigger />
          </header>

          <main className="flex-1 overflow-auto bg-muted/30 p-4">
            <div className="grid h-full min-h-[780px] gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
              <section className="space-y-4">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <FileSearch className="h-4 w-4" />
                      Document Review API Test
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <form className="space-y-3" onSubmit={handleCreate}>
                      <Input
                        type="file"
                        accept=".doc,.docx,.hwp,.hwpx,.pdf"
                        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                      />
                      <Textarea
                        className="min-h-[168px] font-mono text-xs"
                        value={optionsText}
                        onChange={(event) => setOptionsText(event.target.value)}
                      />
                      <Button className="w-full" disabled={busy === "upload"} type="submit">
                        {busy === "upload" ? <Loader2 className="animate-spin" /> : <Upload />}
                        Create Review
                      </Button>
                    </form>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Job</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="flex gap-2">
                      <Input
                        value={reviewId}
                        onChange={(event) => setReviewId(event.target.value)}
                        placeholder="review_id"
                      />
                      <Button
                        size="icon"
                        variant="outline"
                        onClick={() => void refreshAll()}
                        disabled={!reviewId}
                        title="Refresh"
                      >
                        <RefreshCw />
                      </Button>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-sm">
                        <span className="font-medium">{summary?.stage ?? "No job"}</span>
                        <Badge variant={summary?.status === "failed" ? "destructive" : "secondary"}>
                          {summary?.status ?? "idle"}
                        </Badge>
                      </div>
                      <Progress value={progress} />
                      <p className="text-xs text-muted-foreground">{progress}%</p>
                    </div>
                    {summary?.error && (
                      <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
                        {summary.error}
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      {Object.entries(summary?.risk_counts ?? {}).map(([key, value]) => (
                        <div key={key} className="rounded-md border bg-background px-2 py-1">
                          <span className="font-medium">{key}</span>: {value}
                        </div>
                      ))}
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <Button
                        variant="outline"
                        disabled={!reviewId || busy === "resume"}
                        onClick={() => void handleResume()}
                      >
                        {busy === "resume" ? <Loader2 className="animate-spin" /> : <Play />}
                        Resume
                      </Button>
                      <Button
                        variant="outline"
                        disabled={!reviewId || acceptedEditableCount === 0 || busy === "apply"}
                        onClick={() => void handleApply()}
                      >
                        {busy === "apply" ? <Loader2 className="animate-spin" /> : <Send />}
                        Apply
                      </Button>
                    </div>
                    <Button
                      asChild
                      className="w-full"
                      variant="secondary"
                      disabled={!summary?.download_url}
                    >
                      <a
                        href={summary?.download_url ? absoluteApiUrl(summary.download_url) : "#"}
                        aria-disabled={!summary?.download_url}
                      >
                        <Download />
                        Download Edited Document
                      </a>
                    </Button>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">Events</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="max-h-[220px] space-y-2 overflow-auto pr-1">
                      {events.length === 0 && <p className="text-sm text-muted-foreground">No events yet.</p>}
                      {events.map((event, index) => (
                        <div key={`${event.seq}-${index}`} className="rounded-md border bg-background p-2 text-xs">
                          <div className="flex items-center justify-between">
                            <span className="font-medium">{event.type}</span>
                            <span className="text-muted-foreground">#{event.seq}</span>
                          </div>
                          <pre className="mt-1 whitespace-pre-wrap break-words text-[11px] text-muted-foreground">
                            {JSON.stringify(event, null, 2)}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </section>

              <section className="grid min-h-0 gap-4 lg:grid-rows-[minmax(360px,1fr)_minmax(260px,0.85fr)]">
                <Card className="min-h-0">
                  <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
                    <CardTitle className="text-base">Preview</CardTitle>
                    <div className="flex flex-wrap gap-2">
                      {(["latest", "parser", "risk", "edited"] as const).map((kind) => (
                        <Button
                          key={kind}
                          size="sm"
                          variant={previewKind === kind ? "default" : "outline"}
                          disabled={summary ? !summary.artifact_flags?.[previewFlagFor(kind, summary)] : kind !== "latest"}
                          onClick={() => setPreviewKind(kind)}
                        >
                          {kind}
                        </Button>
                      ))}
                    </div>
                  </CardHeader>
                  <CardContent className="h-[calc(100%-76px)] min-h-[320px]">
                    {previewSrc ? (
                      <iframe
                        key={previewSrc}
                        className="h-full min-h-[320px] w-full rounded-md border bg-white"
                        src={previewSrc}
                        title="Document review preview"
                      />
                    ) : (
                      <div className="flex h-full min-h-[320px] items-center justify-center rounded-md border bg-background text-sm text-muted-foreground">
                        {reviewId ? "Preview artifact is not ready yet." : "Upload a document to load a preview."}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card className="min-h-0">
                  <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
                    <CardTitle className="text-base">Suggestions</CardTitle>
                    <Badge variant="secondary">{suggestions.length}</Badge>
                  </CardHeader>
                  <CardContent className="min-h-0">
                    <div className="max-h-[360px] space-y-3 overflow-auto pr-1">
                      {suggestions.length === 0 && (
                        <p className="text-sm text-muted-foreground">No suggestions available.</p>
                      )}
                      {suggestions.map((item) => {
                        const savedComment = decisionComment(item);
                        return (
                        <div
                          key={item.finding_id}
                          className={cn(
                            "rounded-md border bg-background p-3 transition-colors",
                            suggestionStateClassName(item.status)
                          )}
                        >
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div>
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge className={riskClassName(item.risk_level)}>{item.risk_level ?? "risk"}</Badge>
                                <Badge className={statusBadgeClassName(item.status)} variant="outline">
                                  {statusIcon(item.status)}
                                  {statusLabel(item.status)}
                                </Badge>
                                {item.proposed_edit && <Badge variant="secondary">edit</Badge>}
                              </div>
                              <h3 className="mt-2 text-sm font-semibold">{item.title || item.finding_id}</h3>
                              <p className="mt-1 text-xs text-muted-foreground">{item.finding_id}</p>
                            </div>
                          </div>
                          {item.guidance && <p className="mt-2 text-sm">{item.guidance}</p>}
                          {item.selected_text && (
                            <blockquote className="mt-2 rounded-md border-l-4 border-primary bg-muted/50 px-3 py-2 text-xs">
                              {item.selected_text}
                            </blockquote>
                          )}
                          {item.diff && (
                            <pre className="mt-2 max-h-32 overflow-auto rounded-md bg-muted p-2 text-xs">
                              {item.diff}
                            </pre>
                          )}
                          {savedComment && (
                            <div className="mt-2 rounded-md border bg-background/70 px-3 py-2 text-xs">
                              <span className="font-medium">Saved feedback:</span> {savedComment}
                            </div>
                          )}
                          <Textarea
                            className="mt-3 min-h-[64px]"
                            placeholder="Feedback comment"
                            value={commentByFinding[item.finding_id] ?? ""}
                            onChange={(event) =>
                              setCommentByFinding((prev) => ({
                                ...prev,
                                [item.finding_id]: event.target.value,
                              }))
                            }
                          />
                          <div className="mt-3 flex flex-wrap gap-2">
                            <Button
                              size="sm"
                              variant={item.status === "accepted" ? "default" : "outline"}
                              disabled={!item.proposed_edit || busy === `accept:${item.finding_id}`}
                              onClick={() => void handleDecision(item.finding_id, "accept")}
                            >
                              {busy === `accept:${item.finding_id}` ? <Loader2 className="animate-spin" /> : <Check />}
                              Accept
                            </Button>
                            <Button
                              size="sm"
                              variant={item.status === "rejected" ? "destructive" : "outline"}
                              disabled={busy === `reject:${item.finding_id}`}
                              onClick={() => void handleDecision(item.finding_id, "reject")}
                            >
                              <X />
                              Reject
                            </Button>
                            <Button
                              size="sm"
                              variant={item.status === "feedback" ? "default" : "secondary"}
                              disabled={busy === `feedback:${item.finding_id}`}
                              onClick={() => void handleDecision(item.finding_id, "feedback")}
                            >
                              <MessageSquare />
                              Feedback
                            </Button>
                          </div>
                        </div>
                      );
                      })}
                    </div>
                  </CardContent>
                </Card>
              </section>
            </div>
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
}

function previewFlagFor(
  kind: "latest" | "parser" | "risk" | "edited",
  summary: DocumentReviewSummary
): "parser_preview" | "risk_preview" | "edited_preview" {
  if (kind === "parser") return "parser_preview";
  if (kind === "risk") return "risk_preview";
  if (kind === "edited") return "edited_preview";
  if (summary.current_preview_kind === "edited") return "edited_preview";
  if (summary.current_preview_kind === "risk") return "risk_preview";
  return "parser_preview";
}

function isActivelyProcessing(status: DocumentReviewSummary["status"]): boolean {
  return status === "queued" || status === "running" || status === "applying";
}

function actionToStatus(action: "accept" | "reject" | "feedback"): DocumentReviewSuggestion["status"] {
  if (action === "accept") return "accepted";
  if (action === "reject") return "rejected";
  return "feedback";
}

function statusLabel(status: DocumentReviewSuggestion["status"]): string {
  if (status === "accepted") return "Accepted";
  if (status === "rejected") return "Rejected";
  if (status === "feedback") return "Feedback requested";
  return "Pending";
}

function statusIcon(status: DocumentReviewSuggestion["status"]) {
  if (status === "accepted") return <CheckCircle2 className="mr-1 h-3 w-3" />;
  if (status === "rejected") return <XCircle className="mr-1 h-3 w-3" />;
  if (status === "feedback") return <MessageSquare className="mr-1 h-3 w-3" />;
  return <CircleDashed className="mr-1 h-3 w-3" />;
}

function suggestionStateClassName(status: DocumentReviewSuggestion["status"]): string {
  return cn(
    status === "accepted" && "border-emerald-500/60 bg-emerald-50/70",
    status === "rejected" && "border-red-500/60 bg-red-50/70",
    status === "feedback" && "border-blue-500/60 bg-blue-50/70"
  );
}

function statusBadgeClassName(status: DocumentReviewSuggestion["status"]): string {
  return cn(
    "inline-flex items-center",
    status === "accepted" && "border-emerald-600 text-emerald-700",
    status === "rejected" && "border-red-600 text-red-700",
    status === "feedback" && "border-blue-600 text-blue-700"
  );
}

function decisionComment(item: DocumentReviewSuggestion): string {
  const decision = item.payload.decision;
  if (!decision || typeof decision !== "object" || !("comment" in decision)) return "";
  const comment = (decision as { comment?: unknown }).comment;
  return typeof comment === "string" ? comment : "";
}

function riskClassName(level: string | null): string {
  return cn(
    level === "crit" && "bg-red-700 text-white",
    level === "high" && "bg-red-500 text-white",
    level === "mid" && "bg-amber-500 text-white",
    level === "low" && "bg-lime-600 text-white",
    !level && "bg-secondary text-secondary-foreground"
  );
}
