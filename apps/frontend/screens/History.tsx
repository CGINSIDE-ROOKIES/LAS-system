import { useState } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { toast } from "sonner";
import {
  Search,
  CalendarIcon,
  ChevronDown,
  ChevronUp,
  Trash2,
  Copy,
  MessageSquarePlus,
  Scale,
  FileText,
} from "lucide-react";
import { format } from "date-fns";
import { ko } from "date-fns/locale";
import { cn } from "@/lib/utils";

interface HistoryItem {
  id: string;
  question: string;
  answer: string;
  timestamp: Date;
  lawType: string;
  citations: string[];
  relatedLaws: string[];
}

const mockHistory: HistoryItem[] = [
  {
    id: "1",
    question: "근로계약서 작성 시 필수 기재사항은 무엇인가요?",
    answer:
      "근로기준법 제17조에 따르면, 근로계약서에는 다음 사항을 명시해야 합니다:\n\n1. 임금의 구성항목, 계산방법, 지급방법\n2. 소정근로시간\n3. 주휴일\n4. 연차 유급휴가\n5. 취업의 장소와 종사하여야 할 업무에 관한 사항\n6. 근로계약 기간에 관한 사항\n\n특히 기간제 근로자의 경우 계약기간, 근로시간, 휴게시간에 관한 사항도 반드시 포함되어야 합니다.",
    timestamp: new Date("2024-01-15T10:30:00"),
    lawType: "labor",
    citations: ["근로기준법 제17조", "근로기준법 시행령 제8조"],
    relatedLaws: ["근로기준법", "기간제법"],
  },
  {
    id: "2",
    question: "연장근로수당 지급 기준은 어떻게 되나요?",
    answer:
      "근로기준법 제56조에 따르면, 연장근로에 대해서는 통상임금의 100분의 50 이상을 가산하여 지급해야 합니다.\n\n연장근로란 1주간 40시간, 1일 8시간을 초과하는 근로를 말합니다. 야간근로(오후 10시부터 오전 6시까지)와 휴일근로의 경우에도 각각 50% 이상의 가산임금이 적용됩니다.\n\n5인 미만 사업장의 경우 연장근로 가산수당 규정이 적용되지 않습니다.",
    timestamp: new Date("2024-01-14T14:20:00"),
    lawType: "labor",
    citations: ["근로기준법 제56조", "근로기준법 제50조"],
    relatedLaws: ["근로기준법", "최저임금법"],
  },
  {
    id: "3",
    question: "하도급 계약에서 위법 소지가 있는 조항은 무엇인가요?",
    answer:
      "하도급거래 공정화에 관한 법률에 따르면, 다음과 같은 조항은 위법 소지가 있습니다:\n\n1. 부당한 하도급대금 결정 (제4조)\n2. 부당한 위탁취소 (제8조)\n3. 부당반품 (제10조)\n4. 부당한 대금 감액 (제11조)\n5. 물품구매 강제 (제12조)\n6. 경제적 이익의 부당요구 (제12조의2)\n\n특히 원사업자가 정당한 사유 없이 목적물 수령일로부터 60일을 초과하여 대금을 지급하지 않는 것은 지급지연에 해당합니다.",
    timestamp: new Date("2024-01-12T09:15:00"),
    lawType: "subcontract",
    citations: ["하도급법 제4조", "하도급법 제13조"],
    relatedLaws: ["하도급법", "공정거래법"],
  },
  {
    id: "4",
    question: "최저임금 미달 시 제재는 어떻게 되나요?",
    answer:
      "최저임금법 제28조에 따르면, 최저임금액 미만의 임금을 지급한 사용자는 3년 이하의 징역 또는 2천만원 이하의 벌금에 처해집니다.\n\n또한, 근로자에게 최저임금액 이상을 지급하지 아니한 사용자에게는 미지급 임금에 대한 지연이자도 부과될 수 있습니다.",
    timestamp: new Date("2024-01-10T16:45:00"),
    lawType: "minwage",
    citations: ["최저임금법 제28조", "최저임금법 제6조"],
    relatedLaws: ["최저임금법", "근로기준법"],
  },
];

const lawTypeLabels: Record<string, string> = {
  labor: "근로기준법",
  subcontract: "하도급법",
  minwage: "최저임금법",
};

