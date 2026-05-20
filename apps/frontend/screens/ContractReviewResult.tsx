"use client";

import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { toast } from "sonner";
import {
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  Download,
  Copy,
  MessageSquare,
  RefreshCw,
  Scale,
  FileText,
  BookOpen,
  ChevronRight,
  Clock,
  ExternalLink,
  Loader2,
  Check,
  X,
  Play,
  Send,
  Sparkles,
  ArrowLeft,
  Maximize2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  absoluteApiUrl,
  applyDocumentReview,
  decideDocumentReviewSuggestion,
  DocumentReviewEvent,
  DocumentReviewStage,
  DocumentReviewStatus,
  DocumentReviewSuggestion,
  DocumentReviewSummary,
  getDocumentReview,
  getDocumentReviewSuggestions,
  resumeDocumentReview,
} from "@/lib/document-review-api";

// Types matching custom configuration
type OverallStatus = "safe" | "attention" | "high-risk" | "processing";

const riskConfig: Record<string, { label: string; bgClass: string; textClass: string; borderClass: string; badgeClass: string }> = {
  crit: {
    label: "치명적 위험",
    bgClass: "bg-red-500/5 hover:bg-red-500/10 dark:bg-red-950/20 dark:hover:bg-red-950/30",
    textClass: "text-red-700 dark:text-red-400",
    borderClass: "border-red-200 dark:border-red-900/50",
    badgeClass: "bg-red-600 text-white dark:bg-red-900 dark:text-red-200"
  },
  high: {
    label: "고위험",
    bgClass: "bg-rose-500/5 hover:bg-rose-500/10 dark:bg-rose-950/20 dark:hover:bg-rose-950/30",
    textClass: "text-rose-700 dark:text-rose-400",
    borderClass: "border-rose-200 dark:border-rose-900/50",
    badgeClass: "bg-rose-600 text-white dark:bg-rose-900 dark:text-rose-200"
  },
  mid: {
    label: "주의",
    bgClass: "bg-amber-500/5 hover:bg-amber-500/10 dark:bg-amber-950/20 dark:hover:bg-amber-950/30",
    textClass: "text-amber-700 dark:text-amber-400",
    borderClass: "border-amber-200 dark:border-amber-900/50",
    badgeClass: "bg-amber-500 text-white dark:bg-amber-800 dark:text-amber-200"
  },
  low: {
    label: "참고",
    bgClass: "bg-emerald-500/5 hover:bg-emerald-500/10 dark:bg-emerald-950/20 dark:hover:bg-emerald-950/30",
    textClass: "text-emerald-700 dark:text-emerald-400",
    borderClass: "border-emerald-200 dark:border-emerald-900/50",
    badgeClass: "bg-emerald-600 text-white dark:bg-emerald-900 dark:text-emerald-200"
  },
};

const statusConfig: Record<OverallStatus, { label: string; icon: typeof ShieldCheck; className: string }> = {
  safe: { label: "안전함", icon: ShieldCheck, className: "text-emerald-600 dark:text-emerald-400" },
  attention: { label: "검토 권장", icon: AlertTriangle, className: "text-amber-600 dark:text-amber-400" },
  "high-risk": { label: "위험 조항 감지", icon: ShieldAlert, className: "text-rose-600 dark:text-rose-400" },
  processing: { label: "분석 중...", icon: Loader2, className: "text-blue-600 dark:text-blue-400 animate-spin" },
};

const STAGE_LABELS: Record<DocumentReviewStage, string> = {
  upload_saved: "파일 업로드 완료",
  parser_started: "계약서 파싱 시작",
  parser_completed: "계약서 텍스트 추출 완료",
  review_started: "법률 검토 분석 시작",
  review_progress: "조항별 분석 진행 중",
  hitl_waiting: "사용자 의견 수렴 대기 중",
  apply_started: "수정 조항 계약서 반영 시작",
  apply_completed: "계약서 수정본 반영 완료",
  completed: "법률 계약서 검토 완료",
  failed: "분석 실패",
};

const SUMMARY_POLL_INTERVAL_MS = 8_000;

