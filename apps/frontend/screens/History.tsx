import { useState, useEffect, useCallback } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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
  Copy,
  Scale,
  FileText,
  Loader2,
  Trash2,
  MessageSquarePlus,
} from "lucide-react";
import { format, addDays } from "date-fns";
import { ko } from "date-fns/locale";
import { cn } from "@/lib/utils";
import { getHistory, HistoryItem } from "@/lib/api-client";

const LIMIT = 20;

function deriveCitations(item: HistoryItem): string[] {
  return item.sources
    .filter((s) => s.doc_type === "law")
    .map((s) => s.article_no ? `${s.law_name} ${s.article_no}` : s.law_name);
}

function deriveRelatedLaws(item: HistoryItem): string[] {
  return [...new Set(item.sources.map((s) => s.law_name).filter(Boolean))];
}

const History = () => {
  const [searchQuery, setSearchQuery] = useState("");
  const [startDate, setStartDate] = useState<Date | undefined>();
  const [endDate, setEndDate] = useState<Date | undefined>();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set());

  const fetchHistory = useCallback(async (offset: number, append = false) => {
    if (append) setIsLoadingMore(true);
    else setIsLoading(true);
    setError(null);

    try {
      const result = await getHistory({
        q: searchQuery.trim() || undefined,
        date_from: startDate ? format(startDate, "yyyy-MM-dd") : undefined,
        date_to: endDate ? format(addDays(endDate, 1), "yyyy-MM-dd") : undefined,
        limit: LIMIT,
        offset,
      });
      setItems((prev) => (append ? [...prev, ...result.items] : result.items));
      setTotal(result.total);
    } catch {
      setError("히스토리를 불러오는 데 실패했습니다.");
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
    }
  }, [searchQuery, startDate, endDate]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchHistory(0);
    }, 400);
    return () => clearTimeout(timer);
  }, [fetchHistory]);

  const toggleExpand = (id: string) => {
    setExpandedItems((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleCopy = (answer: string) => {
    navigator.clipboard.writeText(answer);
    toast.success("답변이 클립보드에 복사되었습니다.");
  };

  const handleDelete = (id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
    setTotal((prev) => prev - 1);
    toast.success("히스토리가 삭제되었습니다.");
  };

  const handleFollowUp = (question: string) => {
    toast.info("후속 질문 기능", {
      description: `"${question.slice(0, 30)}..."에 대한 후속 질문을 작성합니다.`,
    });
  };

  const clearFilters = () => {
    setSearchQuery("");
    setStartDate(undefined);
    setEndDate(undefined);
  };

  const hasMore = items.length < total;
  const hasFilter = !!(searchQuery || startDate || endDate);

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
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        placeholder="질문 또는 답변 검색..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="pl-9"
                      />
                    </div>

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

                    {hasFilter && (
                      <Button variant="ghost" size="sm" onClick={clearFilters}>
                        초기화
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>

              {/* Results Count */}
              {!isLoading && (
                <p className="text-sm text-muted-foreground">총 {total}개의 대화 내역</p>
              )}

              {/* Error */}
              {error && (
                <Card>
                  <CardContent className="flex flex-col items-center justify-center py-12 text-center">
                    <p className="text-sm text-destructive">{error}</p>
                    <Button variant="outline" size="sm" className="mt-4" onClick={() => fetchHistory(0)}>
                      다시 시도
                    </Button>
                  </CardContent>
                </Card>
              )}

              {/* Loading skeleton */}
              {isLoading && (
                <div className="space-y-3">
                  {[...Array(3)].map((_, i) => (
                    <Card key={i}>
                      <CardContent className="p-4">
                        <div className="space-y-2 animate-pulse">
                          <div className="h-4 w-3/4 rounded bg-muted" />
                          <div className="h-3 w-full rounded bg-muted" />
                          <div className="h-3 w-1/2 rounded bg-muted" />
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}

              {/* History List */}
              {!isLoading && !error && (
                <div className="space-y-3">
                  {items.length === 0 ? (
                    <Card>
                      <CardContent className="flex flex-col items-center justify-center py-12 text-center">
                        <FileText className="h-12 w-12 text-muted-foreground/50" />
                        <p className="mt-4 text-sm text-muted-foreground">
                          {hasFilter ? "검색 결과가 없습니다." : "아직 대화 내역이 없습니다."}
                        </p>
                      </CardContent>
                    </Card>
                  ) : (
                    items.map((item) => {
                      const isExpanded = expandedItems.has(item.id);
                      const citations = deriveCitations(item);
                      const relatedLaws = deriveRelatedLaws(item);

                      return (
                        <Collapsible
                          key={item.id}
                          open={isExpanded}
                          onOpenChange={() => toggleExpand(item.id)}
                        >
                          <Card className={cn("transition-all duration-200", isExpanded && "ring-1 ring-primary/20")}>
                            <CollapsibleTrigger asChild>
                              <CardContent className="cursor-pointer p-4">
                                <div className="flex items-start justify-between gap-4">
                                  <div className="flex-1 space-y-2">
                                    <p className="font-medium text-foreground">{item.question}</p>

                                    {!isExpanded && (
                                      <p className="line-clamp-2 text-sm text-muted-foreground">
                                        {item.answer}
                                      </p>
                                    )}

                                    <div className="flex flex-wrap items-center gap-2">
                                      {citations.slice(0, 2).map((c) => (
                                        <Badge key={c} variant="outline" className="text-xs">
                                          {c}
                                        </Badge>
                                      ))}
                                      {citations.length > 2 && (
                                        <span className="text-xs text-muted-foreground">
                                          +{citations.length - 2}개
                                        </span>
                                      )}
                                      <span className="text-xs text-muted-foreground">
                                        {format(new Date(item.created_at), "yyyy.MM.dd HH:mm", { locale: ko })}
                                      </span>
                                    </div>
                                  </div>

                                  <Button variant="ghost" size="icon" className="shrink-0">
                                    {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                                  </Button>
                                </div>
                              </CardContent>
                            </CollapsibleTrigger>

                            <CollapsibleContent>
                              <div className="border-t border-border">
                                <CardContent className="space-y-4 p-4">
                                  <div className="space-y-2">
                                    <h4 className="text-sm font-medium text-foreground">AI 답변</h4>
                                    <div className="whitespace-pre-wrap rounded-lg bg-muted/50 p-4 text-sm text-foreground">
                                      {item.answer}
                                    </div>
                                  </div>

                                  {citations.length > 0 && (
                                    <div className="space-y-2">
                                      <h4 className="text-sm font-medium text-foreground">근거 조문</h4>
                                      <div className="flex flex-wrap gap-2">
                                        {citations.map((c) => (
                                          <Badge key={c} variant="outline" className="border-primary/30 bg-primary/5">
                                            <Scale className="mr-1 h-3 w-3" />
                                            {c}
                                          </Badge>
                                        ))}
                                      </div>
                                    </div>
                                  )}

                                  {relatedLaws.length > 0 && (
                                    <div className="space-y-2">
                                      <h4 className="text-sm font-medium text-foreground">관련 법령</h4>
                                      <div className="flex flex-wrap gap-2">
                                        {relatedLaws.map((law) => (
                                          <Badge key={law} variant="secondary">{law}</Badge>
                                        ))}
                                      </div>
                                    </div>
                                  )}

                                  <div className="flex items-center gap-2 border-t border-border pt-4">
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      onClick={(e) => { e.stopPropagation(); handleCopy(item.answer); }}
                                    >
                                      <Copy className="mr-1 h-3 w-3" />
                                      복사
                                    </Button>
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      onClick={(e) => { e.stopPropagation(); handleFollowUp(item.question); }}
                                    >
                                      <MessageSquarePlus className="mr-1 h-3 w-3" />
                                      후속 질문
                                    </Button>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="ml-auto text-destructive hover:bg-destructive/10 hover:text-destructive"
                                      onClick={(e) => { e.stopPropagation(); handleDelete(item.id); }}
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

                  {hasMore && (
                    <div className="flex justify-center pt-2">
                      <Button
                        variant="outline"
                        onClick={() => fetchHistory(items.length, true)}
                        disabled={isLoadingMore}
                      >
                        {isLoadingMore ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            불러오는 중...
                          </>
                        ) : (
                          `더보기 (${total - items.length}개 남음)`
                        )}
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default History;
