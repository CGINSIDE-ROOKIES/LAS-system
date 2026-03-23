import { useState, useRef, useEffect, useCallback } from "react";
import { QuestionInput } from "./QuestionInput";
import { MessageBubble, ChatMessage } from "./MessageBubble";
import { askStream } from "@/lib/api-client";

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
                      citations: event.retrieved_docs.map((doc) => ({
                        article: doc.law_name,
                        content: doc.snippet,
                      })),
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
      if ((err as Error).name === "AbortError") return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiId ? { ...m, isStreaming: false, content: "서버 오류가 발생했습니다." } : m
        )
      );
    } finally {
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
