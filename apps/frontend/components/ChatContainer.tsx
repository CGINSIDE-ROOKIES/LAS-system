import { useState, useRef, useEffect, useCallback } from "react";
import { QuestionInput } from "./QuestionInput";
import { MessageBubble, ChatMessage } from "./MessageBubble";
import { askStream } from "@/lib/api-client";
import { ERROR_MESSAGES } from "@/lib/errors";

export function ChatContainer() {
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
    return () => { abortRef.current?.abort(); };
  }, []);

  const streamAnswer = useCallback(async (userQuestion: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const timeoutId = setTimeout(() => controller.abort("timeout"), 60_000);

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: userQuestion,
    };
    const aiId = (Date.now() + 1).toString();
    const aiMsg: ChatMessage = { id: aiId, role: "assistant", content: "", isStreaming: true };

    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setIsStreaming(true);

    try {
      for await (const event of askStream({ question: userQuestion }, controller.signal)) {
        if (event.type === "chunk") {
          setMessages((prev) =>
            prev.map((m) => m.id === aiId ? { ...m, content: m.content + event.content } : m)
          );
          scrollToBottom();
        } else if (event.type === "done") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiId
                ? {
                    ...m,
                    content: "",
                    isStreaming: false,
                    answerData: {
                      summary: m.content,
                      detail: "",
                      citations: (event.retrieved_docs
                        .filter((doc) => doc.doc_type === "law")
                        .map((doc) => {
                          // source_id: law::{law_name}::{article_no}::{chunk}
                          const parts = (doc.source_id || "").split("::");
                          let articleNo = parts[2] ?? "";
                          // source_id에 조문 번호 없으면 텍스트의 "조문번호:" 필드에서 추출
                          if (!articleNo) {
                            const noMatch = (doc.text || doc.snippet).match(/조문번호:\s*(제?\d[\d조의]*)/);
                            if (noMatch) articleNo = noMatch[1].replace(/^제/, "").replace(/조$/, "");
                          }
                          const articleLabel = articleNo
                            ? `${doc.law_name} 제${articleNo}조`
                            : doc.law_name;

                          // text(전체) 또는 snippet에서 메타데이터 헤더 제거
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
                            // 조문제목 없는 경우: "법령명: X 조문번호: N " 앞부분 제거
                            const stripped = raw.replace(/^법령명:[^\n]*조문번호:[^\n]*\s*/i, "").trim();
                            content = stripped;
                          }
                          // 적재 시 중복 패턴 제거
                          content = content
                            // [['a', 'b', 'c']] 형태의 Python list 직렬화 → 줄바꿈 텍스트로
                            .replace(/\[\[([\s\S]*?)\]\]/g, (_, inner) =>
                              inner
                                .split(/,\s*'/)
                                .map((s: string) => s.replace(/^'|'$/g, "").trim())
                                .filter(Boolean)
                                .join("\n")
                            )
                            // ① ①→①, 1. 1.→1.
                            .replace(/([\u2460-\u2473\u2474-\u2487①-⑳])\s+\1/g, "$1")
                            .replace(/(\d+\.)\s+\1/g, "$1")
                            .trim();

                          // 실질 내용 없는 항목(장/절 제목만 있는 경우) 제외
                          if (content.length < 20) return null;

                          return { article: articleLabel, content };
                        }).filter((c): c is { article: string; content: string } => c !== null)),
                      references: [],
                    },
                  }
                : m
            )
          );
        } else if (event.type === "error") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === aiId ? { ...m, isStreaming: false, content: event.error } : m
            )
          );
        }
      }
    } catch (err) {
      const error = err as Error;
      if (error.name === "AbortError" && error.message !== "timeout") return;

      const errorContent =
        error.message === "timeout"
          ? ERROR_MESSAGES.TIMEOUT
          : error.name === "TypeError"
          ? ERROR_MESSAGES.NETWORK
          : ERROR_MESSAGES.SERVER;

      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiId ? { ...m, isStreaming: false, content: errorContent } : m
        )
      );
    } finally {
      clearTimeout(timeoutId);
      setIsStreaming(false);
    }
  }, [scrollToBottom]);

  const hasMessages = messages.length > 0;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="shrink-0 border-b border-border px-6 py-4">
        <h1 className="text-lg font-semibold text-foreground">법령 Q&A</h1>
        <p className="text-sm text-muted-foreground">
          노동법 및 하도급법 관련 질문에 대해 근거 기반 답변을 제공합니다.
        </p>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin px-6 py-4">
        {!hasMessages && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
                <svg className="h-6 w-6 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
                </svg>
              </div>
              <h3 className="text-sm font-medium text-foreground">법률 질문을 입력해주세요</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                노동법, 하도급법 관련 질문에 대해 근거 조문과 함께 답변합니다.
              </p>
            </div>
          </div>
        )}
        {hasMessages && (
          <div className="space-y-4">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="shrink-0 border-t border-border px-6 py-4">
        <QuestionInput onSubmit={streamAnswer} disabled={isStreaming} />
      </div>
    </div>
  );
}