export default function ContractReviewResult() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const reviewId = searchParams.get("id") || "";

  const [summary, setSummary] = useState<DocumentReviewSummary | null>(null);
  const [suggestions, setSuggestions] = useState<DocumentReviewSuggestion[]>([]);
  const [events, setEvents] = useState<DocumentReviewEvent[]>([]);
  const [previewKind, setPreviewKind] = useState<"latest" | "parser" | "risk" | "edited">("latest");
  const [busy, setBusy] = useState<string | null>(null);
  const [commentByFinding, setCommentByFinding] = useState<Record<string, string>>({});
  const [expandedFeedbackId, setExpandedFeedbackId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("all");

  const eventSourceRef = useRef<EventSource | null>(null);
  const seenEventKeysRef = useRef<Set<string>>(new Set());
  const toastedEventKeysRef = useRef<Set<string>>(new Set());
  const sseErrorNotifiedRef = useRef(false);

  const progress = Math.round((summary?.progress ?? 0) * 100);

  // Dynamic preview handling
  const previewFlag = summary ? previewFlagFor(previewKind, summary) : null;
  const previewAvailable = Boolean(reviewId && summary && previewFlag && summary.artifact_flags?.[previewFlag]);
  const previewSrc = useMemo(() => {
    if (!reviewId || !previewAvailable) return "";
    const safeReviewId = encodeURIComponent(reviewId);
    const cacheKey = summary?.updated_at ? `&t=${encodeURIComponent(summary.updated_at)}` : "";
    return absoluteApiUrl(`/api/v1/document-reviews/${safeReviewId}/preview.html?kind=${previewKind}${cacheKey}`);
  }, [previewAvailable, previewKind, reviewId, summary?.updated_at]);

  // Overall status rating derived from real risk metrics
  const overallStatus: OverallStatus = useMemo(() => {
    if (!summary) return "processing";
    if (isActivelyProcessing(summary.status)) return "processing";
    if (summary.status === "failed") return "high-risk";

    const crit = summary.risk_counts?.crit ?? 0;
    const high = summary.risk_counts?.high ?? 0;
    const mid = summary.risk_counts?.mid ?? 0;

    if (crit + high > 0) return "high-risk";
    if (mid > 0) return "attention";
    return "safe";
  }, [summary]);

  const StatusIcon = statusConfig[overallStatus].icon;

  // Sorting & Filtering suggestions
  const sortedSuggestions = useMemo(() => {
    const riskSortOrder: Record<string, number> = {
      crit: 0,
      high: 1,
      mid: 2,
      low: 3,
    };
    return [...suggestions].sort((a, b) => {
      const scoreA = riskSortOrder[a.risk_level ?? ""] ?? 99;
      const scoreB = riskSortOrder[b.risk_level ?? ""] ?? 99;
      return scoreA - scoreB;
    });
  }, [suggestions]);

  const filteredSuggestions = useMemo(() => {
    if (activeTab === "high") {
      return sortedSuggestions.filter((s) => s.risk_level === "high" || s.risk_level === "crit");
    }
    return sortedSuggestions;
  }, [sortedSuggestions, activeTab]);

  const riskCounts = useMemo(() => {
    const counts = { crit: 0, high: 0, mid: 0, low: 0 };
    suggestions.forEach((s) => {
      const level = s.risk_level;
      if (level && level in counts) {
        counts[level as keyof typeof counts]++;
      }
    });
    return counts;
  }, [suggestions]);

  const acceptedSuggestions = useMemo(() => {
    return suggestions.filter((s) => s.status === "accepted");
  }, [suggestions]);

  const hasPendingDecisions = useMemo(() => {
    return suggestions.some((s) => s.status === "pending");
  }, [suggestions]);

  const hasAppliedDecisions = useMemo(() => {
    return suggestions.some((s) => s.status === "accepted" || s.status === "rejected" || s.status === "feedback");
  }, [suggestions]);

  const refreshAll = useCallback(async (nextReviewId = reviewId) => {
    if (!nextReviewId) return;
    try {
      const nextSummary = await getDocumentReview(nextReviewId);
      setSummary(nextSummary);
      const nextSuggestions = await getDocumentReviewSuggestions(nextReviewId);
      setSuggestions(nextSuggestions);

      // Pre-fill comments in textareas from existing feedback if any
      const comments: Record<string, string> = {};
      nextSuggestions.forEach((s) => {
        const comm = decisionComment(s);
        if (comm) comments[s.finding_id] = comm;
      });
      setCommentByFinding((prev) => ({ ...comments, ...prev }));
    } catch (error) {
      console.error("의견을 불러오는 데 실패했습니다.", error);
    }
  }, [reviewId]);

  const connectEvents = useCallback((nextReviewId: string, eventsUrl?: string) => {
    eventSourceRef.current?.close();
    sseErrorNotifiedRef.current = false;
    const source = new EventSource(absoluteApiUrl(eventsUrl ?? `/api/v1/document-reviews/${nextReviewId}/events`));
    eventSourceRef.current = source;

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
            if (payload.type === "failed") {
              toast.error(payload.error || "법률 계약서 검토 중 에러가 발생했습니다.");
            } else if (payload.type === "hitl_waiting") {
              toast.info("의견 조정(HITL) 단계에 진입했습니다. 조항을 검토해주세요.");
            } else if (payload.type === "completed") {
              toast.success("계약서 검토 및 반영이 완벽하게 처리되었습니다!");
            }
          }

          if (payload.type === "completed" || payload.type === "failed") {
            source.close();
            if (eventSourceRef.current === source) eventSourceRef.current = null;
          }
        } catch {
          // Ignore
        }
      });
    }

    source.onerror = () => {
      if (eventSourceRef.current !== source || source.readyState === EventSource.CLOSED) return;
      if (!sseErrorNotifiedRef.current) {
        sseErrorNotifiedRef.current = true;
        toast.warning("실시간 정보 공유망 연결이 끊겼습니다. 상태 폴링으로 전환합니다.");
      }
    };
  }, [refreshAll]);

  useEffect(() => {
    if (!reviewId) {
      toast.error("유효하지 않은 링크입니다.");
      router.push("/contract-review");
      return;
    }
    void refreshAll(reviewId);
    connectEvents(reviewId);
    return () => {
      eventSourceRef.current?.close();
    };
  }, [reviewId, connectEvents, refreshAll, router]);

  useEffect(() => {
    if (!reviewId || !summary || !isActivelyProcessing(summary.status)) return;
    const interval = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void refreshAll(reviewId);
    }, SUMMARY_POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [refreshAll, reviewId, summary]);

  // Action methods
  const handleDecision = async (findingId: string, action: "accept" | "reject" | "feedback") => {
    if (!reviewId) return;
    const comment = commentByFinding[findingId]?.trim();
    if (action === "feedback" && !comment) {
      toast.error("LLM에 전달할 수정 및 보완 피드백을 입력해주세요.");
      return;
    }

    setBusy(`${action}:${findingId}`);
    try {
      const updated = await decideDocumentReviewSuggestion(reviewId, findingId, {
        action,
        comment: action === "feedback" ? comment : undefined,
      });
      setSuggestions((prev) =>
        prev.map((item) => (item.finding_id === findingId ? updated : item))
      );
      toast.success(
        action === "accept"
          ? "수정 의견을 수락했습니다."
          : action === "reject"
          ? "수정 의견을 제외했습니다."
          : "의견 수정을 제출했습니다. 아래 재생성 버튼을 통해 반영할 수 있습니다."
      );
      await refreshAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "의사결정 반영에 실패했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const handleResume = async () => {
    if (!reviewId) return;
    setBusy("resume");
    toast.info("결정된 피드백 사항들을 반영하여 계약서 분석을 다시 시작합니다...");
    try {
      await resumeDocumentReview(reviewId);
      await refreshAll();
      toast.success("계약서 다시 쓰는 중... 잠시 기다려주세요.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "다시 분석하기 요청에 실패했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const handleApply = async () => {
    if (!reviewId) return;
    setBusy("apply");
    toast.info("수정안 수락 사항들을 계약서 문서 원본에 병합하는 중입니다...");
    try {
      await applyDocumentReview(reviewId);
      await refreshAll();
      setPreviewKind("latest");
      toast.success("계약서 수정 최종 컴파일이 끝났습니다!");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "수정안 빌드에 실패했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    toast.success("해당 조항 분석 정보가 클립보드에 복사되었습니다.");
  };

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full font-sans bg-background">
        <AppSidebar />
        <div className="flex flex-1 flex-col overflow-hidden">
          <header className="flex h-12 items-center justify-between border-b border-border bg-card px-4">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                onClick={() => router.push("/contract-review")}
                className="h-8 w-8 text-muted-foreground hover:text-foreground"
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <SidebarTrigger />
              <Separator orientation="vertical" className="h-4 mx-1" />
              <span className="text-sm font-medium truncate max-w-[200px] sm:max-w-xs">
                {summary?.source_name ?? "계약서 상세 검토"}
              </span>
            </div>
            
            {summary && (
              <Badge variant={summary.status === "failed" ? "destructive" : "outline"} className="text-xs">
                {STAGE_LABELS[summary.stage] ?? summary.stage}
              </Badge>
            )}
          </header>

          {/* Summary Dashboard Bar */}
          {summary && (
            <div className="border-b border-border bg-card/60 px-6 py-3 backdrop-blur-sm z-10">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className={cn("flex items-center gap-2 font-semibold text-base", statusConfig[overallStatus].className)}>
                    <StatusIcon className="h-5 w-5" />
                    <span>{statusConfig[overallStatus].label}</span>
                  </div>
                  <Separator orientation="vertical" className="h-5" />
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="secondary" className="font-normal text-[11px]">
                      {summary.source_doc_type === "employment" && "근로계약서"}
                      {summary.source_doc_type === "subcontract" && "하도급 계약서"}
                      {summary.source_doc_type === "service" && "용역 계약서"}
                      {summary.source_doc_type === "nda" && "비밀유지계약서"}
                      {summary.source_doc_type === "other" && "기타 계약서"}
                      {!summary.source_doc_type && "미지정 유형"}
                    </Badge>
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {new Date(summary.created_at).toLocaleDateString("ko-KR", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2">
                    {riskCounts.crit + riskCounts.high > 0 && (
                      <Badge className="bg-red-500/10 hover:bg-red-500/10 text-red-700 dark:text-red-400 border-red-200 dark:border-red-900/50 text-[11px] font-semibold gap-1">
                        고위험/치명적 {riskCounts.crit + riskCounts.high}
                      </Badge>
                    )}
                    {riskCounts.mid > 0 && (
                      <Badge className="bg-amber-500/10 hover:bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-900/50 text-[11px] font-semibold">
                        주의 {riskCounts.mid}
                      </Badge>
                    )}
                    {riskCounts.low > 0 && (
                      <Badge className="bg-emerald-500/10 hover:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-900/50 text-[11px] font-semibold">
                        참고 {riskCounts.low}
                      </Badge>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Active Job Processing Loading View */}
          {summary && isActivelyProcessing(summary.status) ? (
            <div className="flex-1 flex flex-col items-center justify-center bg-muted/20 p-6">
              <Card className="w-full max-w-md bg-card/80 border-border/60 shadow-xl backdrop-blur-sm relative overflow-hidden">
                <div className="absolute top-0 left-0 w-full h-[3px] bg-gradient-to-r from-blue-500 via-indigo-500 to-purple-500 animate-pulse" />
                <CardHeader className="pb-3 text-center">
                  <CardTitle className="text-lg flex items-center justify-center gap-2">
                    <Loader2 className="h-5 w-5 animate-spin text-primary" />
                    계약서 인공지능 분석 중
                  </CardTitle>
                  <CardDescription className="text-xs">
                    법률 지식 베이스를 참고하여 조항 검토 조서를 준비하고 있습니다.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-xs font-semibold">
                      <span>분석 진행 상태</span>
                      <span>{progress}%</span>
                    </div>
                    <Progress value={progress} className="h-2.5 bg-muted/60" />
                  </div>

                  <Separator className="my-2" />

                  {/* Checklist steps */}
                  <div className="space-y-2.5 text-xs text-muted-foreground">
                    <div className="flex items-center gap-2">
                      <Check className="h-4 w-4 text-emerald-500 font-bold" />
                      <span className="text-foreground">계약서 원본 파일 업로드 완료</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {progress >= 30 ? (
                        <Check className="h-4 w-4 text-emerald-500 font-bold" />
                      ) : (
                        <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                      )}
                      <span className={cn(progress >= 30 && "text-foreground")}>
                        조항 텍스트 분리 및 분석 토큰 추출
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {progress >= 60 ? (
                        <Check className="h-4 w-4 text-emerald-500 font-bold" />
                      ) : progress >= 30 ? (
                        <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                      ) : (
                        <span className="w-4 h-4 rounded-full border border-border inline-block" />
                      )}
                      <span className={cn(progress >= 60 && "text-foreground")}>
                        판례 및 유관 법률 조문 연동 RAG 위험성 심사
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {progress >= 90 ? (
                        <Check className="h-4 w-4 text-emerald-500 font-bold" />
                      ) : progress >= 60 ? (
                        <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                      ) : (
                        <span className="w-4 h-4 rounded-full border border-border inline-block" />
                      )}
                      <span className={cn(progress >= 90 && "text-foreground")}>
                        대화식 의견반영 컴파일 및 최종보고 조서 렌더링
                      </span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          ) : (
            /* Main review split workspace */
            <div className="flex-1 flex flex-col md:flex-row overflow-hidden relative pb-[84px]">
              {/* Left Pane: Interactive Document Iframe Preview */}
              <div className="flex-1 flex flex-col border-r border-border min-h-0 bg-muted/10">
                <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2">
                  <span className="text-xs font-semibold flex items-center gap-1.5">
                    <FileText className="h-3.5 w-3.5 text-primary" />
                    계약서 실시간 미리보기
                  </span>
                  
                  {summary && (
                    <div className="flex items-center gap-1 bg-muted/60 p-0.5 rounded-lg border border-border/40">
                      {(["latest", "parser", "risk", "edited"] as const).map((kind) => {
                        const flag = previewFlagFor(kind, summary);
                        const isAvailable = Boolean(summary.artifact_flags?.[flag] || kind === "latest");
                        return (
                          <Button
                            key={kind}
                            size="sm"
                            variant={previewKind === kind ? "default" : "ghost"}
                            className={cn(
                              "h-6 text-[10px] px-2 rounded-md transition-all font-medium",
                              previewKind === kind ? "shadow-sm bg-background text-foreground hover:bg-background" : "text-muted-foreground"
                            )}
                            disabled={!isAvailable}
                            onClick={() => setPreviewKind(kind)}
                          >
                            {kind === "latest" && "통합"}
                            {kind === "parser" && "파싱"}
                            {kind === "risk" && "위험"}
                            {kind === "edited" && "수정본"}
                          </Button>
                        );
                      })}
                    </div>
                  )}
                </div>

                <div className="flex-1 p-4 flex flex-col min-h-0">
                  {previewSrc ? (
                    <iframe
                      key={previewSrc}
                      className="w-full flex-1 rounded-xl border border-border/80 shadow-md bg-white overflow-hidden min-h-[300px]"
                      src={previewSrc}
                      title="계약서 조항 실시간 프리뷰"
                    />
                  ) : (
                    <div className="flex-1 flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/50 p-6 text-center shadow-inner">
                      <FileText className="h-12 w-12 text-muted-foreground/30 mb-2" />
                      <p className="text-xs text-muted-foreground">
                        {reviewId ? "시각화용 계약서 원문이 빌드되는 중입니다." : "문서가 아직 분석 중이거나 업로드되지 않았습니다."}
                      </p>
                    </div>
                  )}
                </div>
              </div>

              {/* Right Pane: AI suggestions list */}
              <div className="w-full md:w-[480px] lg:w-[540px] shrink-0 flex flex-col bg-card min-h-0 border-t md:border-t-0 border-border">
                <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-1 flex-col min-h-0">
                  <div className="border-b border-border bg-card/40 px-4 pt-2">
                    <TabsList className="w-full grid grid-cols-3 bg-muted/40 p-0.5 rounded-lg border border-border/20">
                      <TabsTrigger value="all" className="text-xs py-1.5 font-medium rounded-md">
                        전체 의견 ({suggestions.length})
                      </TabsTrigger>
                      <TabsTrigger value="high" className="text-xs py-1.5 font-medium rounded-md">
                        핵심 위험 ({riskCounts.crit + riskCounts.high})
                      </TabsTrigger>
                      <TabsTrigger value="references" className="text-xs py-1.5 font-medium rounded-md">
                        법률 근거
                      </TabsTrigger>
                    </TabsList>
                  </div>

                  <ScrollArea className="flex-1 min-h-0">
                    <div className="p-4 space-y-4">
                      {/* Suggestion Cards */}
                      <TabsContent value="all" className="m-0 space-y-3 outline-none">
                        {filteredSuggestions.length === 0 ? (
                          <div className="text-center py-12 text-muted-foreground text-xs">
                            감지된 법적 검토 의견 조항이 없습니다.
                          </div>
                        ) : (
                          filteredSuggestions.map((item) => (
                            <SuggestionCard
                              key={item.finding_id}
                              item={item}
                              busy={busy}
                              commentText={commentByFinding[item.finding_id] ?? ""}
                              isExpanded={expandedFeedbackId === item.finding_id}
                              onSetComment={(text) =>
                                setCommentByFinding((prev) => ({ ...prev, [item.finding_id]: text }))
                              }
                              onToggleExpand={() =>
                                setExpandedFeedbackId(expandedFeedbackId === item.finding_id ? null : item.finding_id)
                              }
                              onDecision={handleDecision}
                              onCopy={handleCopy}
                            />
                          ))
                        )}
                      </TabsContent>

                      <TabsContent value="high" className="m-0 space-y-3 outline-none">
                        {filteredSuggestions.length === 0 ? (
                          <div className="text-center py-12 text-muted-foreground text-xs">
                            고위험군 또는 치명적인 검토 의견 조항이 없습니다.
                          </div>
                        ) : (
                          filteredSuggestions.map((item) => (
                            <SuggestionCard
                              key={item.finding_id}
                              item={item}
                              busy={busy}
                              commentText={commentByFinding[item.finding_id] ?? ""}
                              isExpanded={expandedFeedbackId === item.finding_id}
                              onSetComment={(text) =>
                                setCommentByFinding((prev) => ({ ...prev, [item.finding_id]: text }))
                              }
                              onToggleExpand={() =>
                                setExpandedFeedbackId(expandedFeedbackId === item.finding_id ? null : item.finding_id)
                              }
                              onDecision={handleDecision}
                              onCopy={handleCopy}
                            />
                          ))
                        )}
                      </TabsContent>

                      <TabsContent value="references" className="m-0 space-y-3 outline-none">
                        {suggestions.filter((s) => s.source_citations?.length > 0).length === 0 ? (
                          <div className="text-center py-12 text-muted-foreground text-xs">
                            관련 근거 법령 및 판례 정보가 존재하지 않습니다.
                          </div>
                        ) : (
                          suggestions
                            .filter((s) => s.source_citations?.length > 0)
                            .map((item) => (
                              <Card key={item.finding_id} className="text-sm border-border bg-card shadow-sm hover:shadow transition-all">
                                <CardContent className="space-y-3 p-4">
                                  <div className="flex items-center gap-2">
                                    {item.risk_level && riskConfig[item.risk_level] && (
                                      <Badge className={cn("text-[10px] font-semibold px-2 py-0.5", riskConfig[item.risk_level].badgeClass)}>
                                        {riskConfig[item.risk_level].label}
                                      </Badge>
                                    )}
                                    <span className="font-semibold text-foreground truncate max-w-[280px]">{item.title}</span>
                                  </div>
                                  <Separator />
                                  {item.source_citations.map((cite, idx) => (
                                    <div key={idx} className="rounded-lg border border-border/80 bg-muted/40 p-3">
                                      <div className="flex items-center gap-1.5 text-xs font-semibold text-primary mb-1.5">
                                        <Scale className="h-3.5 w-3.5 text-blue-500" />
                                        법령·지침 근거 #{idx + 1}
                                      </div>
                                      <p className="text-xs leading-relaxed text-muted-foreground whitespace-pre-wrap">{cite}</p>
                                    </div>
                                  ))}
                                </CardContent>
                              </Card>
                            ))
                        )}
                      </TabsContent>
                    </div>
                  </ScrollArea>
                </Tabs>
              </div>

              {/* Floating Glassmorphic Sticky Bottom Action Bar */}
              {summary && (
                <div className="absolute bottom-0 left-0 w-full border-t border-border/80 bg-background/80 backdrop-blur-md px-6 py-4 flex items-center justify-between shadow-2xl z-20 transition-all">
                  <div className="hidden lg:flex flex-col">
                    <span className="text-[11px] font-semibold text-muted-foreground">현재 프로세스 검토 결정</span>
                    <span className="text-xs text-foreground font-bold">
                      {suggestions.filter(s => s.status !== "pending").length} / {suggestions.length} 개 조서 피드백 완료
                    </span>
                  </div>

                  <div className="flex items-center gap-3 w-full lg:w-auto justify-end">
                    {/* Regenerate Trigger Button */}
                    {summary.status === "hitl_waiting" && (
                      <Button
                        variant="outline"
                        className={cn(
                          "text-xs px-4 h-9 font-semibold transition-all shadow-sm flex items-center gap-1.5 border-blue-200 dark:border-blue-900/50 hover:bg-blue-50/50 dark:hover:bg-blue-950/20 text-blue-700 dark:text-blue-400"
                        )}
                        disabled={!hasAppliedDecisions || busy !== null}
                        onClick={handleResume}
                      >
                        {busy === "resume" ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Sparkles className="h-3.5 w-3.5" />
                        )}
                        의견 반영 및 재생성
                      </Button>
                    )}

                    {/* Finalize Changes & Merge Button */}
                    {summary.status === "hitl_waiting" && (
                      <Button
                        className={cn(
                          "text-xs px-4 h-9 font-semibold transition-all shadow-sm flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-700 text-white"
                        )}
                        disabled={acceptedSuggestions.length === 0 || busy !== null}
                        onClick={handleApply}
                      >
                        {busy === "apply" ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Send className="h-3.5 w-3.5" />
                        )}
                        수정 계약서 컴파일하기
                      </Button>
                    )}

                    {/* Download Link Button */}
                    {summary.download_url && (
                      <Button
                        asChild
                        className="text-xs px-4 h-9 font-bold bg-gradient-to-r from-emerald-600 to-teal-500 hover:from-emerald-700 hover:to-teal-600 text-white shadow-md hover:shadow-lg hover:-translate-y-0.5 transition-all"
                      >
                        <a href={absoluteApiUrl(summary.download_url)}>
                          <Download className="mr-1.5 h-4 w-4" />
                          수정된 계약서 다운로드 (.docx)
                        </a>
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </SidebarProvider>
  );
}

// Interactive Issue Suggestion Card component
interface SuggestionCardProps {
  item: DocumentReviewSuggestion;
  busy: string | null;
  commentText: string;
  isExpanded: boolean;
  onSetComment: (text: string) => void;
  onToggleExpand: () => void;
  onDecision: (id: string, action: "accept" | "reject" | "feedback") => Promise<void>;
  onCopy: (text: string) => void;
}

function SuggestionCard({
  item,
  busy,
  commentText,
  isExpanded,
  onSetComment,
  onToggleExpand,
  onDecision,
  onCopy,
}: SuggestionCardProps) {
  const currentComment = decisionComment(item);
  const risk = item.risk_level && item.risk_level in riskConfig ? item.risk_level : "low";
  const config = riskConfig[risk];

  const statusLabel = {
    pending: "검토 대기",
    accepted: "수정안 수락됨",
    rejected: "수정 안 함",
    feedback: "수정 보완 요청",
  }[item.status];

  const isCardBusy = busy?.endsWith(item.finding_id);

  return (
    <div
      className={cn(
        "rounded-xl border transition-all duration-200 shadow-sm relative overflow-hidden hover:shadow-md",
        config.borderClass,
        config.bgClass,
        item.status === "accepted" && "ring-1 ring-emerald-500/20 bg-emerald-500/[0.02]",
        item.status === "rejected" && "ring-1 ring-rose-500/20 bg-rose-500/[0.02]",
        item.status === "feedback" && "ring-1 ring-blue-500/20 bg-blue-500/[0.02]"
      )}
    >
      <div className="p-4 space-y-3">
        {/* Header line */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full border-none", config.badgeClass)}>
              {config.label}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "text-[9px] font-bold px-2 py-0.5 rounded-full border bg-background/60",
                item.status === "accepted" && "border-emerald-500 text-emerald-600 dark:text-emerald-400",
                item.status === "rejected" && "border-rose-500 text-rose-600 dark:text-rose-400",
                item.status === "feedback" && "border-blue-500 text-blue-600 dark:text-blue-400",
                item.status === "pending" && "border-muted-foreground/30 text-muted-foreground"
              )}
            >
              {statusLabel}
            </Badge>
          </div>
          
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-foreground rounded-full"
            onClick={() => onCopy(`${item.title}\n\n감지조항: ${item.selected_text}\n\n수정의견: ${item.guidance}`)}
            title="클립보드 복사"
          >
            <Copy className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Title */}
        <h4 className="text-sm font-bold text-foreground leading-snug tracking-tight">
          {item.title || item.finding_id}
        </h4>

        {/* Selected clause blockquote */}
        {item.selected_text && (
          <div className="rounded-lg bg-muted/40 dark:bg-muted/10 border-l-[3px] border-primary/40 px-3 py-2 text-xs italic text-muted-foreground leading-relaxed">
            "{item.selected_text}"
          </div>
        )}

        {/* Explanation guidance */}
        {item.guidance && (
          <p className="text-xs leading-relaxed text-foreground/90 whitespace-pre-wrap">
            {item.guidance}
          </p>
        )}

        {/* Proposed edit diff */}
        {item.diff && (
          <div className="rounded-lg border border-border/40 bg-zinc-950 p-2.5 font-mono text-[10px] text-zinc-100 overflow-auto max-h-48 leading-relaxed shadow-inner">
            <div className="text-[9px] text-zinc-400 mb-1 border-b border-zinc-800 pb-1 font-sans flex items-center justify-between">
              <span>수정 조항 미리보기(DIFF)</span>
              <Badge variant="secondary" className="bg-zinc-800 text-zinc-300 text-[9px] hover:bg-zinc-800">코드 검증</Badge>
            </div>
            <pre className="whitespace-pre">{item.diff}</pre>
          </div>
        )}

        {/* Saved feedback info */}
        {currentComment && (
          <div className="rounded-lg border border-blue-100 dark:border-blue-900/30 bg-blue-500/[0.04] px-3 py-2.5 text-xs text-blue-700 dark:text-blue-300 leading-relaxed flex items-start gap-1.5">
            <MessageSquare className="h-4 w-4 shrink-0 text-blue-500 mt-0.5" />
            <div>
              <span className="font-bold">기존 전달 의견:</span> {currentComment}
            </div>
          </div>
        )}

        {/* Action Controls */}
        <div className="pt-2 border-t border-border/40 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {/* Accept Button */}
            {item.proposed_edit && (
              <Button
                size="sm"
                variant={item.status === "accepted" ? "default" : "outline"}
                className={cn(
                  "text-[11px] h-7 px-3 font-semibold",
                  item.status === "accepted"
                    ? "bg-emerald-600 hover:bg-emerald-700 text-white border-none"
                    : "border-emerald-200 dark:border-emerald-900/50 hover:bg-emerald-50/50 dark:hover:bg-emerald-950/20 text-emerald-700 dark:text-emerald-400"
                )}
                disabled={isCardBusy}
                onClick={() => onDecision(item.finding_id, "accept")}
              >
                {busy === `accept:${item.finding_id}` ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Check className="h-3 w-3 mr-1" />
                )}
                수락
              </Button>
            )}

            {/* Reject Button */}
            <Button
              size="sm"
              variant={item.status === "rejected" ? "destructive" : "outline"}
              className={cn(
                "text-[11px] h-7 px-3 font-semibold",
                item.status === "rejected"
                  ? "bg-rose-600 hover:bg-rose-700 text-white border-none"
                  : "border-rose-200 dark:border-rose-900/50 hover:bg-rose-50/50 dark:hover:bg-rose-950/20 text-rose-700 dark:text-rose-400"
              )}
              disabled={isCardBusy}
              onClick={() => onDecision(item.finding_id, "reject")}
            >
              {busy === `reject:${item.finding_id}` ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
              ) : (
                <X className="h-3 w-3 mr-1" />
              )}
              수정 안 함
            </Button>
          </div>

          {/* Feedback Area toggle */}
          <Button
            size="sm"
            variant={item.status === "feedback" ? "default" : "ghost"}
            className={cn(
              "text-[11px] h-7 px-3 font-semibold border border-transparent",
              item.status === "feedback"
                ? "bg-blue-600 hover:bg-blue-700 text-white"
                : "text-blue-600 dark:text-blue-400 hover:bg-blue-500/10"
            )}
            onClick={onToggleExpand}
          >
            <MessageSquare className="h-3.5 w-3.5 mr-1" />
            보완 의견 피드백
          </Button>
        </div>

        {/* Collapsible Feedback Comment Box */}
        {isExpanded && (
          <div className="pt-2.5 border-t border-border/40 space-y-2.5 animate-in fade-in slide-in-from-top-1 duration-150">
            <Textarea
              className="min-h-[72px] text-xs resize-none bg-background focus-visible:ring-blue-500"
              placeholder="LLM에 다시 작성을 요청할 세부 의견을 자세하게 입력해주세요. (예: 손해배상 배율을 200%에서 100%로 완화할 것)"
              value={commentText}
              onChange={(e) => onSetComment(e.target.value)}
            />
            <div className="flex justify-end">
              <Button
                size="sm"
                className="text-[11px] h-7 bg-blue-600 hover:bg-blue-700 text-white font-bold"
                disabled={!commentText.trim() || isCardBusy}
                onClick={() => onDecision(item.finding_id, "feedback")}
              >
                {busy === `feedback:${item.finding_id}` ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Sparkles className="h-3 w-3 mr-1" />
                )}
                피드백 의견 제출
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Helpers
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

function isActivelyProcessing(status: DocumentReviewStatus): boolean {
  return status === "queued" || status === "running" || status === "applying";
}

function decisionComment(item: DocumentReviewSuggestion): string {
  const decision = item.payload.decision;
  if (!decision || typeof decision !== "object" || !("comment" in decision)) return "";
  const comment = (decision as { comment?: unknown }).comment;
  return typeof comment === "string" ? comment : "";
}
