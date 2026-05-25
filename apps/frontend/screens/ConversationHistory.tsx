"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { getHistory, HistoryItem } from "@/lib/api-client";
import { SimpleMarkdown } from "@/components/SimpleMarkdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Scale, MessageSquare, Loader2, Search, SquarePen } from "lucide-react";
import { format, isToday, isYesterday, isThisWeek, isThisMonth } from "date-fns";
import { ko } from "date-fns/locale";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/components/MessageBubble";

// ─── Types ────────────────────────────────────────────────────────────────────

type ConversationThread = {
  threadId: string;
  session_id: string | null;
  title: string;
  items: HistoryItem[];
  lastDate: string;
};

// ─── Date grouping ────────────────────────────────────────────────────────────

function getDateGroup(dateStr: string): string {
  const d = new Date(dateStr);
  if (isToday(d)) return "오늘";
  if (isYesterday(d)) return "어제";
  if (isThisWeek(d, { weekStartsOn: 1 })) return "이번 주";
  if (isThisMonth(d)) return "이번 달";
  return format(d, "yyyy년 M월", { locale: ko });
}

function groupThreadsByDate(
  threads: ConversationThread[]
): { label: string; threads: ConversationThread[] }[] {
  const map = new Map<string, ConversationThread[]>();
  for (const thread of threads) {
    const label = getDateGroup(thread.lastDate);
    if (!map.has(label)) map.set(label, []);
    map.get(label)!.push(thread);
  }
  return Array.from(map.entries()).map(([label, threads]) => ({ label, threads }));
}

// ─── Thread grouping ──────────────────────────────────────────────────────────

function groupIntoThreads(items: HistoryItem[]): ConversationThread[] {
  const sessionMap = new Map<string, HistoryItem[]>();
  const orphans: HistoryItem[] = [];

  for (const item of items) {
    if (item.session_id) {
      if (!sessionMap.has(item.session_id)) sessionMap.set(item.session_id, []);
      sessionMap.get(item.session_id)!.push(item);
    } else {
      orphans.push(item);
    }
  }

  const threads: ConversationThread[] = [];

  for (const [session_id, sessionItems] of sessionMap) {
    const sorted = [...sessionItems].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
    threads.push({
      threadId: session_id,
      session_id,
      title: sorted[0].question,
      items: sorted,
      lastDate: sorted[sorted.length - 1].created_at,
    });
  }

  for (const item of orphans) {
    threads.push({
      threadId: item.id,
      session_id: null,
      title: item.question,
      items: [item],
      lastDate: item.created_at,
    });
  }

  return threads.sort(
    (a, b) => new Date(b.lastDate).getTime() - new Date(a.lastDate).getTime()
  );
}

// ─── Citation helpers ─────────────────────────────────────────────────────────

function deriveCitations(item: HistoryItem): string[] {
  const seen = new Set<string>();
  return item.sources
    .filter((s) => s.doc_type === "law" && s.law_name)
    .map((s) => (s.article_no ? `${s.law_name} ${s.article_no}` : s.law_name))
    .filter((c) => {
      if (seen.has(c)) return false;
      seen.add(c);
      return true;
    });
}

