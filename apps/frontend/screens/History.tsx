import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
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
import { deleteHistoryItem, deleteHistoryItems, getHistory, HistoryItem } from "@/lib/api-client";
import { SimpleMarkdown } from "@/components/SimpleMarkdown";

const LIMIT = 20;

function deriveCitations(item: HistoryItem): string[] {
  const seen = new Set<string>();
  return item.sources
    .filter((s) => s.doc_type === "law" && s.law_name)
    .map((s) => s.article_no ? `${s.law_name} ${s.article_no}` : s.law_name)
    .filter((c) => { if (seen.has(c)) return false; seen.add(c); return true; });
}

function extractArticleContent(text: string): string {
  const match = text.match(/제\d+조/);
  if (match?.index !== undefined) return text.slice(match.index);
  return text;
}

function deriveRelatedLaws(item: HistoryItem): string[] {
  return [...new Set(item.sources.map((s) => s.law_name).filter(Boolean))];
}

const History = () => {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const [startDate, setStartDate] = useState<Date | undefined>();
  const [endDate, setEndDate] = useState<Date | undefined>();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set());
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set());
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());

  // 다중 선택
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);

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
    } catch (e) {
      console.error("[LAS:HISTORY] 조회 실패:", e);
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

  const toggleSources = (id: string) => {
    setExpandedSources((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((i) => i.id)));
    }
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds(new Set());
  };

  const handleCopy = (answer: string) => {
    navigator.clipboard.writeText(answer);
    toast.success("답변이 클립보드에 복사되었습니다.");
  };

  const handleDelete = async (id: string) => {
    setDeletingIds((prev) => new Set(prev).add(id));
    try {
      await deleteHistoryItem(id);
      setItems((prev) => prev.filter((item) => item.id !== id));
      setTotal((prev) => prev - 1);
      toast.success("히스토리가 삭제되었습니다.");
    } catch (e) {
      console.error("[LAS:HISTORY] 삭제 실패:", e);
      toast.error("삭제에 실패했습니다. 다시 시도해주세요.");
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const handleBulkDelete = async () => {
    setIsBulkDeleting(true);
    const ids = [...selectedIds];
    try {
      const { deleted } = await deleteHistoryItems(ids);
      setItems((prev) => prev.filter((item) => !selectedIds.has(item.id)));
      setTotal((prev) => prev - deleted);
      setSelectedIds(new Set());
      setSelectMode(false);
      toast.success(`${deleted}개의 히스토리가 삭제되었습니다.`);
    } catch (e) {
      console.error("[LAS:HISTORY] 일괄 삭제 실패:", e);
      toast.error("삭제에 실패했습니다. 다시 시도해주세요.");
    } finally {
      setIsBulkDeleting(false);
    }
  };

  const handleFollowUp = (item: HistoryItem) => {
    sessionStorage.setItem(
      "las_followup_context",
      JSON.stringify({ question: item.question, answer: item.answer })
    );
    router.push("/chat");
  };

  const clearFilters = () => {
    setSearchQuery("");
    setStartDate(undefined);
    setEndDate(undefined);
  };

  const hasMore = items.length < total;
  const hasFilter = !!(searchQuery || startDate || endDate);
  const allSelected = items.length > 0 && selectedIds.size === items.length;

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <div className="flex flex-1 flex-col">
          <header className="flex h-10 items-center border-b border-border px-2 gap-2">
            <SidebarTrigger />
            <div className="h-4 w-px bg-border" />
            <span className="text-sm font-medium text-muted-foreground">히스토리</span>
          </header>

          <div className="flex-1 overflow-auto bg-muted/30 p-6">
            <div className="mx-auto max-w-4xl space-y-6">
              {/* Header */}
              <div className="flex items-start justify-between">
                <div>
                  <h1 className="text-2xl font-semibold text-foreground">히스토리</h1>
                  <p className="text-sm text-muted-foreground">
                    이전 법률 Q&A 대화 내역을 확인합니다.
                  </p>
                </div>
                {!isLoading && items.length > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => (selectMode ? exitSelectMode() : setSelectMode(true))}
                  >
                    {selectMode ? "취소" : "선택"}
                  </Button>
                )}
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
                        className="pl-9 focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-primary/60 focus-visible:[box-shadow:0_0_0_3px_hsl(var(--primary)/0.08),0_0_10px_hsl(var(--primary)/0.12)]"
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
                      const isSelected = selectedIds.has(item.id);
                      const citations = deriveCitations(item);
                      const relatedLaws = deriveRelatedLaws(item);

                      return (
                        <Collapsible
                          key={item.id}
                          open={!selectMode && isExpanded}
                          onOpenChange={() => !selectMode && toggleExpand(item.id)}
                        >
                          <Card
                            className={cn(
                              "transition-all duration-200",
                              !selectMode && isExpanded && "ring-1 ring-primary/20",
                              selectMode && isSelected && "ring-2 ring-primary",
                              selectMode && "cursor-pointer"
                            )}
                            onClick={() => selectMode && toggleSelect(item.id)}
                          >
                            <CollapsibleTrigger asChild>
                              <CardContent className={cn("p-4", !selectMode && "cursor-pointer")}>
                                <div className="flex items-start gap-3">
                                  {/* 체크박스 (선택 모드) */}
                                  {selectMode && (
                                    <div className="mt-0.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                                      <Checkbox
                                        checked={isSelected}
                                        onCheckedChange={() => toggleSelect(item.id)}
                                      />
                                    </div>
                                  )}

                                  <div className="flex flex-1 items-start justify-between gap-4">
                                    <div className="flex-1 space-y-2">
                                      <p className="font-medium text-foreground">{item.question}</p>

                                      {!isExpanded && (
                                        <p className="line-clamp-2 text-sm text-muted-foreground">
                                          {item.answer}
                                        </p>
                                      )}

                                      <div className="flex flex-wrap items-center gap-2">
                                        {citations.slice(0, 2).map((c, idx) => (
                                          <Badge key={`${c}-${idx}`} variant="outline" className="text-xs">
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

                                    {!selectMode && (
                                      <Button variant="ghost" size="icon" className="shrink-0">
                                        {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                                      </Button>
                                    )}
                                  </div>
                                </div>
                              </CardContent>
                            </CollapsibleTrigger>

                            <CollapsibleContent>
                              <div className="border-t border-border">
                                <CardContent className="space-y-4 p-4">
                                  <div className="space-y-2">
                                    <h4 className="text-sm font-medium text-foreground">AI 답변</h4>
                                    <div className="rounded-lg bg-muted/50 p-4 text-sm text-foreground">
                                      <SimpleMarkdown>{item.answer}</SimpleMarkdown>
                                    </div>
                                  </div>

                                  {citations.length > 0 && (
                                    <Collapsible
                                      open={expandedSources.has(item.id)}
                                      onOpenChange={() => toggleSources(item.id)}
                                    >
                                      <CollapsibleTrigger asChild>
                                        <button
                                          className="flex w-full items-center justify-between text-sm font-medium text-foreground hover:text-primary"
                                          onClick={(e) => e.stopPropagation()}
                                        >
                                          <span className="flex items-center gap-1.5">
                                            <Scale className="h-3.5 w-3.5" />
                                            근거 조문
                                            <span className="text-xs font-normal text-muted-foreground">({citations.length})</span>
                                          </span>
                                          {expandedSources.has(item.id)
                                            ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
                                            : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                                          }
                                        </button>
                                      </CollapsibleTrigger>
                                      <CollapsibleContent>
                                        <div className="mt-2 space-y-2" onClick={(e) => e.stopPropagation()}>
                                          {item.sources
                                            .filter((s) => s.doc_type === "law")
                                            .map((s, idx) => {
                                              const label = s.article_no ? `${s.law_name} ${s.article_no}` : s.law_name;
                                              const raw = s.text || s.snippet;
                                              const content = raw ? extractArticleContent(raw) : null;
                                              return (
                                                <div key={`${item.id}-src-${idx}`} className="rounded-md border border-primary/20 bg-primary/5 p-3 text-sm">
                                                  <p className="mb-1.5 font-medium text-foreground">{label}</p>
                                                  {content ? (
                                                    <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{content}</p>
                                                  ) : (
                                                    <p className="text-xs text-muted-foreground/50">조문 내용이 저장되지 않았습니다.</p>
                                                  )}
                                                </div>
                                              );
                                            })}
                                        </div>
                                      </CollapsibleContent>
                                    </Collapsible>
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
                                      onClick={(e) => { e.stopPropagation(); handleFollowUp(item); }}
                                    >
                                      <MessageSquarePlus className="mr-1 h-3 w-3" />
                                      후속 질문
                                    </Button>
                                    <AlertDialog>
                                      <AlertDialogTrigger asChild>
                                        <Button
                                          variant="ghost"
                                          size="sm"
                                          className="ml-auto text-destructive hover:bg-destructive/10 hover:text-destructive"
                                          disabled={deletingIds.has(item.id)}
                                          onClick={(e) => e.stopPropagation()}
                                        >
                                          {deletingIds.has(item.id) ? (
                                            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                          ) : (
                                            <Trash2 className="mr-1 h-3 w-3" />
                                          )}
                                          삭제
                                        </Button>
                                      </AlertDialogTrigger>
                                      <AlertDialogContent onClick={(e) => e.stopPropagation()}>
                                        <AlertDialogHeader>
                                          <AlertDialogTitle>히스토리 삭제</AlertDialogTitle>
                                          <AlertDialogDescription>
                                            이 대화 내역을 삭제하시겠습니까? 삭제 후 복구할 수 없습니다.
                                          </AlertDialogDescription>
                                        </AlertDialogHeader>
                                        <AlertDialogFooter>
                                          <AlertDialogCancel>취소</AlertDialogCancel>
                                          <AlertDialogAction
                                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                            onClick={() => handleDelete(item.id)}
                                          >
                                            삭제
                                          </AlertDialogAction>
                                        </AlertDialogFooter>
                                      </AlertDialogContent>
                                    </AlertDialog>
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

      {/* 다중 선택 액션바 */}
      {selectMode && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
          <div className="flex items-center gap-3 rounded-xl border border-border bg-background px-4 py-3 shadow-lg">
            <div
              className="flex cursor-pointer items-center gap-2"
              onClick={toggleSelectAll}
            >
              <Checkbox checked={allSelected} />
              <span className="text-sm text-muted-foreground whitespace-nowrap">
                {selectedIds.size > 0 ? `${selectedIds.size}개 선택됨` : "전체 선택"}
              </span>
            </div>

            <div className="h-4 w-px bg-border" />

            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={selectedIds.size === 0 || isBulkDeleting}
                >
                  {isBulkDeleting ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : (
                    <Trash2 className="mr-1 h-3 w-3" />
                  )}
                  삭제
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>히스토리 삭제</AlertDialogTitle>
                  <AlertDialogDescription>
                    선택한 {selectedIds.size}개의 대화 내역을 삭제하시겠습니까? 삭제 후 복구할 수 없습니다.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>취소</AlertDialogCancel>
                  <AlertDialogAction
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                    onClick={handleBulkDelete}
                  >
                    삭제
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>

            <Button variant="ghost" size="sm" onClick={exitSelectMode}>
              취소
            </Button>
          </div>
        </div>
      )}
    </SidebarProvider>
  );
};

export default History;
