"use client";

import { useMemo, useRef, useState, useCallback } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronRight,
  Clock,
  Copy,
  Download,
  ExternalLink,
  FileText,
  MessageSquare,
  RefreshCw,
  Scale,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

type RiskLevel = "crit" | "high" | "mid" | "low";
type ReviewStatus = "safe" | "attention" | "high-risk";
type SuggestionStatus = "pending" | "accepted" | "rejected" | "feedback";
type ReferenceType = "precedent" | "interpretation" | "case" | "commentary";

interface ContractClause {
  id: string;
  text: string;
  riskLevel: RiskLevel | null;
  issueId?: string;
}

interface LawReference {
  lawName: string;
  article: string;
  snippet: string;
}

interface SupportingDocument {
  title: string;
  type: ReferenceType;
  excerpt: string;
}

interface ReviewSuggestion {
  id: string;
  title: string;
  riskLevel: RiskLevel;
  clauseId: string;
  selectedText: string;
  guidance: string;
  proposedEdit: string;
  lawReferences: LawReference[];
  supportingDocuments: SupportingDocument[];
}

const mockClauses: ContractClause[] = [
  {
    id: "c1",
    text: '제1조 (목적) 본 계약은 갑(이하 "원사업자")과 을(이하 "수급사업자") 간의 소프트웨어 개발 용역에 관한 기본적인 사항을 정함을 목적으로 한다.',
    riskLevel: null,
  },
  {
    id: "c2",
    text: "제2조 (계약기간) 본 계약의 기간은 2024년 1월 1일부터 2024년 12월 31일까지로 한다. 단, 갑의 사정에 따라 계약기간을 일방적으로 변경할 수 있다.",
    riskLevel: "high",
    issueId: "i1",
  },
  {
    id: "c3",
    text: "제3조 (대금) 갑은 을에게 총 계약금액 5억원을 지급한다. 대금 지급 시기는 갑의 내부 결재 완료 후 지급하며, 구체적인 지급일은 별도로 정하지 아니한다.",
    riskLevel: "high",
    issueId: "i2",
  },
  {
    id: "c4",
    text: "제4조 (납품) 을은 갑이 지정한 일시 및 장소에 목적물을 납품하여야 한다. 납품 후 갑의 검수 기간은 별도로 정하지 아니하며, 갑이 이의를 제기하지 않는 한 검수에 합격한 것으로 본다.",
    riskLevel: "mid",
    issueId: "i3",
  },
  {
    id: "c5",
    text: "제5조 (지식재산권) 본 계약에 의하여 을이 개발한 소프트웨어의 모든 지식재산권은 갑에게 귀속된다. 을은 개발 과정에서 발생한 모든 산출물에 대해 어떠한 권리도 주장할 수 없다.",
    riskLevel: "mid",
    issueId: "i4",
  },
  {
    id: "c6",
    text: "제6조 (비밀유지) 을은 본 계약과 관련하여 알게 된 갑의 영업비밀을 계약 종료 후에도 무기한 보호하여야 한다.",
    riskLevel: "low",
    issueId: "i5",
  },
  {
    id: "c7",
    text: "제7조 (손해배상) 을의 귀책사유로 갑에게 손해가 발생한 경우, 을은 갑에게 계약금액의 200%에 해당하는 손해배상금을 지급하여야 한다.",
    riskLevel: "crit",
    issueId: "i6",
  },
  {
    id: "c8",
    text: "제8조 (계약해지) 갑은 언제든지 본 계약을 해지할 수 있으며, 이 경우 기 지급된 대금의 반환을 요청할 수 있다. 을의 해지 요청은 갑의 서면 승인을 요한다.",
    riskLevel: "high",
    issueId: "i7",
  },
  {
    id: "c9",
    text: "제9조 (분쟁해결) 본 계약에 관한 분쟁은 갑의 본사 소재지를 관할하는 법원을 전속관할로 한다.",
    riskLevel: "low",
    issueId: "i8",
  },
];