const History = () => {
  const [searchQuery, setSearchQuery] = useState("");
  const [lawFilter, setLawFilter] = useState<string>("all");
  const [startDate, setStartDate] = useState<Date | undefined>();
  const [endDate, setEndDate] = useState<Date | undefined>();
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set());
  const [history, setHistory] = useState<HistoryItem[]>(mockHistory);

  const toggleExpand = (id: string) => {
    setExpandedItems((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      return newSet;
    });
  };

  const filteredHistory = history.filter((item) => {
    const matchesSearch =
      searchQuery === "" ||
      item.question.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.answer.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesLaw = lawFilter === "all" || item.lawType === lawFilter;

    const matchesDateRange =
      (!startDate || item.timestamp >= startDate) &&
      (!endDate || item.timestamp <= endDate);

    return matchesSearch && matchesLaw && matchesDateRange;
  });

  const handleDelete = (id: string) => {
    setHistory((prev) => prev.filter((item) => item.id !== id));
    toast.success("히스토리가 삭제되었습니다.");
  };

  const handleCopy = (answer: string) => {
    navigator.clipboard.writeText(answer);
    toast.success("답변이 클립보드에 복사되었습니다.");
  };

  const handleFollowUp = (question: string) => {
    toast.info("후속 질문 기능", {
      description: `"${question.slice(0, 30)}..."에 대한 후속 질문을 작성합니다.`,
    });
  };

  const clearFilters = () => {
    setSearchQuery("");
    setLawFilter("all");
    setStartDate(undefined);
    setEndDate(undefined);
  };

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <div className="flex flex-1 flex-col">
          <header className="flex h-10 items-center border-b border-border px-2">
            <SidebarTrigger />
          </header>

          <div className="flex-1 overflow-auto bg-muted/30 p-6">
            <div className="mx-auto max-w-4xl space-y-6">
              {/* Header */}
              <div>
                <h1 className="text-2xl font-semibold text-foreground">히스토리</h1>
                <p className="text-sm text-muted-foreground">
                  이전 법률 Q&A 대화 내역을 확인합니다.
                </p>
              </div>

              {/* Search & Filters */}
              <Card>
                <CardContent className="p-4">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
                    {/* Search */}
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        placeholder="질문 또는 답변 검색..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="pl-9"
                      />
                    </div>

                    {/* Law Filter */}
                    <Select value={lawFilter} onValueChange={setLawFilter}>
                      <SelectTrigger className="w-full sm:w-[160px]">
                        <SelectValue placeholder="법령 선택" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">전체 법령</SelectItem>
                        <SelectItem value="labor">근로기준법</SelectItem>
                        <SelectItem value="subcontract">하도급법</SelectItem>
                        <SelectItem value="minwage">최저임금법</SelectItem>
                      </SelectContent>
                    </Select>

                    {/* Date Range */}
                    <Popover>
                      <PopoverTrigger asChild>
                        <Button
                          variant="outline"
                          className={cn(
                            "w-full justify-start text-left font-normal sm:w-[200px]",
                            !startDate && !endDate && "text-muted-foreground"
                          )}
                        >
                          <CalendarIcon className="mr-2 h-4 w-4" />
                          {startDate && endDate
                            ? `${format(startDate, "MM/dd")} - ${format(endDate, "MM/dd")}`
                            : startDate
                              ? format(startDate, "yyyy-MM-dd")
                              : "기간 선택"}
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent className="w-auto p-0" align="end">
                        <Calendar
                          mode="range"
                          selected={{ from: startDate, to: endDate }}
                          onSelect={(range) => {
                            setStartDate(range?.from);
                            setEndDate(range?.to);
                          }}
                          locale={ko}
                          className="pointer-events-auto p-3"
                        />
                      </PopoverContent>
                    </Popover>

                    {(searchQuery || lawFilter !== "all" || startDate || endDate) && (
                      <Button variant="ghost" size="sm" onClick={clearFilters}>
                        초기화
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Results Count */}
              <p className="text-sm text-muted-foreground">
                {filteredHistory.length}개의 대화 내역
              </p>

              {/* History List */}
              <div className="space-y-3">
                {filteredHistory.length === 0 ? (
                  <Card>
                    <CardContent className="flex flex-col items-center justify-center py-12 text-center">
                      <FileText className="h-12 w-12 text-muted-foreground/50" />
                      <p className="mt-4 text-sm text-muted-foreground">
                        검색 결과가 없습니다.
                      </p>
                    </CardContent>
                  </Card>
                ) : (
                  filteredHistory.map((item) => {
                    const isExpanded = expandedItems.has(item.id);
                    return (
                      <Collapsible
                        key={item.id}
                        open={isExpanded}
                        onOpenChange={() => toggleExpand(item.id)}
                      >
                        <Card
                          className={cn(
                            "transition-all duration-200",
                            isExpanded && "ring-1 ring-primary/20"
                          )}
                        >
                          <CollapsibleTrigger asChild>
                            <CardContent className="cursor-pointer p-4">
                              <div className="flex items-start justify-between gap-4">
                                <div className="flex-1 space-y-2">
                                  {/* Question */}
                                  <p className="font-medium text-foreground">
                                    {item.question}
                                  </p>

                                  {/* Answer Preview */}
                                  {!isExpanded && (
                                    <p className="line-clamp-2 text-sm text-muted-foreground">
                                      {item.answer}
                                    </p>
                                  )}

                                  {/* Meta */}
                                  <div className="flex flex-wrap items-center gap-2">
                                    <Badge variant="secondary" className="text-xs">
                                      {lawTypeLabels[item.lawType]}
                                    </Badge>
                                    {item.citations.slice(0, 2).map((citation) => (
                                      <Badge
                                        key={citation}
                                        variant="outline"
                                        className="text-xs"
                                      >
                                        {citation}
                                      </Badge>
                                    ))}
                                    <span className="text-xs text-muted-foreground">
                                      {format(item.timestamp, "yyyy.MM.dd HH:mm", {
                                        locale: ko,
                                      })}
                                    </span>
                                  </div>
                                </div>

                                <Button variant="ghost" size="icon" className="shrink-0">
                                  {isExpanded ? (
                                    <ChevronUp className="h-4 w-4" />
                                  ) : (
                                    <ChevronDown className="h-4 w-4" />
                                  )}
                                </Button>
                              </div>
                            </CardContent>
                          </CollapsibleTrigger>

                          <CollapsibleContent>
                            <div className="border-t border-border">
                              <CardContent className="space-y-4 p-4">
                                {/* Full Answer */}
                                <div className="space-y-2">
                                  <h4 className="text-sm font-medium text-foreground">
                                    AI 답변
                                  </h4>
                                  <div className="whitespace-pre-wrap rounded-lg bg-muted/50 p-4 text-sm text-foreground">
                                    {item.answer}
                                  </div>
                                </div>

                                {/* Citations */}
                                <div className="space-y-2">
                                  <h4 className="text-sm font-medium text-foreground">
                                    근거 조문
                                  </h4>
                                  <div className="flex flex-wrap gap-2">
                                    {item.citations.map((citation) => (
                                      <Badge
                                        key={citation}
                                        variant="outline"
                                        className="border-primary/30 bg-primary/5"
                                      >
                                        <Scale className="mr-1 h-3 w-3" />
                                        {citation}
                                      </Badge>
                                    ))}
                                  </div>
                                </div>

                                {/* Related Laws */}
                                <div className="space-y-2">
                                  <h4 className="text-sm font-medium text-foreground">
                                    관련 법령
                                  </h4>
                                  <div className="flex flex-wrap gap-2">
                                    {item.relatedLaws.map((law) => (
                                      <Badge key={law} variant="secondary">
                                        {law}
                                      </Badge>
                                    ))}
                                  </div>
                                </div>

                                {/* Actions */}
                                <div className="flex items-center gap-2 border-t border-border pt-4">
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleCopy(item.answer);
                                    }}
                                  >
                                    <Copy className="mr-1 h-3 w-3" />
                                    복사
                                  </Button>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleFollowUp(item.question);
                                    }}
                                  >
                                    <MessageSquarePlus className="mr-1 h-3 w-3" />
                                    후속 질문
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="ml-auto text-destructive hover:bg-destructive/10 hover:text-destructive"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleDelete(item.id);
                                    }}
                                  >
                                    <Trash2 className="mr-1 h-3 w-3" />
                                    삭제
                                  </Button>
                                </div>
                              </CardContent>
                            </div>
                          </CollapsibleContent>
                        </Card>
                      </Collapsible>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default History;
