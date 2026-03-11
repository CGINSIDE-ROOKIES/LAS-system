import { useState, useRef, useCallback } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
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
} from "lucide-react";
import { cn } from "@/lib/utils";

// Types
type RiskLevel = "high" | "medium" | "low";
type OverallStatus = "safe" | "attention" | "high-risk";
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

interface ReviewIssue {
  id: string;
  title: string;
  riskLevel: RiskLevel;
  clauseId: string;
  detectedClause: string;
  explanation: string;
  suggestedRevision: string;
  lawReferences: LawReference[];
  supportingDocuments: SupportingDocument[];
}

interface ReviewResult {
  overallStatus: OverallStatus;
  contractType: string;
  reviewTimestamp: Date;
  totalIssues: number;
  issues: ReviewIssue[];
}

// Mock data
const mockClauses: ContractClause[] = [
  { id: "c1", text: "제1조 (목적) 본 계약은 갑(이하 \"원사업자\")과 을(이하 \"수급사업자\") 간의 소프트웨어 개발 용역에 관한 기본적인 사항을 정함을 목적으로 한다.", riskLevel: null },
  { id: "c2", text: "제2조 (계약기간) 본 계약의 기간은 2024년 1월 1일부터 2024년 12월 31일까지로 한다. 단, 갑의 사정에 따라 계약기간을 일방적으로 변경할 수 있다.", riskLevel: "high", issueId: "i1" },
  { id: "c3", text: "제3조 (대금) 갑은 을에게 총 계약금액 5억원을 지급한다. 대금 지급 시기는 갑의 내부 결재 완료 후 지급하며, 구체적인 지급일은 별도로 정하지 아니한다.", riskLevel: "high", issueId: "i2" },
  { id: "c4", text: "제4조 (납품) 을은 갑이 지정한 일시 및 장소에 목적물을 납품하여야 한다. 납품 후 갑의 검수 기간은 별도로 정하지 아니하며, 갑이 이의를 제기하지 않는 한 검수에 합격한 것으로 본다.", riskLevel: "medium", issueId: "i3" },
  { id: "c5", text: "제5조 (지식재산권) 본 계약에 의하여 을이 개발한 소프트웨어의 모든 지식재산권은 갑에게 귀속된다. 을은 개발 과정에서 발생한 모든 산출물에 대해 어떠한 권리도 주장할 수 없다.", riskLevel: "medium", issueId: "i4" },
  { id: "c6", text: "제6조 (비밀유지) 을은 본 계약과 관련하여 알게 된 갑의 영업비밀을 계약 종료 후에도 무기한 보호하여야 한다.", riskLevel: "low", issueId: "i5" },
  { id: "c7", text: "제7조 (손해배상) 을의 귀책사유로 갑에게 손해가 발생한 경우, 을은 갑에게 계약금액의 200%에 해당하는 손해배상금을 지급하여야 한다.", riskLevel: "high", issueId: "i6" },
  { id: "c8", text: "제8조 (계약해지) 갑은 언제든지 본 계약을 해지할 수 있으며, 이 경우 기 지급된 대금의 반환을 요청할 수 있다. 을의 해지 요청은 갑의 서면 승인을 요한다.", riskLevel: "high", issueId: "i7" },
  { id: "c9", text: "제9조 (분쟁해결) 본 계약에 관한 분쟁은 갑의 본사 소재지를 관할하는 법원을 전속관할로 한다.", riskLevel: "low", issueId: "i8" },
  { id: "c10", text: "제10조 (기타) 본 계약에 명시되지 아니한 사항은 갑과 을이 상호 협의하여 결정한다. 단, 협의가 되지 않는 경우 갑의 결정에 따른다.", riskLevel: "medium", issueId: "i9" },
];