const mockSuggestions: ReviewSuggestion[] = [
  {
    id: "i1",
    title: "계약기간 일방 변경 조항",
    riskLevel: "high",
    clauseId: "c2",
    selectedText: "갑의 사정에 따라 계약기간을 일방적으로 변경할 수 있다.",
    guidance:
      "원사업자가 일방적으로 계약기간을 변경할 수 있는 조항은 수급사업자의 예측 가능성을 해치고 불공정 계약 변경으로 해석될 수 있습니다.",
    proposedEdit: "계약기간의 변경은 갑과 을이 서면으로 합의한 경우에 한하며, 변경 시 30일 이전에 통보하여야 한다.",
    lawReferences: [
      {
        lawName: "하도급법",
        article: "제8조",
        snippet: "원사업자는 수급사업자의 책임으로 돌릴 사유가 없는 경우 위탁 내용을 임의로 변경하여서는 아니 된다.",
      },
    ],
    supportingDocuments: [
      {
        title: "하도급 거래 시 부당한 계약변경 사례집",
        type: "case",
        excerpt: "일방적 계약기간 변경은 부당한 위탁취소 또는 변경 사례로 검토될 수 있다.",
      },
    ],
  },
  {
    id: "i2",
    title: "대금 지급 시기 미정",
    riskLevel: "high",
    clauseId: "c3",
    selectedText: "대금 지급 시기는 갑의 내부 결재 완료 후 지급하며, 구체적인 지급일은 별도로 정하지 아니한다.",
    guidance:
      "지급 시점을 내부 결재에만 연결하면 지급기일이 사실상 무기한 지연될 수 있어 분쟁 가능성이 큽니다.",
    proposedEdit: "갑은 을의 납품 및 검수 완료일로부터 60일 이내에 대금을 지급하여야 한다.",
    lawReferences: [
      {
        lawName: "하도급법",
        article: "제13조",
        snippet: "목적물 수령일부터 60일 이내의 가능한 짧은 기간으로 정한 지급기일까지 하도급대금을 지급하여야 한다.",
      },
    ],
    supportingDocuments: [
      {
        title: "공정거래위원회 하도급대금 지급 관련 해석례",
        type: "interpretation",
        excerpt: "지급기일을 정하지 아니한 경우 목적물 수령일 기준 지급기한이 문제된다.",
      },
    ],
  },
  {
    id: "i3",
    title: "검수 기간 미명시",
    riskLevel: "mid",
    clauseId: "c4",
    selectedText: "갑의 검수 기간은 별도로 정하지 아니하며",
    guidance:
      "검수 기준과 기간이 없으면 검수 지연과 대금 지급 지연이 함께 발생할 수 있습니다.",
    proposedEdit: "갑은 납품일로부터 10영업일 이내에 검수를 완료하여야 하며, 기간 내 이의가 없으면 검수에 합격한 것으로 본다.",
    lawReferences: [
      {
        lawName: "하도급법",
        article: "제13조 제2항",
        snippet: "원사업자는 검사의 기준 및 방법, 검사에 필요한 기간을 정하여야 한다.",
      },
    ],
    supportingDocuments: [
      {
        title: "하도급 표준계약서 가이드라인",
        type: "commentary",
        excerpt: "검수 기간은 통상 10~15영업일로 명시할 것을 권고한다.",
      },
    ],
  },
  {
    id: "i6",
    title: "과도한 손해배상 예정",
    riskLevel: "crit",
    clauseId: "c7",
    selectedText: "계약금액의 200%에 해당하는 손해배상금을 지급하여야 한다.",
    guidance:
      "계약금액을 초과하는 고정 손해배상 예정액은 과도한 부담으로 보일 수 있고 법원에서 감액될 가능성이 있습니다.",
    proposedEdit: "손해배상액은 실제 발생한 통상손해를 기준으로 하며, 손해배상 예정액은 계약금액을 초과하지 아니한다.",
    lawReferences: [
      {
        lawName: "민법",
        article: "제398조",
        snippet: "손해배상의 예정액이 부당히 과다한 경우에는 법원은 적당히 감액할 수 있다.",
      },
    ],
    supportingDocuments: [
      {
        title: "과다 위약금 조항 관련 판례 경향",
        type: "precedent",
        excerpt: "예정 손해배상액이 계약 목적과 실제 손해에 비해 큰 경우 감액 판단이 이루어진다.",
      },
    ],
  },
  {
    id: "i8",
    title: "일방적 관할법원 지정",
    riskLevel: "low",
    clauseId: "c9",
    selectedText: "갑의 본사 소재지를 관할하는 법원을 전속관할로 한다.",
    guidance:
      "전속관할 합의는 가능하지만 한쪽 당사자에게만 편리한 관할을 고정하면 협상상 불리한 조항으로 인식될 수 있습니다.",
    proposedEdit: "분쟁 발생 시 민사소송법에 따른 관할법원에서 해결한다.",
    lawReferences: [
      {
        lawName: "민사소송법",
        article: "제29조",
        snippet: "합의에 의한 관할은 일정한 법률관계에 기한 소에 관하여 서면으로 정할 수 있다.",
      },
    ],
    supportingDocuments: [],
  },
];

