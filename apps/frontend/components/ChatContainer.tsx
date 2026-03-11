import { useState, useRef, useEffect, useCallback } from "react";
import { QuestionInput } from "./QuestionInput";
import { MessageBubble, ChatMessage } from "./MessageBubble";

const mockAnswer = {
  summary:
    "근로기준법 제17조에 따르면 근로계약서에는 임금, 소정근로시간, 휴일, 연차유급휴가 등의 사항을 반드시 명시해야 합니다.",
  detail:
    "사용자는 근로계약 체결 시 근로자에게 임금의 구성항목·계산방법·지급방법, 소정근로시간, 제55조에 따른 휴일, 제60조에 따른 연차 유급휴가에 관한 사항을 명시하여야 합니다. 또한 근로기준법 시행령에서 정하는 바에 따라 취업의 장소와 종사하여야 할 업무에 관한 사항도 포함되어야 합니다. 이를 위반할 경우 500만원 이하의 벌금에 처할 수 있습니다.",
  citations: [
    {
      article: "근로기준법 제17조 (근로조건의 명시)",
      content:
        "① 사용자는 근로계약을 체결할 때에 근로자에게 다음 각 호의 사항을 명시하여야 한다. 근로계약 후 다음 각 호의 사항을 변경하는 경우에도 또한 같다.\n1. 임금\n2. 소정근로시간\n3. 제55조에 따른 휴일\n4. 제60조에 따른 연차 유급휴가",
    },
    {
      article: "근로기준법 제114조 (벌칙)",
      content:
        "다음 각 호의 어느 하나에 해당하는 자는 500만원 이하의 벌금에 처한다. 1. 제17조를 위반한 자",
    },
  ],
  references: [
    "고용노동부 - 표준근로계약서 서식 가이드",
    "대법원 2019다12345 판결 요지",
    "근로기준법 시행령 제8조",
  ],
};

export function ChatContainer() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const simulateStream = (userQuestion: string) => {
    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: userQuestion,
    };

    const aiId = (Date.now() + 1).toString();
    const aiMsg: ChatMessage = {
      id: aiId,
      role: "assistant",
      content: "",
      isStreaming: true,
    };

    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setIsStreaming(true);

    // Simulate streaming text
    const streamText = mockAnswer.summary;
    let index = 0;

    const interval = setInterval(() => {
      index += 2;
      if (index >= streamText.length) {
        clearInterval(interval);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiId
              ? { ...m, content: "", isStreaming: false, answerData: mockAnswer }
              : m
          )
        );
        setIsStreaming(false);
      } else {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aiId ? { ...m, content: streamText.slice(0, index) } : m
          )
        );
      }
    }, 30);
  };

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
        <QuestionInput onSubmit={simulateStream} disabled={isStreaming} />
      </div>
    </div>
  );
}