const mockReview: ReviewResult = {
  overallStatus: "high-risk",
  contractType: "하도급 계약서",
  reviewTimestamp: new Date("2024-01-16T14:30:00"),
  totalIssues: 9,
  issues: [
    {
      id: "i1",
      title: "계약기간 일방 변경 조항",
      riskLevel: "high",
      clauseId: "c2",
      detectedClause: "갑의 사정에 따라 계약기간을 일방적으로 변경할 수 있다.",
      explanation: "원사업자가 일방적으로 계약기간을 변경할 수 있는 조항은 하도급법 제8조(부당한 위탁취소 등의 금지)에 위반될 소지가 있습니다. 수급사업자의 동의 없이 계약 내용을 변경하는 것은 부당한 행위로 간주됩니다.",
      suggestedRevision: "계약기간의 변경은 갑과 을이 서면으로 합의한 경우에 한하며, 변경 시 30일 이전에 통보하여야 한다.",
      lawReferences: [
        { lawName: "하도급법", article: "제8조", snippet: "원사업자는 수급사업자에게 위탁한 후 수급사업자의 책임으로 돌릴 사유가 없는 경우에는 위탁을 임의로 취소하거나 변경하여서는 아니 된다." },
      ],
      supportingDocuments: [
        { title: "하도급 거래 시 부당한 계약변경 사례집", type: "case", excerpt: "일방적 계약기간 변경은 부당한 위탁취소에 해당..." },
      ],
    },
    {
      id: "i2",
      title: "대금 지급 시기 미정",
      riskLevel: "high",
      clauseId: "c3",
      detectedClause: "대금 지급 시기는 갑의 내부 결재 완료 후 지급하며, 구체적인 지급일은 별도로 정하지 아니한다.",
      explanation: "하도급법 제13조에 따르면, 원사업자는 목적물 수령일로부터 60일 이내에 대금을 지급해야 합니다. 지급 시기를 명시하지 않는 것은 지급지연의 소지가 있습니다.",
      suggestedRevision: "갑은 을의 납품 후 검수 완료일로부터 60일 이내에 대금을 지급하여야 한다.",
      lawReferences: [
        { lawName: "하도급법", article: "제13조", snippet: "원사업자가 수급사업자에게 목적물 등의 수령일부터 60일 이내의 가능한 짧은 기간으로 정한 지급기일까지 하도급대금을 지급하여야 한다." },
      ],
      supportingDocuments: [
        { title: "공정거래위원회 하도급대금 지급 관련 해석례", type: "interpretation", excerpt: "지급기일을 정하지 아니한 경우 수령일로부터 60일 적용..." },
      ],
    },
    {
      id: "i3",
      title: "검수 기간 미명시",
      riskLevel: "medium",
      clauseId: "c4",
      detectedClause: "갑의 검수 기간은 별도로 정하지 아니하며...",
      explanation: "검수 기간을 명시하지 않으면 원사업자가 검수를 무한정 지연할 수 있어 대금 지급이 지체될 수 있습니다.",
      suggestedRevision: "갑은 납품일로부터 10영업일 이내에 검수를 완료하여야 한다.",
      lawReferences: [
        { lawName: "하도급법", article: "제13조 제2항", snippet: "원사업자는 검사의 기준 및 방법, 검사에 필요한 기간을 정하여야 한다." },
      ],
      supportingDocuments: [
        { title: "하도급 표준계약서 가이드라인", type: "commentary", excerpt: "검수 기간은 통상 10~15영업일로 명시할 것을 권고..." },
      ],
    },
    {
      id: "i4",
      title: "지식재산권 전면 귀속 조항",
      riskLevel: "medium",
      clauseId: "c5",
      detectedClause: "을이 개발한 소프트웨어의 모든 지식재산권은 갑에게 귀속된다.",
      explanation: "수급사업자가 기존에 보유한 기술이나 범용 기술까지 원사업자에게 귀속되는 것은 부당할 수 있습니다.",
      suggestedRevision: "본 계약에 의하여 새롭게 개발된 기술에 한하여 갑에게 귀속되며, 을이 기존에 보유한 기술의 권리는 을에게 유지된다.",
      lawReferences: [
        { lawName: "하도급법", article: "제12조의3", snippet: "원사업자는 수급사업자의 기술자료를 본래의 사용 목적 외의 용도로 사용하여서는 아니 된다." },
      ],
      supportingDocuments: [
        { title: "SW 개발 하도급 지식재산권 분쟁 판례", type: "precedent", excerpt: "기존 보유 기술까지 포괄적으로 귀속시키는 조항은 무효..." },
      ],
    },
    {
      id: "i5",
      title: "무기한 비밀유지 의무",
      riskLevel: "low",
      clauseId: "c6",
      detectedClause: "을은 갑의 영업비밀을 계약 종료 후에도 무기한 보호하여야 한다.",
      explanation: "비밀유지 의무의 기간을 무기한으로 설정하는 것은 수급사업자에게 과도한 부담이 될 수 있습니다.",
      suggestedRevision: "비밀유지 의무는 계약 종료일로부터 3년간 유지된다.",
      lawReferences: [
        { lawName: "부정경쟁방지법", article: "제2조 제2호", snippet: "영업비밀이란 공공연히 알려져 있지 아니하고 독립된 경제적 가치를 가지는 것으로서..." },
      ],
      supportingDocuments: [],
    },
    {
      id: "i6",
      title: "과도한 손해배상 조항",
      riskLevel: "high",
      clauseId: "c7",
      detectedClause: "을은 갑에게 계약금액의 200%에 해당하는 손해배상금을 지급하여야 한다.",
      explanation: "계약금액의 200%에 해당하는 손해배상 예정액은 민법 제398조에 따라 부당하게 과다한 경우 법원에 의해 감액될 수 있으며, 하도급법 위반 소지가 있습니다.",
      suggestedRevision: "손해배상액은 실제 발생한 손해에 한하며, 손해배상 예정액은 계약금액을 초과하지 아니한다.",
      lawReferences: [
        { lawName: "민법", article: "제398조", snippet: "당사자는 손해배상에 관한 예정액을 약정할 수 있다. 손해배상의 예정액이 부당히 과다한 경우에는 법원은 적당히 감액할 수 있다." },
        { lawName: "하도급법", article: "제11조", snippet: "원사업자는 정당한 사유 없이 하도급대금을 감액하여서는 아니 된다." },
      ],
      supportingDocuments: [
        { title: "과다 위약금 조항에 대한 대법원 판례", type: "precedent", excerpt: "계약금액의 100%를 초과하는 위약금은 부당하게 과다한 것으로..." },
      ],
    },
    {
      id: "i7",
      title: "일방적 계약해지 조항",
      riskLevel: "high",
      clauseId: "c8",
      detectedClause: "갑은 언제든지 본 계약을 해지할 수 있으며... 을의 해지 요청은 갑의 서면 승인을 요한다.",
      explanation: "원사업자만 자유롭게 해지할 수 있고 수급사업자의 해지는 제한하는 조항은 불공정합니다.",
      suggestedRevision: "갑과 을은 상대방의 귀책사유가 있는 경우 30일 전 서면 통지 후 계약을 해지할 수 있다.",
      lawReferences: [
        { lawName: "하도급법", article: "제8조", snippet: "원사업자는 수급사업자에게 위탁한 후 수급사업자의 책임으로 돌릴 사유가 없는 경우에는 위탁을 임의로 취소하여서는 아니 된다." },
      ],
      supportingDocuments: [
        { title: "불공정 해지조항 관련 공정위 결정례", type: "case", excerpt: "해지권을 원사업자에게만 부여하는 것은 불공정 거래행위..." },
      ],
    },
    {
      id: "i8",
      title: "일방적 관할법원 지정",
      riskLevel: "low",
      clauseId: "c9",
      detectedClause: "갑의 본사 소재지를 관할하는 법원을 전속관할로 한다.",
      explanation: "일방적으로 원사업자의 소재지 법원으로 전속관할을 지정하는 것은 수급사업자에게 불리할 수 있습니다.",
      suggestedRevision: "분쟁 발생 시 민사소송법에 따른 관할법원에서 해결한다.",
      lawReferences: [
        { lawName: "민사소송법", article: "제29조", snippet: "합의에 의한 관할은 일정한 법률관계에 기한 소에 관하여 서면으로 정할 수 있다." },
      ],
      supportingDocuments: [],
    },
    {
      id: "i9",
      title: "갑 결정 우선 조항",
      riskLevel: "medium",
      clauseId: "c10",
      detectedClause: "협의가 되지 않는 경우 갑의 결정에 따른다.",
      explanation: "미정 사항에 대해 원사업자의 결정을 우선하는 조항은 수급사업자에게 불리한 조건을 일방적으로 부과할 수 있습니다.",
      suggestedRevision: "협의가 되지 않는 경우 관련 법령 및 상관례에 따르며, 필요시 제3의 전문기관에 자문을 구한다.",
      lawReferences: [
        { lawName: "하도급법", article: "제3조", snippet: "원사업자와 수급사업자는 대등한 지위에서 합의에 따라 공정하게 계약을 체결하여야 한다." },
      ],
      supportingDocuments: [
        { title: "하도급 표준계약서 해설집", type: "commentary", excerpt: "계약 당사자 간 대등한 지위를 보장하기 위해..." },
      ],
    },
  ],
};

