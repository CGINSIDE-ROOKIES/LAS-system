import { useState, useRef, useEffect, useCallback } from "react";
import { QuestionInput } from "./QuestionInput";
import { MessageBubble, ChatMessage } from "./MessageBubble";
import { Button } from "@/components/ui/button";
import { askStream } from "@/lib/api-client";
import { QA_STREAM_TIMEOUT_MS, sseErrorMessage, streamTransportErrorMessage } from "@/lib/errors";
import { SquarePen } from "lucide-react";

export type Citation = {
  article: string;  // e.g. "근로기준법 제17조"
  content: string;
  lawName: string;  // e.g. "근로기준법"
};

interface ChatContainerProps {
  onCitationsChange?: (citations: Citation[]) => void;
}

const STORAGE_KEY = "las_chat_messages";

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

export function ChatContainer({ onCitationsChange }: ChatContainerProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const abortRef = useRef<AbortController | null>(null);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    const stored = loadMessages();
    if (stored.length > 0) setMessages(stored);
  }, []);

  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  useEffect(() => {
    if (messages.length === 0) return;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {
      // sessionStorage 용량 초과 등 무시
    }
  }, [messages]);

  const streamAnswer = useCallback(async (userQuestion: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const timeoutId = setTimeout(() => controller.abort("timeout"), QA_STREAM_TIMEOUT_MS);
    const t0 = performance.now();

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: userQuestion,
    };
    const aiId = (Date.now() + 1).toString();
    const aiMsg: ChatMessage = { id: aiId, role: "assistant", content: "", isStreaming: true };

    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setIsStreaming(true);

    console.log("[LAS:QA] 질문 전송:", userQuestion.slice(0, 80));
    try {
      let lawFilter: string[] | undefined;
      try {
        const raw = localStorage.getItem("las_law_filter");
        const parsed = raw ? JSON.parse(raw) : [];
        if (Array.isArray(parsed) && parsed.length > 0) lawFilter = parsed;
      } catch {}

      for await (const event of askStream({ question: userQuestion, law_filter: lawFilter }, controller.signal)) {
        if (event.type === "chunk") {
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
          const parsedCitations: Citation[] = event.retrieved_docs
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
            .filter((c): c is Citation => c !== null);

          console.log(
            `[LAS:QA] 스트림 완료: ${((performance.now() - t0) / 1000).toFixed(2)}s | docs=${event.retrieved_docs.length} | law_context_status=${event.law_context_status}`
          );
          onCitationsChange?.(parsedCitations);

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
                      summary: m.content,
                      citations: parsedCitations,
                      references: [],
                      isIrrelevant: event.law_context_status === "irrelevant",
                      lawContextStatus: event.law_context_status,
                      lawFilterActive: !!lawFilter,
                    },
                  }
                : m
            )
          );
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
  }, [scrollToBottom]);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    sessionStorage.removeItem(STORAGE_KEY);
    onCitationsChange?.([]);
  }, [onCitationsChange]);

  const hasMessages = messages.length > 0;

  if (!hasMessages) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-6">
        <div className="w-full max-w-2xl">
          {/* Logo / Title */}
          <div className="mb-8 text-center">
            {/* Icon with glow ring */}
            <div className="animate-in fade-in slide-in-from-bottom-4 duration-700 fill-mode-both mx-auto mb-6 relative w-fit">
              <div className="absolute inset-0 rounded-2xl bg-primary/20 blur-xl scale-150" />
              <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/20 shadow-lg">
                <svg className="h-8 w-8 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
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
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex h-10 shrink-0 items-center justify-end border-b border-border px-4">
        <Button variant="ghost" size="sm" onClick={handleNewChat} disabled={isStreaming}>
          <SquarePen className="mr-1.5 h-3.5 w-3.5" />
          새 대화
        </Button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin px-6 py-4">
        <div className="space-y-4">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-border px-6 py-4">
        <QuestionInput onSubmit={streamAnswer} disabled={isStreaming} />
      </div>
    </div>
  );
}
