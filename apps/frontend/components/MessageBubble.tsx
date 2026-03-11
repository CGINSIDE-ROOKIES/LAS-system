import { User, Bot } from "lucide-react";
import { AnswerCard } from "./AnswerCard";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  answerData?: {
    summary: string;
    detail: string;
    citations: { article: string; content: string }[];
    references: string[];
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
            {message.content && (
              <p className="mt-2 text-sm text-foreground">{message.content}</p>
            )}
          </div>
        ) : message.answerData ? (
          <AnswerCard data={message.answerData} />
        ) : (
          <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-foreground">
            {message.content}
          </div>
        )}
      </div>
    </div>
  );
}
