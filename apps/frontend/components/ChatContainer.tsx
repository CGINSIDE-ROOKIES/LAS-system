import { useState, useRef, useEffect, useCallback } from "react";
import { QuestionInput } from "./QuestionInput";
import { MessageBubble, ChatMessage } from "./MessageBubble";
import { Button } from "@/components/ui/button";
import { askStream, getSuggestions, type RetrievedDoc } from "@/lib/api-client";
import { QA_STREAM_TIMEOUT_MS, sseErrorMessage, streamTransportErrorMessage } from "@/lib/errors";
import { SquarePen, Scale, ChevronLeft, ChevronRight } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { cn } from "@/lib/utils";
import { useSettings } from "@/hooks/useSettings";

const QUESTION_POOL = [
  // 근로계약서 작성
  "근로계약서에 꼭 들어가야 하는 항목은 무엇인가요?",
  "수습 근로자에게도 최저임금이 적용되나요?",
  "연장근로 수당은 어떻게 계산해야 하나요?",
  // 해고·계약 종료 리스크
  "해고 시 사전 통지가 필요하지 않은 예외가 있나요?",
  "기간제 근로계약을 갱신하지 않을 때 주의할 점은?",
  "해고예고가 적용되지 않는 경우는 무엇인가요?",
  "기간제 계약 종료 시 유의사항은?",
  // 근로시간·임금 설계
  "연장근로 기준은?",
  "휴일근로 수당 기준은?",
  "성과급도 퇴직금에 포함되나요?",
  // 파견·도급 리스크
  "도급 계약에서 불법파견이 되는 경우는?",
  "도급이 파견으로 판단되는 기준은?",
  "파견이 허용되는 업무 범위는 어디까지인가요?",
  // 하도급 계약
  "하도급 계약서 필수 기재 내용은?",
  "하도급 대금 감액 금지 예외는?",
  "하도급법 위반 시 손해배상 책임 범위는?",
  "기술자료 요구가 금지되는 경우는?",
];

function pickRandom<T>(arr: T[], n: number): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy.slice(0, n);
}

function ScrollableChips({
  questions,
  onSelect,
  disabled = false,
  loading = false,
  className,
}: {
  questions: string[];
  onSelect: (q: string) => void;
  disabled?: boolean;
  loading?: boolean;
  className?: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const update = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setIsOverflowing(el.scrollWidth > el.clientWidth + 1);
    setCanScrollLeft(el.scrollLeft > 1);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    el.addEventListener("scroll", update, { passive: true });
    return () => { ro.disconnect(); el.removeEventListener("scroll", update); };
  }, [update]);

  const scrollTo = (dir: "left" | "right") => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollBy({ left: dir === "left" ? -(el.clientWidth * 0.6) : el.clientWidth * 0.6, behavior: "smooth" });
  };

  if (loading) {
    return (
      <div className={cn("flex items-center justify-center gap-2 py-1", className)}>
        {["w-28", "w-32", "w-24", "w-28"].map((w, i) => (
          <div key={i} className={cn("h-7 animate-pulse rounded-full bg-muted", w)} />
        ))}
      </div>
    );
  }

  return (
    <div className={cn("flex items-center", className)}>
      <button
        type="button"
        onClick={() => scrollTo("left")}
        tabIndex={canScrollLeft ? 0 : -1}
        aria-hidden={!canScrollLeft}
        className={cn(
          "shrink-0 rounded-full p-1 text-muted-foreground transition-all hover:bg-accent hover:text-foreground",
          !canScrollLeft && "invisible"
        )}
      >
        <ChevronLeft className="h-4 w-4" />
      </button>

      <div
        ref={scrollRef}
        className={cn(
          "flex flex-1 flex-nowrap gap-2 overflow-x-scroll py-0.5 [&::-webkit-scrollbar]:hidden [scrollbar-width:none]",
          !isOverflowing && "justify-center"
        )}
      >
        {questions.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onSelect(q)}
            disabled={disabled}
            className="shrink-0 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-[0_0_10px_rgba(186,230,253,0.25),0_2px_6px_rgba(0,0,0,0.04)] transition-all hover:-translate-y-0.5 hover:shadow-[0_0_14px_rgba(186,230,253,0.4),0_4px_8px_rgba(0,0,0,0.05)] hover:border-primary hover:text-primary disabled:opacity-50 first:ml-3 last:mr-3"
          >
            {q}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={() => scrollTo("right")}
        tabIndex={canScrollRight ? 0 : -1}
        aria-hidden={!canScrollRight}
        className={cn(
          "shrink-0 rounded-full p-1 text-muted-foreground transition-all hover:bg-accent hover:text-foreground",
          !canScrollRight && "invisible"
        )}
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}