const riskConfig: Record<
  RiskLevel,
  { label: string; bgClass: string; textClass: string; borderClass: string; badgeClass: string; clauseClass: string }
> = {
  crit: {
    label: "치명적 위험",
    bgClass: "bg-red-500/5 hover:bg-red-500/10 dark:bg-red-950/20 dark:hover:bg-red-950/30",
    textClass: "text-red-700 dark:text-red-400",
    borderClass: "border-red-200 dark:border-red-900/50",
    badgeClass: "bg-red-600 text-white dark:bg-red-900 dark:text-red-200",
    clauseClass: "border-l-red-500 bg-red-50/80 dark:bg-red-950/20",
  },
  high: {
    label: "고위험",
    bgClass: "bg-rose-500/5 hover:bg-rose-500/10 dark:bg-rose-950/20 dark:hover:bg-rose-950/30",
    textClass: "text-rose-700 dark:text-rose-400",
    borderClass: "border-rose-200 dark:border-rose-900/50",
    badgeClass: "bg-rose-600 text-white dark:bg-rose-900 dark:text-rose-200",
    clauseClass: "border-l-rose-500 bg-rose-50/80 dark:bg-rose-950/20",
  },
  mid: {
    label: "주의",
    bgClass: "bg-amber-500/5 hover:bg-amber-500/10 dark:bg-amber-950/20 dark:hover:bg-amber-950/30",
    textClass: "text-amber-700 dark:text-amber-400",
    borderClass: "border-amber-200 dark:border-amber-900/50",
    badgeClass: "bg-amber-500 text-white dark:bg-amber-800 dark:text-amber-200",
    clauseClass: "border-l-amber-500 bg-amber-50/80 dark:bg-amber-950/20",
  },
  low: {
    label: "참고",
    bgClass: "bg-emerald-500/5 hover:bg-emerald-500/10 dark:bg-emerald-950/20 dark:hover:bg-emerald-950/30",
    textClass: "text-emerald-700 dark:text-emerald-400",
    borderClass: "border-emerald-200 dark:border-emerald-900/50",
    badgeClass: "bg-emerald-600 text-white dark:bg-emerald-900 dark:text-emerald-200",
    clauseClass: "border-l-emerald-500 bg-emerald-50/80 dark:bg-emerald-950/20",
  },
};

const statusConfig: Record<ReviewStatus, { label: string; icon: typeof ShieldCheck; className: string }> = {
  safe: { label: "안전함", icon: ShieldCheck, className: "text-emerald-600 dark:text-emerald-400" },
  attention: { label: "검토 권장", icon: AlertTriangle, className: "text-amber-600 dark:text-amber-400" },
  "high-risk": { label: "위험 조항 감지", icon: ShieldAlert, className: "text-rose-600 dark:text-rose-400" },
};