const riskConfig: Record<RiskLevel, { label: string; className: string; bgClassName: string }> = {
  high: { label: "고위험", className: "text-destructive", bgClassName: "bg-destructive/10 border-destructive/30" },
  medium: { label: "주의", className: "text-orange-600 dark:text-orange-400", bgClassName: "bg-orange-50 border-orange-200 dark:bg-orange-950/30 dark:border-orange-800" },
  low: { label: "참고", className: "text-amber-600 dark:text-amber-400", bgClassName: "bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-800" },
};

const statusConfig: Record<OverallStatus, { label: string; icon: typeof ShieldCheck; className: string }> = {
  safe: { label: "안전", icon: ShieldCheck, className: "text-primary" },
  attention: { label: "주의 필요", icon: AlertTriangle, className: "text-orange-600 dark:text-orange-400" },
  "high-risk": { label: "고위험", icon: ShieldAlert, className: "text-destructive" },
};

const refTypeLabels: Record<ReferenceType, string> = {
  precedent: "판례",
  interpretation: "해석례",
  case: "사례",
  commentary: "해설",
};

const ContractReviewResult = () => {
  const [activeTab, setActiveTab] = useState("all");
  const [activeIssueId, setActiveIssueId] = useState<string | null>(null);
  const clauseRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const issueRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  const review = mockReview;
  const clauses = mockClauses;
  const StatusIcon = statusConfig[review.overallStatus].icon;

  const highCount = review.issues.filter((i) => i.riskLevel === "high").length;
  const mediumCount = review.issues.filter((i) => i.riskLevel === "medium").length;
  const lowCount = review.issues.filter((i) => i.riskLevel === "low").length;

  const filteredIssues = review.issues.filter((issue) => {
    if (activeTab === "all") return true;
    if (activeTab === "high") return issue.riskLevel === "high";
    if (activeTab === "references") return true;
    return true;
  });

  const scrollToClause = useCallback((clauseId: string) => {
    const el = clauseRefs.current.get(clauseId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("ring-2", "ring-primary");
      setTimeout(() => el.classList.remove("ring-2", "ring-primary"), 2000);
    }
  }, []);

  const scrollToIssue = useCallback((issueId: string) => {
    setActiveIssueId(issueId);
    const el = issueRefs.current.get(issueId);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, []);

  const handleDownload = () => {
    toast.info("검토 보고서를 다운로드합니다.");
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    toast.success("클립보드에 복사되었습니다.");
  };

  const handleFollowUp = (clause: string) => {
    toast.info("후속 질문 모드", { description: `"${clause.slice(0, 30)}..."에 대해 질문합니다.` });
  };

  const handleRegenerate = () => {
    toast.info("검토를 다시 수행합니다.");
  };

  const setClauseRef = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) clauseRefs.current.set(id, el);
  }, []);

  const setIssueRef = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) issueRefs.current.set(id, el);
  }, []);

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <div className="flex flex-1 flex-col">
          <header className="flex h-10 items-center border-b border-border px-2">
            <SidebarTrigger />
          </header>

          {/* Summary Bar */}
          <div className="border-b border-border bg-card px-6 py-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className={cn("flex items-center gap-2", statusConfig[review.overallStatus].className)}>
                  <StatusIcon className="h-5 w-5" />
                  <span className="text-lg font-semibold">{statusConfig[review.overallStatus].label}</span>
                </div>
                <Separator orientation="vertical" className="h-6" />
                <div className="flex items-center gap-3 text-sm text-muted-foreground">
                  <Badge variant="outline" className="gap-1">
                    <FileText className="h-3 w-3" />
                    {review.contractType}
                  </Badge>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {review.reviewTimestamp.toLocaleString("ko-KR")}
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 text-sm">
                  <Badge variant="destructive" className="text-xs">{highCount} 고위험</Badge>
                  <Badge className="border-orange-300 bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300 text-xs">{mediumCount} 주의</Badge>
                  <Badge variant="secondary" className="text-xs">{lowCount} 참고</Badge>
                </div>
                <Separator orientation="vertical" className="h-6" />
                <div className="flex items-center gap-1">
                  <Button variant="outline" size="sm" onClick={handleDownload}>
                    <Download className="mr-1 h-3 w-3" />
                    보고서
                  </Button>
                  <Button variant="outline" size="sm" onClick={handleRegenerate}>
                    <RefreshCw className="mr-1 h-3 w-3" />
                    재검토
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Main Split Layout */}
          <div className="flex flex-1 overflow-hidden">
            {/* Left: Contract Viewer */}
            <div className="flex flex-1 flex-col border-r border-border">
              <div className="flex items-center justify-between border-b border-border px-4 py-2">
                <h2 className="text-sm font-semibold text-foreground">계약서 원문</h2>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm bg-destructive/30" /> 고위험
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm bg-orange-300/50" /> 주의
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-200/50" /> 참고
                  </span>
                </div>
              </div>
              <ScrollArea className="flex-1">
                <div className="space-y-1 p-6">
                  <h3 className="mb-6 text-center text-lg font-bold text-foreground">
                    소프트웨어 개발 용역 하도급 계약서
                  </h3>
                  {clauses.map((clause) => {
                    const highlightClass =
                      clause.riskLevel === "high"
                        ? "border-l-4 border-l-destructive bg-destructive/5"
                        : clause.riskLevel === "medium"
                          ? "border-l-4 border-l-orange-400 bg-orange-50/50 dark:bg-orange-950/20"
                          : clause.riskLevel === "low"
                            ? "border-l-4 border-l-amber-400 bg-amber-50/50 dark:bg-amber-950/20"
                            : "";

                    return (
                      <div
                        key={clause.id}
                        ref={(el) => setClauseRef(clause.id, el)}
                        className={cn(
                          "cursor-pointer rounded-md px-4 py-3 text-sm leading-relaxed text-foreground transition-all",
                          highlightClass,
                          clause.issueId && "hover:opacity-80",
                          activeIssueId && clause.issueId === activeIssueId && "ring-2 ring-primary"
                        )}
                        onClick={() => clause.issueId && scrollToIssue(clause.issueId)}
                      >
                        {clause.text}
                      </div>
                    );
                  })}
                </div>
              </ScrollArea>
            </div>

            {/* Right: Issue Panel */}
            <div className="hidden w-[440px] shrink-0 flex-col lg:flex">
              <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-1 flex-col">
                <div className="border-b border-border px-4 pt-2">
                  <TabsList className="w-full">
                    <TabsTrigger value="all" className="flex-1 text-xs">
                      전체 ({review.totalIssues})
                    </TabsTrigger>
                    <TabsTrigger value="high" className="flex-1 text-xs">
                      고위험 ({highCount})
                    </TabsTrigger>
                    <TabsTrigger value="references" className="flex-1 text-xs">
                      참조 문서
                    </TabsTrigger>
                  </TabsList>
                </div>

                <ScrollArea className="flex-1">
                  {/* Issues Tab */}
                  <TabsContent value="all" className="m-0 space-y-3 p-4">
                    {filteredIssues.map((issue) => (
                      <IssueCard
                        key={issue.id}
                        issue={issue}
                        isActive={activeIssueId === issue.id}
                        refCallback={(el) => setIssueRef(issue.id, el)}
                        onScrollToClause={scrollToClause}
                        onCopy={handleCopy}
                        onFollowUp={handleFollowUp}
                      />
                    ))}
                  </TabsContent>

                  <TabsContent value="high" className="m-0 space-y-3 p-4">
                    {filteredIssues.map((issue) => (
                      <IssueCard
                        key={issue.id}
                        issue={issue}
                        isActive={activeIssueId === issue.id}
                        refCallback={(el) => setIssueRef(issue.id, el)}
                        onScrollToClause={scrollToClause}
                        onCopy={handleCopy}
                        onFollowUp={handleFollowUp}
                      />
                    ))}
                  </TabsContent>

                  <TabsContent value="references" className="m-0 space-y-3 p-4">
                    {review.issues.filter((i) => i.supportingDocuments.length > 0).map((issue) => (
                      <Card key={issue.id} className="text-sm">
                        <CardContent className="space-y-3 p-4">
                          <div className="flex items-center gap-2">
                            <Badge variant="outline" className={cn("text-xs", riskConfig[issue.riskLevel].className)}>
                              {riskConfig[issue.riskLevel].label}
                            </Badge>
                            <span className="font-medium text-foreground">{issue.title}</span>
                          </div>
                          {issue.lawReferences.map((ref, idx) => (
                            <div key={idx} className="rounded-md border border-border bg-muted/30 p-3">
                              <div className="flex items-center gap-1.5 text-xs font-medium text-primary">
                                <Scale className="h-3 w-3" />
                                {ref.lawName} {ref.article}
                              </div>
                              <p className="mt-1 text-xs text-muted-foreground">{ref.snippet}</p>
                            </div>
                          ))}
                          {issue.supportingDocuments.map((doc, idx) => (
                            <div key={idx} className="rounded-md border border-border p-3">
                              <div className="flex items-center gap-2">
                                <BookOpen className="h-3 w-3 text-muted-foreground" />
                                <span className="text-xs font-medium text-foreground">{doc.title}</span>
                                <Badge variant="secondary" className="text-[10px]">
                                  {refTypeLabels[doc.type]}
                                </Badge>
                              </div>
                              <p className="mt-1 text-xs text-muted-foreground">{doc.excerpt}</p>
                            </div>
                          ))}
                        </CardContent>
                      </Card>
                    ))}
                  </TabsContent>
                </ScrollArea>
              </Tabs>
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