export type Citation = {
  article: string;  // e.g. "근로기준법 제17조"
  content: string;
  lawName: string;  // e.g. "근로기준법"
};

interface ChatContainerProps {
  onCitationsChange?: (citations: Citation[]) => void;
  onQuestionSubmit?: (question: string) => void;
  onNewChat?: () => void;
}

const STORAGE_KEY = "las_chat_messages";
const SUGGESTIONS_KEY = "las_chat_suggestions";

function loadMessages(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: ChatMessage[] = JSON.parse(raw);
    return parsed.map((m) =>
      m.isStreaming
        ? {
            ...m,
            isStreaming: false,
            statusMessage: undefined,
            content: m.content || "응답이 중단되었습니다.",
          }
        : m
    );
  } catch {
    return [];
  }
}

function parseCitations(retrievedDocs: RetrievedDoc[]): Citation[] {
  return retrievedDocs
    .filter((doc) => doc.doc_type === "law")
    .map((doc) => {
      let articleLabel: string;
      if (doc.article_no) {
        articleLabel = `${doc.law_name} ${doc.article_no}`;
      } else {
        const noMatch = (doc.text || doc.snippet).match(/조문번호:\s*(제?\d[\d조의]*)/);
        if (noMatch) {
          const extracted = noMatch[1];
          articleLabel = extracted.startsWith("제")
            ? `${doc.law_name} ${extracted}`
            : `${doc.law_name} 제${extracted}조`;
        } else {
          articleLabel = doc.law_name;
        }
      }

      const raw = doc.text || doc.snippet;
      let content = raw;
      const metaIdx = raw.indexOf("조문제목:");
      if (metaIdx !== -1) {
        const afterMeta = raw.slice(metaIdx + "조문제목:".length);
        const contentMatch = afterMeta.match(/제\d/);
        if (contentMatch?.index !== undefined) {
          content = afterMeta.slice(contentMatch.index).trim();
        }
      } else {
        const stripped = raw.replace(/^법령명:[^\n]*조문번호:[^\n]*\s*/i, "").trim();
        content = stripped;
      }
      content = content
        .replace(/\[\[([\s\S]*?)\]\]/g, (_, inner) =>
          inner
            .split(/,\s*'/)
            .map((s: string) => s.replace(/^'|'$/g, "").trim())
            .filter(Boolean)
            .join("\n")
        )
        .replace(/([\u2460-\u2473\u2474-\u2487①-⑳])\s+\1/g, "$1")
        .replace(/(\d+\.)\s+\1/g, "$1")
        .trim();

      if (content.length < 20) return null;
      return { article: articleLabel, content, lawName: doc.law_name };
    })
    .filter((c): c is Citation => c !== null)
    .filter((c, idx, arr) => arr.findIndex((x) => x.article === c.article) === idx);
}

type FollowUpContext = { question: string; answer: string };

export function ChatContainer({ onCitationsChange, onQuestionSubmit, onNewChat }: ChatContainerProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [suggestions, setSuggestions] = useState<string[] | null>(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [defaultQuestions, setDefaultQuestions] = useState(() => QUESTION_POOL.slice(0, 4));
  useEffect(() => { setDefaultQuestions(pickRandom(QUESTION_POOL, 4)); }, []);
  const scrollRef = useRef<HTMLDivElement>(null);
  const settings = useSettings();

  const abortRef = useRef<AbortController | null>(null);
  const followUpContextRef = useRef<FollowUpContext | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const suggestionsGenRef = useRef(0);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    const raw = sessionStorage.getItem("las_followup_context");
    if (raw) {
      try {
        const ctx: FollowUpContext = JSON.parse(raw);
        sessionStorage.removeItem("las_followup_context");
        sessionStorage.removeItem(STORAGE_KEY);
        sessionStorage.removeItem(SUGGESTIONS_KEY);
        followUpContextRef.current = ctx;
        setMessages([
          { id: "followup-prev-q", role: "user", content: ctx.question, isFollowUpContext: true },
          {
            id: "followup-prev-a",
            role: "assistant",
            content: "",
            isFollowUpContext: true,
            answerData: {
              summary: ctx.answer,
              citations: [],
              references: [],
              isIrrelevant: false,
              lawContextStatus: "ok",
              lawFilterActive: false,
            },
          },
        ]);
      } catch {
        const stored = loadMessages();
        if (stored.length > 0) setMessages(stored);
      }
    } else {
      const stored = loadMessages();
      if (stored.length === 0) return;
      setMessages(stored);
      // 마지막 답변의 citations 복원
      const lastAnswer = [...stored].reverse().find(
        (m) => m.role === "assistant" && m.answerData?.citations?.length
      );
      if (lastAnswer?.answerData?.citations) {
        onCitationsChange?.(lastAnswer.answerData.citations as unknown as Citation[]);
      }
      // suggestions 복원
      try {
        const rawSugs = sessionStorage.getItem(SUGGESTIONS_KEY);
        if (rawSugs) {
          const parsed = JSON.parse(rawSugs);
          if (Array.isArray(parsed) && parsed.length > 0) setSuggestions(parsed);
        }
      } catch {}
    }
  }, []);

  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  useEffect(() => {
    messagesRef.current = messages;
    if (messages.length === 0) return;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {
      // sessionStorage 용량 초과 등 무시
    }
  }, [messages]);

  const streamAnswer = useCallback(async (userQuestion: string) => {
    onQuestionSubmit?.(userQuestion);
    let prevCtx: FollowUpContext | null = null;
    if (followUpContextRef.current) {
      prevCtx = followUpContextRef.current;
      followUpContextRef.current = null;
    } else {
      const msgs = messagesRef.current;
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = msgs[i];
        if (m.role === "assistant" && m.answerData?.summary && !m.isFollowUpContext) {
          const prevUser = msgs.slice(0, i).reverse().find((u) => u.role === "user" && !u.isFollowUpContext);
          if (prevUser) prevCtx = { question: prevUser.content, answer: m.answerData.summary };
          break;
        }
      }
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const t0 = performance.now();

    setSuggestions(null);
    setSuggestionsLoading(false);
    const sugGen = ++suggestionsGenRef.current;
    let accumulatedContent = "";

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: userQuestion,
    };
    const aiId = (Date.now() + 1).toString();
    const aiMsg: ChatMessage = { id: aiId, role: "assistant", content: "", isStreaming: true };

    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setIsStreaming(true);

    let lawFilter: string[] | undefined;
    try {
      const raw = localStorage.getItem("las_law_filter");
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed) && parsed.length > 0) lawFilter = parsed;
    } catch {}

    const request = {
      question: userQuestion,
      law_filter: lawFilter,
      answer_detail: settings.answerDetail,
      top_k: settings.topK,
      ...(prevCtx && {
        previous_question: prevCtx.question,
        previous_answer: prevCtx.answer,
      }),
    };

    console.log("[LAS:QA] 질문 전송:", userQuestion.slice(0, 80));

    const timeoutId = setTimeout(() => controller.abort("timeout"), QA_STREAM_TIMEOUT_MS);
    try {
      for await (const event of askStream(request, controller.signal)) {
        if (event.type === "chunk") {
          accumulatedContent += event.content;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiId
                ? { ...m, statusMessage: undefined, content: m.content + event.content }
                : m
            )
          );
          scrollToBottom();
        } else if (event.type === "status") {
          console.info("[LAS:QA] 상태:", event.code, event.message);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiId ? { ...m, statusMessage: event.message } : m
            )
          );
        } else if (event.type === "done") {
          const citations = parseCitations(event.retrieved_docs);

          console.log(
            `[LAS:QA] 스트림 완료: ${((performance.now() - t0) / 1000).toFixed(2)}s | docs=${event.retrieved_docs.length} | law_context_status=${event.law_context_status}`
          );
          onCitationsChange?.(citations);

          const answerText = accumulatedContent
            .replace(/\n?\[ANSWERABLE:[^\]]+\]\s*$/i, "").trimEnd();

          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiId
                ? {
                    ...m,
                    content: "",
                    isStreaming: false,
                    statusMessage: undefined,
                    qa_id: event.qa_id ?? undefined,
                    answerData: {
                      summary: m.content.replace(/\n?\[ANSWERABLE:[^\]]+\]\s*$/i, "").trimEnd(),
                      citations,
                      references: [],
                      isIrrelevant: event.law_context_status === "irrelevant",
                      lawContextStatus: event.law_context_status,
                      lawFilterActive: !!lawFilter,
                    },
                  }
                : m
            )
          );

          const isIrrelevant = event.law_context_status === "irrelevant";
          const isUnanswerable = /\[ANSWERABLE:no\]/i.test(accumulatedContent);
          if (isIrrelevant || isUnanswerable) return;

          setSuggestionsLoading(true);
          getSuggestions({ question: userQuestion, answer: answerText })
            .then((sugs) => {
              if (suggestionsGenRef.current !== sugGen) return;
              const next = sugs.length > 0 ? sugs : null;
              setSuggestions(next);
              try {
                if (next) sessionStorage.setItem(SUGGESTIONS_KEY, JSON.stringify(next));
                else sessionStorage.removeItem(SUGGESTIONS_KEY);
              } catch {}
            })
            .finally(() => {
              if (suggestionsGenRef.current === sugGen) setSuggestionsLoading(false);
            });
        } else if (event.type === "error") {
          console.error("[LAS:QA] SSE 에러:", event.code, event.error);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiId
                ? {
                    ...m,
                    isStreaming: false,
                    statusMessage: undefined,
                    content: sseErrorMessage(event.code),
                  }
                : m
            )
          );
        }
      }
    } catch (err) {
      const errorContent = streamTransportErrorMessage(err);
      if (errorContent === null) return;
      console.error("[LAS:QA] 스트림 예외:", err);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiId
            ? { ...m, isStreaming: false, statusMessage: undefined, content: errorContent }
            : m
        )
      );
    } finally {
      clearTimeout(timeoutId);
      setIsStreaming(false);
    }
  }, [scrollToBottom, settings, onQuestionSubmit]);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    sessionStorage.removeItem(STORAGE_KEY);
    onCitationsChange?.([]);
    setSuggestions(null);
    setSuggestionsLoading(false);
    sessionStorage.removeItem(SUGGESTIONS_KEY);
    onNewChat?.();
  }, [onCitationsChange, onNewChat]);

  const hasMessages = messages.length > 0;

  return (
    <div className="flex h-full flex-col">
      {/* 통합 헤더 — 항상 표시 */}
      <div className="flex h-10 shrink-0 items-center border-b border-border px-2">
        <SidebarTrigger />
        {hasMessages && (
          <div className="ml-auto">
            <Button variant="ghost" size="sm" onClick={handleNewChat} disabled={isStreaming}>
              <SquarePen className="mr-1.5 h-3.5 w-3.5" />
              새 대화
            </Button>
          </div>
        )}
      </div>

      {!hasMessages ? (
        <div className="flex flex-1 flex-col items-center justify-center px-6">
          <div className="w-full max-w-3xl">
            {/* Logo / Title */}
            <div className="mb-8 text-center">
              {/* Icon with glow ring */}
              <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 fill-mode-both mx-auto mb-6 relative w-fit">
                <div className="absolute inset-0 rounded-2xl bg-primary/20 blur-xl scale-150" />
                <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/20 shadow-lg">
                  <Scale className="h-8 w-8 text-primary" />
                </div>
              </div>

              {/* Title */}
              <h1
                className="animate-in fade-in slide-in-from-bottom-4 duration-700 fill-mode-both text-3xl font-bold bg-gradient-to-r from-foreground to-foreground/60 bg-clip-text text-transparent"
                style={{ animationDelay: "120ms" }}
              >
                무엇이 궁금하신가요?
              </h1>

              {/* Subtitle */}
              <p
                className="animate-in fade-in slide-in-from-bottom-4 duration-700 fill-mode-both mt-3 text-sm text-muted-foreground leading-relaxed"
                style={{ animationDelay: "220ms" }}
              >
                노동법 및 하도급법 관련 질문에 대해
                <br />
                근거 조문과 판례를 함께 제공합니다.
              </p>
            </div>

            {/* Input */}
            <div
              className="animate-in fade-in slide-in-from-bottom-4 duration-700 fill-mode-both"
              style={{ animationDelay: "340ms" }}
            >
              <QuestionInput onSubmit={streamAnswer} disabled={isStreaming} />
            </div>
          </div>

          {/* 추천 질문 칩 */}
          {settings.showFollowUpQuestions && (
            <div
              className="animate-in fade-in slide-in-from-bottom-4 duration-700 fill-mode-both mt-3 w-full max-w-4xl"
              style={{ animationDelay: "440ms" }}
            >
              <ScrollableChips
                questions={suggestions ?? defaultQuestions}
                onSelect={streamAnswer}
                disabled={isStreaming}
                loading={suggestionsLoading}
              />
            </div>
          )}
        </div>
      ) : (
        <>
          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin px-6 py-4">
            <div className="space-y-4">
              {messages.map((msg, idx) => (
                <div key={msg.id}>
                  {idx > 0 && !msg.isFollowUpContext && messages[idx - 1]?.isFollowUpContext && (
                    <div className="mb-4 h-px bg-border/50" />
                  )}
                  <MessageBubble message={msg} />
                </div>
              ))}
            </div>
          </div>

          {/* 선 → 칩 → 입력창 */}
          <div className="shrink-0 border-t border-border px-6 py-4 space-y-3">
            {settings.showFollowUpQuestions && (!isStreaming || suggestionsLoading) && (
              <ScrollableChips
                questions={suggestions ?? defaultQuestions}
                onSelect={streamAnswer}
                loading={suggestionsLoading}
              />
            )}
            <div className="mx-auto w-full max-w-3xl">
              <QuestionInput onSubmit={streamAnswer} disabled={isStreaming} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
