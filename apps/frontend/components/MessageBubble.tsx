import { useState, useRef, useEffect } from "react";
import { User, Bot } from "lucide-react";
import { AnswerCard } from "./AnswerCard";

/** 받은 텍스트를 한 글자씩 드립해서 타이핑 효과를 만드는 컴포넌트 */
function TypewriterText({ text }: { text: string }) {
  const [displayed, setDisplayed] = useState("");
  const indexRef = useRef(0);

  useEffect(() => {
    // 이미 따라잡은 경우 아무것도 안 함
    if (indexRef.current >= text.length) return;

    const id = setInterval(() => {
      const remaining = text.length - indexRef.current;
      if (remaining <= 0) { clearInterval(id); return; }
      // 백로그가 많으면 step 올려서 스트림에 따라잡기
      const step = remaining > 80 ? 4 : remaining > 20 ? 2 : 1;
      indexRef.current = Math.min(indexRef.current + step, text.length);
      setDisplayed(text.slice(0, indexRef.current));
    }, 16);

    return () => clearInterval(id);
  }, [text]);

  return (
    <>
      {displayed}
      <span className="animate-cursor-blink ml-px font-light text-primary">|</span>
    </>
  );
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  statusMessage?: string;
  qa_id?: string;
  answerData?: {
    summary: string;
    citations: { article: string; content: string }[];
    references: string[];
    isIrrelevant?: boolean;
    lawContextStatus?: string;
    lawFilterActive?: boolean;
  };
}

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end gap-3">
        <div className="max-w-[70%] rounded-lg bg-primary px-4 py-3 text-sm text-primary-foreground">
          {message.content}
        </div>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary">
          <User className="h-4 w-4 text-secondary-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
        <Bot className="h-4 w-4 text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        {message.isStreaming && !message.answerData ? (
          <div className="rounded-lg border border-border bg-card px-4 py-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>답변 생성 중</span>
              <span className="flex gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse-dot" style={{ animationDelay: "0s" }} />
                <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse-dot" style={{ animationDelay: "0.2s" }} />
                <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse-dot" style={{ animationDelay: "0.4s" }} />
              </span>
            </div>
            {message.statusMessage && (
              <p className="mt-2 text-sm text-muted-foreground">{message.statusMessage}</p>
            )}
            {message.content && (
              <p className="mt-2 text-sm text-foreground whitespace-pre-line">
                <TypewriterText text={message.content} />
              </p>
            )}
          </div>
        ) : message.answerData ? (
          <AnswerCard data={message.answerData} qaId={message.qa_id} />
        ) : (
          <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-foreground">
            {message.content}
          </div>
        )}
      </div>
    </div>
  );
}