// Issue Card Component
interface IssueCardProps {
  issue: ReviewIssue;
  isActive: boolean;
  refCallback: (el: HTMLDivElement | null) => void;
  onScrollToClause: (clauseId: string) => void;
  onCopy: (text: string) => void;
  onFollowUp: (clause: string) => void;
}

function IssueCard({ issue, isActive, refCallback, onScrollToClause, onCopy, onFollowUp }: IssueCardProps) {
  return (
    <div
      ref={refCallback}
      className={cn(
        "rounded-lg border transition-all",
        isActive ? "border-primary ring-1 ring-primary/20" : "border-border",
        riskConfig[issue.riskLevel].bgClassName
      )}
    >
      <div className="space-y-3 p-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className={cn("text-xs", riskConfig[issue.riskLevel].className)}>
                {riskConfig[issue.riskLevel].label}
              </Badge>
              <h4 className="text-sm font-semibold text-foreground">{issue.title}</h4>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="shrink-0 text-xs text-muted-foreground"
            onClick={() => onScrollToClause(issue.clauseId)}
          >
            원문 보기
            <ChevronRight className="ml-0.5 h-3 w-3" />
          </Button>
        </div>

        {/* Detected clause */}
        <div className="rounded-md bg-muted/60 px-3 py-2 text-xs italic text-muted-foreground">
          "{issue.detectedClause}"
        </div>

        {/* Explanation */}
        <p className="text-xs leading-relaxed text-foreground">{issue.explanation}</p>

        {/* Suggestion */}
        <div className="rounded-md border border-primary/20 bg-primary/5 px-3 py-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-primary">수정 제안</p>
          <p className="mt-1 text-xs text-foreground">{issue.suggestedRevision}</p>
        </div>

        {/* Law references */}
        {issue.lawReferences.length > 0 && (
          <div className="space-y-1.5">
            {issue.lawReferences.map((ref, idx) => (
              <div key={idx} className="flex items-start gap-1.5 text-xs">
                <Scale className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                <span>
                  <span className="font-medium text-primary">{ref.lawName} {ref.article}</span>
                  <span className="text-muted-foreground"> — {ref.snippet.slice(0, 60)}...</span>
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Supporting documents */}
        {issue.supportingDocuments.length > 0 && (
          <div className="space-y-1.5">
            {issue.supportingDocuments.map((doc, idx) => (
              <div key={idx} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <ExternalLink className="h-3 w-3 shrink-0" />
                <span>{doc.title}</span>
                <Badge variant="secondary" className="text-[10px]">{refTypeLabels[doc.type]}</Badge>
              </div>
            ))}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-1 border-t border-border/50 pt-2">
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => onCopy(issue.explanation + "\n\n수정 제안: " + issue.suggestedRevision)}>
            <Copy className="mr-1 h-3 w-3" /> 복사
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => onFollowUp(issue.detectedClause)}>
            <MessageSquare className="mr-1 h-3 w-3" /> 질문
          </Button>
        </div>
      </div>
    </div>
  );
}

export default ContractReviewResult;