function sourcesToChatCitations(item: HistoryItem): { article: string; content: string }[] {
  const seen = new Set<string>();
  return item.sources
    .filter((s) => s.doc_type === "law" && s.law_name)
    .map((s) => ({
      article: s.article_no ? `${s.law_name} ${s.article_no}` : s.law_name,
      content: s.snippet || s.text || "",
    }))
    .filter((c) => {
      if (seen.has(c.article)) return false;
      seen.add(c.article);
      return true;
    });
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function ConversationHistory() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(
    searchParams.get("thread")
  );
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    getHistory({ limit: 100 })
      .then((r) => setItems(r.items))
      .catch(console.error)
      .finally(() => setIsLoading(false));
  }, []);

  const allThreads = useMemo(() => groupIntoThreads(items), [items]);

  const filteredThreads = useMemo(() => {
    if (!searchQuery.trim()) return allThreads;
    const q = searchQuery.toLowerCase();
    return allThreads.filter(
      (t) =>
        t.title.toLowerCase().includes(q) ||
        t.items.some(
          (item) =>
            item.question.toLowerCase().includes(q) ||
            item.answer.toLowerCase().includes(q)
        )
    );
  }, [allThreads, searchQuery]);

  // 첫 스레드 자동 선택
  useEffect(() => {
    if (filteredThreads.length > 0 && !selectedThreadId) {
      setSelectedThreadId(filteredThreads[0].threadId);
    }
  }, [filteredThreads, selectedThreadId]);

  const dateGroups = useMemo(() => groupThreadsByDate(filteredThreads), [filteredThreads]);
  const selectedThread = allThreads.find((t) => t.threadId === selectedThreadId) ?? null;

  const handleContinue = () => {
    if (!selectedThread) return;

    const messages: ChatMessage[] = selectedThread.items.flatMap((item, idx) => [
      {
        id: `hist-user-${idx}-${item.id}`,
        role: "user" as const,
        content: item.question,
      },
      {
        id: `hist-ai-${idx}-${item.id}`,
        role: "assistant" as const,
        content: "",
        qa_id: item.id,
        answerData: {
          summary: item.answer,
          citations: sourcesToChatCitations(item),
          references: [],
          isIrrelevant: item.law_context_status === "irrelevant",
          lawContextStatus: item.law_context_status,
          lawFilterActive: false,
        },
      },
    ]);

    sessionStorage.setItem(
      "las_resume_session",
      JSON.stringify({ session_id: selectedThread.session_id, messages })
    );
    router.push("/chat");
  };

  return (
    <SidebarProvider>
      <div className="flex h-screen w-full overflow-hidden">
        <AppSidebar />

        <div className="flex flex-1 overflow-hidden">
          {/* ── 왼쪽: 대화 목록 ── */}
          <div className="flex w-[260px] shrink-0 flex-col border-r border-border bg-card">
            <div className="flex h-10 shrink-0 items-center border-b border-border px-2 gap-2">
              <SidebarTrigger />
              <div className="h-4 w-px bg-border" />
              <span className="text-sm font-medium text-muted-foreground">대화 내역</span>
            </div>

            {/* 검색 */}
            <div className="border-b border-border px-3 py-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/50" />
                <Input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="대화 검색..."
                  className="h-7 border-0 bg-muted/40 pl-8 text-xs focus-visible:ring-1"
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto py-1 [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
              {isLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : filteredThreads.length === 0 ? (
                <p className="px-4 py-10 text-center text-sm text-muted-foreground">
                  {searchQuery ? "검색 결과가 없습니다." : "대화 내역이 없습니다."}
                </p>
              ) : (
                dateGroups.map(({ label, threads }) => (
                  <div key={label} className="mb-1">
                    <p className="px-3 pb-1 pt-3 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground/50">
                      {label}
                    </p>
                    {threads.map((thread) => {
                      const active = selectedThreadId === thread.threadId;
                      return (
                        <button
                          key={thread.threadId}
                          type="button"
                          onClick={() => setSelectedThreadId(thread.threadId)}
                          className={cn(
                            "relative w-full px-3 py-2.5 text-left transition-colors",
                            active
                              ? "bg-primary/10 text-primary"
                              : "text-foreground hover:bg-secondary/60"
                          )}
                        >
                          {active && (
                            <span className="absolute bottom-2 left-0 top-2 w-[3px] rounded-r bg-primary" />
                          )}
                          <p className="line-clamp-1 text-[13px] font-medium leading-snug">
                            {thread.title}
                          </p>
                          <p
                            className={cn(
                              "mt-0.5 text-[11px]",
                              active ? "text-primary/60" : "text-muted-foreground"
                            )}
                          >
                            {thread.items.length > 1 && (
                              <span className="mr-1">{thread.items.length}개 질문 ·</span>
                            )}
                            {format(new Date(thread.lastDate), "M월 d일 HH:mm", { locale: ko })}
                          </p>
                        </button>
                      );
                    })}
                  </div>
                ))
              )}
            </div>
          </div>

          {/* ── 오른쪽: 대화 상세 ── */}
          <div className="flex flex-1 flex-col overflow-hidden">
            {selectedThread ? (
              <>
                {/* 상단 타이틀 바 */}
                <div className="flex shrink-0 items-start justify-between gap-4 border-b border-border bg-card px-6 py-3">
                  <div className="min-w-0">
                    <p className="line-clamp-1 text-sm font-semibold text-foreground">
                      {selectedThread.title}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {format(
                        new Date(selectedThread.items[0].created_at),
                        "yyyy년 M월 d일 HH:mm",
                        { locale: ko }
                      )}
                      {selectedThread.items.length > 1 &&
                        ` · ${selectedThread.items.length}개 질문`}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleContinue}
                    className="h-8 shrink-0 gap-1.5 text-xs"
                  >
                    <SquarePen className="h-3.5 w-3.5" />
                    이어서 질문하기
                  </Button>
                </div>

                {/* 메시지 영역 */}
                <div className="flex-1 overflow-y-auto px-6 py-8">
                  <div className="space-y-8">
                    {selectedThread.items.map((item, idx) => (
                      <div key={item.id} className="space-y-4">
                        {idx > 0 && <div className="h-px bg-border/40" />}

                        {/* 사용자 메시지 */}
                        <div className="flex justify-end">
                          <div className="max-w-[72%] rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground">
                            {item.question}
                          </div>
                        </div>

                        {/* AI 답변 */}
                        <div className="flex gap-3">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
                            <Scale className="h-4 w-4 text-primary" />
                          </div>
                          <div className="min-w-0 flex-1 space-y-2.5">
                            <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3 text-sm leading-relaxed text-foreground">
                              <SimpleMarkdown>{item.answer}</SimpleMarkdown>
                            </div>

                            {(() => {
                              const citations = deriveCitations(item);
                              if (citations.length === 0) return null;
                              return (
                                <div className="flex flex-wrap items-center gap-1.5 px-1">
                                  <Scale className="h-3 w-3 shrink-0 text-muted-foreground" />
                                  {citations.slice(0, 5).map((c, i) => (
                                    <Badge key={i} variant="outline" className="text-xs font-normal">
                                      {c}
                                    </Badge>
                                  ))}
                                  {citations.length > 5 && (
                                    <span className="text-xs text-muted-foreground">
                                      +{citations.length - 5}개
                                    </span>
                                  )}
                                </div>
                              );
                            })()}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center gap-3">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted">
                  <MessageSquare className="h-6 w-6 text-muted-foreground/40" />
                </div>
                <p className="text-sm text-muted-foreground">대화를 선택하세요</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
}