const refTypeLabels: Record<ReferenceType, string> = {
  precedent: "판례",
  interpretation: "해석례",
  case: "사례",
  commentary: "해설",
};

export default function ContractReviewResult() {
  const [activeTab, setActiveTab] = useState("all");
  const [activeIssueId, setActiveIssueId] = useState<string | null>(mockSuggestions[0]?.id ?? null);
  const [decisions, setDecisions] = useState<Record<string, SuggestionStatus>>({});
  const [commentByIssue, setCommentByIssue] = useState<Record<string, string>>({});
  const [expandedFeedbackId, setExpandedFeedbackId] = useState<string | null>(null);
  const clauseRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const issueRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const riskCounts = useMemo(() => {
    return mockSuggestions.reduce(
      (counts, item) => ({ ...counts, [item.riskLevel]: counts[item.riskLevel] + 1 }),
      { crit: 0, high: 0, mid: 0, low: 0 } satisfies Record<RiskLevel, number>
    );
  }, []);

  const visibleSuggestions = useMemo(() => {
    if (activeTab === "high") {
      return mockSuggestions.filter((item) => item.riskLevel === "crit" || item.riskLevel === "high");
    }
    return mockSuggestions;
  }, [activeTab]);

  const decidedCount = Object.keys(decisions).length;
  const reviewStatus: ReviewStatus = riskCounts.crit + riskCounts.high > 0 ? "high-risk" : riskCounts.mid > 0 ? "attention" : "safe";
  const StatusIcon = statusConfig[reviewStatus].icon;

  const setClauseRef = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) clauseRefs.current.set(id, el);
  }, []);

  const setIssueRef = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) issueRefs.current.set(id, el);
  }, []);

  const scrollToClause = useCallback((clauseId: string) => {
    const el = clauseRefs.current.get(clauseId);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("ring-2", "ring-primary");
    window.setTimeout(() => el.classList.remove("ring-2", "ring-primary"), 1600);
  }, []);

  const scrollToIssue = useCallback((issueId: string) => {
    setActiveIssueId(issueId);
    const el = issueRefs.current.get(issueId);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  const copyText = (text: string) => {
    void navigator.clipboard.writeText(text);
    toast.success("클립보드에 복사되었습니다.");
  };

  const decide = (id: string, status: SuggestionStatus) => {
    if (status === "feedback" && !commentByIssue[id]?.trim()) {
      toast.error("보완 의견을 입력해주세요.");
      return;
    }
    setDecisions((prev) => ({ ...prev, [id]: status }));
    toast.success(
      status === "accepted"
        ? "수정 의견을 수락했습니다."
        : status === "rejected"
          ? "수정 의견을 제외했습니다."
          : "보완 의견을 기록했습니다."
    );
  };

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full bg-background font-sans">
        <AppSidebar />
        <div className="flex flex-1 flex-col overflow-hidden">
          <header className="flex h-12 items-center justify-between border-b border-border bg-card px-4">
            <div className="flex items-center gap-2">
              <SidebarTrigger />
              <Separator orientation="vertical" className="mx-1 h-4" />
              <span className="max-w-[220px] truncate text-sm font-medium sm:max-w-xs">
                소프트웨어 개발 용역 하도급 계약서
              </span>
            </div>
            <Badge variant="outline" className="text-xs">
              검토 결과
            </Badge>
          </header>

          <div className="z-10 border-b border-border bg-card/60 px-6 py-3 backdrop-blur-sm">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className={cn("flex items-center gap-2 text-base font-semibold", statusConfig[reviewStatus].className)}>
                  <StatusIcon className="h-5 w-5" />
                  <span>{statusConfig[reviewStatus].label}</span>
                </div>
                <Separator orientation="vertical" className="h-5" />
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="secondary" className="font-normal text-[11px]">
                    하도급 계약서
                  </Badge>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    2024. 1. 16. 14:30
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Badge className="border-red-200 bg-red-500/10 text-[11px] font-semibold text-red-700 hover:bg-red-500/10 dark:border-red-900/50 dark:text-red-400">
                  고위험/치명적 {riskCounts.crit + riskCounts.high}
                </Badge>
                <Badge className="border-amber-200 bg-amber-500/10 text-[11px] font-semibold text-amber-700 hover:bg-amber-500/10 dark:border-amber-900/50 dark:text-amber-400">
                  주의 {riskCounts.mid}
                </Badge>
                <Badge className="border-emerald-200 bg-emerald-500/10 text-[11px] font-semibold text-emerald-700 hover:bg-emerald-500/10 dark:border-emerald-900/50 dark:text-emerald-400">
                  참고 {riskCounts.low}
                </Badge>
              </div>
            </div>
          </div>

          <div className="relative flex flex-1 flex-col overflow-hidden pb-[84px] md:flex-row">
            <div className="flex min-h-0 flex-1 flex-col border-r border-border bg-muted/10">
              <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2">
                <span className="flex items-center gap-1.5 text-xs font-semibold">
                  <FileText className="h-3.5 w-3.5 text-primary" />
                  계약서 원문 검토
                </span>
                <div className="hidden items-center gap-2 text-[11px] text-muted-foreground sm:flex">
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm bg-red-500/50" /> 치명적
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm bg-rose-500/40" /> 고위험
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-500/40" /> 주의
                  </span>
                </div>
              </div>

              <ScrollArea className="flex-1">
                <div className="mx-auto max-w-3xl space-y-2 p-6">
                  <h2 className="mb-6 text-center text-lg font-bold text-foreground">
                    소프트웨어 개발 용역 하도급 계약서
                  </h2>
                  {mockClauses.map((clause) => (
                    <div
                      key={clause.id}
                      ref={(el) => setClauseRef(clause.id, el)}
                      className={cn(
                        "rounded-md border-l-4 border-l-transparent px-4 py-3 text-sm leading-relaxed text-foreground transition-all",
                        clause.riskLevel && riskConfig[clause.riskLevel].clauseClass,
                        clause.issueId && "cursor-pointer hover:opacity-80",
                        activeIssueId && clause.issueId === activeIssueId && "ring-2 ring-primary"
                      )}
                      onClick={() => clause.issueId && scrollToIssue(clause.issueId)}
                    >
                      {clause.text}
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </div>

            <div className="flex min-h-0 w-full shrink-0 flex-col border-t border-border bg-card md:w-[480px] md:border-t-0 lg:w-[540px]">
              <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col">
                <div className="border-b border-border bg-card/40 px-4 pt-2">
                  <TabsList className="grid w-full grid-cols-3 rounded-lg border border-border/20 bg-muted/40 p-0.5">
                    <TabsTrigger value="all" className="rounded-md py-1.5 text-xs font-medium">
                      전체 의견 ({mockSuggestions.length})
                    </TabsTrigger>
                    <TabsTrigger value="high" className="rounded-md py-1.5 text-xs font-medium">
                      핵심 위험 ({riskCounts.crit + riskCounts.high})
                    </TabsTrigger>
                    <TabsTrigger value="references" className="rounded-md py-1.5 text-xs font-medium">
                      법률 근거
                    </TabsTrigger>
                  </TabsList>
                </div>

                <ScrollArea className="min-h-0 flex-1">
                  <div className="space-y-4 p-4">
                    <TabsContent value="all" className="m-0 space-y-3 outline-none">
                      {visibleSuggestions.map((item) => (
                        <SuggestionCard
                          key={item.id}
                          item={item}
                          status={decisions[item.id] ?? "pending"}
                          commentText={commentByIssue[item.id] ?? ""}
                          isActive={activeIssueId === item.id}
                          isExpanded={expandedFeedbackId === item.id}
                          refCallback={(el) => setIssueRef(item.id, el)}
                          onSetComment={(text) => setCommentByIssue((prev) => ({ ...prev, [item.id]: text }))}
                          onToggleExpand={() => setExpandedFeedbackId(expandedFeedbackId === item.id ? null : item.id)}
                          onDecision={decide}
                          onCopy={copyText}
                          onScrollToClause={scrollToClause}
                        />
                      ))}
                    </TabsContent>

                    <TabsContent value="high" className="m-0 space-y-3 outline-none">
                      {visibleSuggestions.map((item) => (
                        <SuggestionCard
                          key={item.id}
                          item={item}
                          status={decisions[item.id] ?? "pending"}
                          commentText={commentByIssue[item.id] ?? ""}
                          isActive={activeIssueId === item.id}
                          isExpanded={expandedFeedbackId === item.id}
                          refCallback={(el) => setIssueRef(item.id, el)}
                          onSetComment={(text) => setCommentByIssue((prev) => ({ ...prev, [item.id]: text }))}
                          onToggleExpand={() => setExpandedFeedbackId(expandedFeedbackId === item.id ? null : item.id)}
                          onDecision={decide}
                          onCopy={copyText}
                          onScrollToClause={scrollToClause}
                        />
                      ))}
                    </TabsContent>

                    <TabsContent value="references" className="m-0 space-y-3 outline-none">
                      {mockSuggestions
                        .filter((item) => item.lawReferences.length > 0 || item.supportingDocuments.length > 0)
                        .map((item) => (
                          <div key={item.id} className="rounded-lg border border-border bg-card p-4 text-sm shadow-sm">
                            <div className="mb-3 flex items-center gap-2">
                              <Badge className={cn("px-2 py-0.5 text-[10px] font-semibold", riskConfig[item.riskLevel].badgeClass)}>
                                {riskConfig[item.riskLevel].label}
                              </Badge>
                              <span className="truncate font-semibold text-foreground">{item.title}</span>
                            </div>
                            <Separator className="mb-3" />
                            <div className="space-y-2">
                              {item.lawReferences.map((ref, idx) => (
                                <div key={`${item.id}-law-${idx}`} className="rounded-lg border border-border/80 bg-muted/40 p-3">
                                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-primary">
                                    <Scale className="h-3.5 w-3.5 text-blue-500" />
                                    {ref.lawName} {ref.article}
                                  </div>
                                  <p className="text-xs leading-relaxed text-muted-foreground">{ref.snippet}</p>
                                </div>
                              ))}
                              {item.supportingDocuments.map((doc, idx) => (
                                <div key={`${item.id}-doc-${idx}`} className="rounded-lg border border-border/80 p-3">
                                  <div className="mb-1 flex items-center gap-2 text-xs font-medium text-foreground">
                                    <BookOpen className="h-3.5 w-3.5 text-muted-foreground" />
                                    <span>{doc.title}</span>
                                    <Badge variant="secondary" className="text-[10px]">
                                      {refTypeLabels[doc.type]}
                                    </Badge>
                                  </div>
                                  <p className="text-xs leading-relaxed text-muted-foreground">{doc.excerpt}</p>
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                    </TabsContent>
                  </div>
                </ScrollArea>
              </Tabs>
            </div>

            <div className="absolute bottom-0 left-0 z-20 flex w-full items-center justify-between border-t border-border/80 bg-background/80 px-6 py-4 shadow-2xl backdrop-blur-md">
              <div className="hidden flex-col lg:flex">
                <span className="text-[11px] font-semibold text-muted-foreground">현재 검토 결정</span>
                <span className="text-xs font-bold text-foreground">
                  {decidedCount} / {mockSuggestions.length} 개 조항 피드백 완료
                </span>
              </div>

              <div className="flex w-full items-center justify-end gap-3 lg:w-auto">
                <Button
                  variant="outline"
                  className="flex h-9 items-center gap-1.5 border-blue-200 px-4 text-xs font-semibold text-blue-700 shadow-sm hover:bg-blue-50/50 dark:border-blue-900/50 dark:text-blue-400 dark:hover:bg-blue-950/20"
                  onClick={() => toast.info("재검토 흐름은 정리 대상이라 비활성화되어 있습니다.")}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  의견 반영 및 재생성
                </Button>
                <Button
                  className="flex h-9 items-center gap-1.5 bg-indigo-600 px-4 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700"
                  onClick={() => toast.info("문서 컴파일 기능은 현재 연결되어 있지 않습니다.")}
                >
                  <Send className="h-3.5 w-3.5" />
                  수정 계약서 컴파일하기
                </Button>
                <Button
                  variant="outline"
                  className="hidden h-9 px-4 text-xs font-semibold sm:inline-flex"
                  onClick={() => toast.info("다운로드할 수정 문서가 없습니다.")}
                >
                  <Download className="mr-1.5 h-4 w-4" />
                  다운로드
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
}

interface SuggestionCardProps {
  item: ReviewSuggestion;
  status: SuggestionStatus;
  commentText: string;
  isActive: boolean;
  isExpanded: boolean;
  refCallback: (el: HTMLDivElement | null) => void;
  onSetComment: (text: string) => void;
  onToggleExpand: () => void;
  onDecision: (id: string, status: SuggestionStatus) => void;
  onCopy: (text: string) => void;
  onScrollToClause: (clauseId: string) => void;
}

function SuggestionCard({
  item,
  status,
  commentText,
  isActive,
  isExpanded,
  refCallback,
  onSetComment,
  onToggleExpand,
  onDecision,
  onCopy,
  onScrollToClause,
}: SuggestionCardProps) {
  const config = riskConfig[item.riskLevel];
  const statusLabel: Record<SuggestionStatus, string> = {
    pending: "검토 대기",
    accepted: "수정안 수락됨",
    rejected: "수정 안 함",
    feedback: "수정 보완 요청",
  };

  return (
    <div
      ref={refCallback}
      className={cn(
        "relative overflow-hidden rounded-xl border shadow-sm transition-all duration-200 hover:shadow-md",
        config.borderClass,
        config.bgClass,
        isActive && "ring-1 ring-primary/30",
        status === "accepted" && "ring-1 ring-emerald-500/20 bg-emerald-500/[0.02]",
        status === "rejected" && "ring-1 ring-rose-500/20 bg-rose-500/[0.02]",
        status === "feedback" && "ring-1 ring-blue-500/20 bg-blue-500/[0.02]"
      )}
    >
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge className={cn("rounded-full border-none px-2 py-0.5 text-[10px] font-semibold", config.badgeClass)}>
              {config.label}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "rounded-full border bg-background/60 px-2 py-0.5 text-[9px] font-bold",
                status === "accepted" && "border-emerald-500 text-emerald-600 dark:text-emerald-400",
                status === "rejected" && "border-rose-500 text-rose-600 dark:text-rose-400",
                status === "feedback" && "border-blue-500 text-blue-600 dark:text-blue-400",
                status === "pending" && "border-muted-foreground/30 text-muted-foreground"
              )}
            >
              {statusLabel[status]}
            </Badge>
          </div>

          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 rounded-full text-muted-foreground hover:text-foreground"
            onClick={() => onCopy(`${item.title}\n\n감지조항: ${item.selectedText}\n\n수정의견: ${item.guidance}`)}
            title="클립보드 복사"
          >
            <Copy className="h-3.5 w-3.5" />
          </Button>
        </div>

        <h4 className="text-sm font-bold leading-snug tracking-tight text-foreground">{item.title}</h4>

        <div className="rounded-lg border-l-[3px] border-primary/40 bg-muted/40 px-3 py-2 text-xs italic leading-relaxed text-muted-foreground dark:bg-muted/10">
          &quot;{item.selectedText}&quot;
        </div>

        <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/90">{item.guidance}</p>

        <div className="rounded-lg border border-primary/20 bg-primary/5 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase text-primary">수정 제안</p>
          <p className="mt-1 text-xs leading-relaxed text-foreground">{item.proposedEdit}</p>
        </div>

        {item.lawReferences.length > 0 && (
          <div className="space-y-1.5">
            {item.lawReferences.map((ref, idx) => (
              <div key={idx} className="flex items-start gap-1.5 text-xs">
                <Scale className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                <span>
                  <span className="font-medium text-primary">
                    {ref.lawName} {ref.article}
                  </span>
                  <span className="text-muted-foreground"> - {ref.snippet.slice(0, 70)}...</span>
                </span>
              </div>
            ))}
          </div>
        )}

        {item.supportingDocuments.length > 0 && (
          <div className="space-y-1.5">
            {item.supportingDocuments.map((doc, idx) => (
              <div key={idx} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <ExternalLink className="h-3 w-3 shrink-0" />
                <span>{doc.title}</span>
                <Badge variant="secondary" className="text-[10px]">
                  {refTypeLabels[doc.type]}
                </Badge>
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/40 pt-2">
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant={status === "accepted" ? "default" : "outline"}
              className={cn(
                "h-7 px-3 text-[11px] font-semibold",
                status === "accepted"
                  ? "border-none bg-emerald-600 text-white hover:bg-emerald-700"
                  : "border-emerald-200 text-emerald-700 hover:bg-emerald-50/50 dark:border-emerald-900/50 dark:text-emerald-400 dark:hover:bg-emerald-950/20"
              )}
              onClick={() => onDecision(item.id, "accepted")}
            >
              <Check className="mr-1 h-3 w-3" />
              수락
            </Button>
            <Button
              size="sm"
              variant={status === "rejected" ? "destructive" : "outline"}
              className={cn(
                "h-7 px-3 text-[11px] font-semibold",
                status !== "rejected" &&
                  "border-rose-200 text-rose-700 hover:bg-rose-50/50 dark:border-rose-900/50 dark:text-rose-400 dark:hover:bg-rose-950/20"
              )}
              onClick={() => onDecision(item.id, "rejected")}
            >
              <X className="mr-1 h-3 w-3" />
              수정 안 함
            </Button>
          </div>

          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              className="h-7 px-3 text-[11px] font-semibold text-muted-foreground"
              onClick={() => onScrollToClause(item.clauseId)}
            >
              원문 보기
              <ChevronRight className="ml-0.5 h-3 w-3" />
            </Button>
            <Button
              size="sm"
              variant={status === "feedback" ? "default" : "ghost"}
              className={cn(
                "h-7 border border-transparent px-3 text-[11px] font-semibold",
                status === "feedback" ? "bg-blue-600 text-white hover:bg-blue-700" : "text-blue-600 hover:bg-blue-500/10 dark:text-blue-400"
              )}
              onClick={onToggleExpand}
            >
              <MessageSquare className="mr-1 h-3.5 w-3.5" />
              보완 의견
            </Button>
          </div>
        </div>

        {isExpanded && (
          <div className="animate-in fade-in slide-in-from-top-1 space-y-2.5 border-t border-border/40 pt-2.5 duration-150">
            <Textarea
              className="min-h-[72px] resize-none bg-background text-xs focus-visible:ring-blue-500"
              placeholder="보완 요청 내용을 입력하세요."
              value={commentText}
              onChange={(event) => onSetComment(event.target.value)}
            />
            <div className="flex justify-end">
              <Button
                size="sm"
                className="h-7 bg-blue-600 text-[11px] font-bold text-white hover:bg-blue-700"
                disabled={!commentText.trim()}
                onClick={() => onDecision(item.id, "feedback")}
              >
                <RefreshCw className="mr-1 h-3 w-3" />
                피드백 의견 저장
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
