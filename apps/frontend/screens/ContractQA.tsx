import { useState, useRef, useEffect, useCallback } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  Send,
  Copy,
  Bookmark,
  MessageSquarePlus,
  ExternalLink,
  Scale,
  FileText,
  BookOpen,
  Loader2,
  User,
  Bot,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { askStream, RetrievedDoc as ApiDoc } from "@/lib/api-client";
import { ERROR_MESSAGES } from "@/lib/errors";
import Link from "next/link";

// Types
type SourceType = "contract" | "law" | "precedent" | "interpretation";
type AnswerBasis = "both" | "contract" | "law";

interface Source {
  id: string;
  type: SourceType;
  title: string;
  excerpt: string;
  article?: string;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  sources?: Source[];
  followUps?: string[];
  isStreaming?: boolean;
}

// Source badge config
const sourceTypeConfig: Record<SourceType, { label: string; icon: typeof FileText; className: string }> = {
  contract: { label: "계약서", icon: FileText, className: "border-primary/30 bg-primary/5 text-primary" },
  law: { label: "법령", icon: Scale, className: "border-accent-foreground/20 bg-accent/50 text-accent-foreground" },
  precedent: { label: "판례", icon: BookOpen, className: "border-muted-foreground/20 bg-muted text-muted-foreground" },
  interpretation: { label: "해석례", icon: ExternalLink, className: "border-secondary-foreground/20 bg-secondary text-secondary-foreground" },
};

const DOC_TYPE_MAP: Record<string, SourceType> = {
  contract: "contract",
  law: "law",
  precedent: "precedent",
  interpretation: "interpretation",
};

function mapDocToSource(doc: ApiDoc): Source {
  return {
    id: doc.source_id,
    type: DOC_TYPE_MAP[doc.doc_type] ?? "law",
    title: doc.law_name,
    excerpt: doc.snippet,
    article: doc.article_no ? `제${doc.article_no}조` : undefined,
  };
}

const initialMessages: ChatMessage[] = [
  {
    id: "m1",
    role: "assistant",
    content: "업로드하신 **소프트웨어 개발 용역 하도급 계약서**를 분석할 준비가 되었습니다.\n\n계약서 내용에 대해 궁금한 점을 질문해주세요. 계약 조항, 관련 법률, 판례 등을 기반으로 답변드리겠습니다.",
    timestamp: new Date("2024-01-16T14:35:00"),
    followUps: [
      "이 계약서에서 가장 위험한 조항은 무엇인가요?",
      "대금 지급 조건이 적법한지 검토해주세요.",
      "손해배상 조항이 과도하지 않은지 확인해주세요.",
      "지식재산권 귀속 조항에 문제가 있나요?",
    ],
  },
];

const ContractQA = () => {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [answerBasis, setAnswerBasis] = useState<AnswerBasis>("both");
  const [activeSourceId, setActiveSourceId] = useState<string | null>(null);
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const sourceRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const abortRef = useRef<AbortController | null>(null);

  const scrollToBottom = useCallback(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  const streamAnswer = useCallback(async (question: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const timeoutId = setTimeout(() => controller.abort("timeout"), 60_000);

    const assistantId = `m${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "", timestamp: new Date(), isStreaming: true },
    ]);

    try {
      for await (const event of askStream({ question }, controller.signal)) {
        if (event.type === "chunk") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + event.content } : m
            )
          );
          scrollToBottom();
        } else if (event.type === "done") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, isStreaming: false, sources: event.retrieved_docs.map(mapDocToSource) }
                : m
            )
          );
          setActiveMessageId(assistantId);
        } else if (event.type === "error") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, isStreaming: false, content: m.content || `오류가 발생했습니다: ${event.error}` }
                : m
            )
          );
          toast.error(event.error);
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
          m.id === assistantId
            ? { ...m, isStreaming: false, content: m.content || errorContent }
            : m
        )
      );
      toast.error(errorContent);
    } finally {
      clearTimeout(timeoutId);
      setIsStreaming(false);
    }
  }, [scrollToBottom]);

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    const userMsg: ChatMessage = {
      id: `m${Date.now()}-u`,
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);

    await streamAnswer(trimmed);
  }, [input, isStreaming, streamAnswer]);

  const handleFollowUp = useCallback((question: string) => {
    setInput(question);
  }, []);

  const handleCopy = useCallback((text: string) => {
    navigator.clipboard.writeText(text);
    toast.success("클립보드에 복사되었습니다.");
  }, []);

  const handleSave = useCallback(() => {
    toast.success("Q&A가 저장되었습니다.");
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const scrollToSource = useCallback((sourceId: string) => {
    setActiveSourceId(sourceId);
    const el = sourceRefs.current.get(sourceId);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  const setSourceRef = useCallback((id: string, el: HTMLDivElement | null) => {
    if (el) sourceRefs.current.set(id, el);
  }, []);

  // Get sources for active message
  const activeSources = messages.find((m) => m.id === activeMessageId)?.sources || [];
  const filteredSources = activeSources.filter((s) => {
    if (answerBasis === "contract") return s.type === "contract";
    if (answerBasis === "law") return s.type !== "contract";
    return true;
  });

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <div className="flex flex-1 flex-col">
          <header className="flex h-10 items-center justify-between border-b border-border px-2">
            <SidebarTrigger />
            <div className="flex items-center gap-2 pr-2">
              <Badge variant="outline" className="text-xs">
                <FileText className="mr-1 h-3 w-3" />
                소프트웨어 개발 용역 하도급 계약서
              </Badge>
              <Link href="/contract-review/result">
                <Button variant="ghost" size="sm" className="text-xs">
                  전체 검토 결과
                  <ExternalLink className="ml-1 h-3 w-3" />
                </Button>
              </Link>
            </div>
          </header>

          {/* Two-column layout */}
          <div className="flex flex-1 overflow-hidden">
            {/* Left: Chat Panel */}
            <div className="flex flex-1 flex-col border-r border-border">
              {/* Chat messages */}
              <ScrollArea className="flex-1">
                <div className="space-y-4 p-4">
                  {messages.map((msg) => (
                    <div key={msg.id} className={cn("flex gap-3", msg.role === "user" && "flex-row-reverse")}>
                      {/* Avatar */}
                      <div className={cn(
                        "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                        msg.role === "user" ? "bg-primary" : "bg-muted"
                      )}>
                        {msg.role === "user"
                          ? <User className="h-4 w-4 text-primary-foreground" />
                          : <Bot className="h-4 w-4 text-muted-foreground" />
                        }
                      </div>

                      {/* Message content */}
                      <div className={cn("max-w-[85%] space-y-2", msg.role === "user" && "items-end")}>
                        <Card className={cn(
                          msg.role === "user"
                            ? "bg-primary text-primary-foreground"
                            : "bg-card"
                        )}>
                          <CardContent className="p-3">
                            <div className={cn(
                              "whitespace-pre-wrap text-sm leading-relaxed",
                              msg.role === "assistant" && "prose-sm"
                            )}>
                              {msg.content.split(/(\*\*.*?\*\*|### .*?\n)/g).map((part, idx) => {
                                if (part.startsWith("**") && part.endsWith("**")) {
                                  return <strong key={idx}>{part.slice(2, -2)}</strong>;
                                }
                                if (part.startsWith("### ")) {
                                  return <h4 key={idx} className="mb-1 mt-3 text-sm font-semibold">{part.slice(4).trim()}</h4>;
                                }
                                return <span key={idx}>{part}</span>;
                              })}
                              {msg.isStreaming && (
                                <span className="ml-1 inline-block h-4 w-1.5 animate-pulse bg-primary" />
                              )}
                            </div>
                          </CardContent>
                        </Card>

                        {/* Source badges for assistant */}
                        {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 px-1">
                            {msg.sources.map((source) => {
                              const config = sourceTypeConfig[source.type];
                              const Icon = config.icon;
                              return (
                                <Badge
                                  key={source.id}
                                  variant="outline"
                                  className={cn(
                                    "cursor-pointer text-[10px] transition-all hover:opacity-80",
                                    config.className,
                                    activeSourceId === source.id && "ring-1 ring-primary"
                                  )}
                                  onClick={() => {
                                    setActiveMessageId(msg.id);
                                    scrollToSource(source.id);
                                  }}
                                >
                                  <Icon className="mr-0.5 h-2.5 w-2.5" />
                                  {config.label}: {source.title} {source.article || ""}
                                </Badge>
                              );
                            })}
                          </div>
                        )}

                        {/* Actions for assistant */}
                        {msg.role === "assistant" && !msg.isStreaming && msg.content && (
                          <div className="flex items-center gap-1 px-1">
                            <Button variant="ghost" size="sm" className="h-6 text-[10px] text-muted-foreground" onClick={() => handleCopy(msg.content)}>
                              <Copy className="mr-0.5 h-3 w-3" /> 복사
                            </Button>
                            <Button variant="ghost" size="sm" className="h-6 text-[10px] text-muted-foreground" onClick={handleSave}>
                              <Bookmark className="mr-0.5 h-3 w-3" /> 저장
                            </Button>
                          </div>
                        )}

                        {/* Follow-up suggestions */}
                        {msg.role === "assistant" && msg.followUps && msg.followUps.length > 0 && !msg.isStreaming && (
                          <div className="space-y-1 px-1 pt-1">
                            <p className="text-[10px] font-medium text-muted-foreground">추가 질문</p>
                            <div className="flex flex-col gap-1">
                              {msg.followUps.map((q, idx) => (
                                <Button
                                  key={idx}
                                  variant="outline"
                                  size="sm"
                                  className="h-auto justify-start whitespace-normal px-2 py-1.5 text-left text-xs"
                                  onClick={() => handleFollowUp(q)}
                                >
                                  <MessageSquarePlus className="mr-1.5 h-3 w-3 shrink-0" />
                                  {q}
                                </Button>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}

                  {isStreaming && messages[messages.length - 1]?.content === "" && (
                    <div className="flex items-center gap-2 px-11 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      답변을 생성하고 있습니다...
                    </div>
                  )}

                  <div ref={chatEndRef} />
                </div>
              </ScrollArea>

              {/* Input Area */}
              <div className="border-t border-border bg-card p-4">
                <div className="flex items-end gap-2">
                  <div className="flex-1">
                    <Textarea
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={handleKeyDown}
                      placeholder="계약서에 대해 질문하세요..."
                      className="min-h-[44px] max-h-[120px] resize-none"
                      rows={1}
                      disabled={isStreaming}
                    />
                  </div>
                  <Button onClick={handleSend} disabled={isStreaming || !input.trim()} size="icon" className="shrink-0">
                    {isStreaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
            </div>

            {/* Right: Source Panel */}
            <div className="hidden w-[380px] shrink-0 flex-col lg:flex">
              {/* Panel Header */}
              <div className="flex items-center justify-between border-b border-border px-4 py-2">
                <h3 className="text-sm font-semibold text-foreground">근거 자료</h3>
                <Select value={answerBasis} onValueChange={(v) => setAnswerBasis(v as AnswerBasis)}>
                  <SelectTrigger className="h-7 w-[130px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="both">전체 근거</SelectItem>
                    <SelectItem value="contract">계약서만</SelectItem>
                    <SelectItem value="law">법령만</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Sources List */}
              <ScrollArea className="flex-1">
                <div className="space-y-3 p-4">
                  {filteredSources.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-12 text-center">
                      <FileText className="h-10 w-10 text-muted-foreground/30" />
                      <p className="mt-3 text-sm text-muted-foreground">
                        {activeMessageId ? "선택한 필터에 해당하는 근거가 없습니다." : "질문을 입력하면 관련 근거가 여기에 표시됩니다."}
                      </p>
                    </div>
                  ) : (
                    filteredSources.map((source) => {
                      const config = sourceTypeConfig[source.type];
                      const Icon = config.icon;
                      return (
                        <div
                          key={source.id}
                          ref={(el) => setSourceRef(source.id, el)}
                          className={cn(
                            "rounded-lg border p-3 transition-all",
                            activeSourceId === source.id
                              ? "border-primary ring-1 ring-primary/20"
                              : "border-border"
                          )}
                        >
                          <div className="flex items-start gap-2">
                            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted">
                              <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                            </div>
                            <div className="flex-1 space-y-1.5">
                              <div className="flex items-center gap-2">
                                <Badge variant="outline" className={cn("text-[10px]", config.className)}>
                                  {config.label}
                                </Badge>
                                <span className="text-xs font-medium text-foreground">
                                  {source.title}
                                  {source.article && ` ${source.article}`}
                                </span>
                              </div>
                              <div className="rounded-md bg-muted/50 px-2.5 py-2 text-xs leading-relaxed text-muted-foreground">
                                {source.excerpt}
                              </div>
                              {source.type === "contract" && (
                                <Link href="/contract-review/result">
                                  <Button variant="ghost" size="sm" className="h-6 p-0 text-[10px] text-primary">
                                    원문에서 보기
                                    <ChevronRight className="ml-0.5 h-3 w-3" />
                                  </Button>
                                </Link>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </ScrollArea>

              {/* Related contract info */}
              <div className="border-t border-border p-4">
                <div className="rounded-lg bg-muted/50 p-3">
                  <p className="text-xs font-medium text-foreground">현재 분석 중인 계약서</p>
                  <p className="mt-1 text-xs text-muted-foreground">소프트웨어 개발 용역 하도급 계약서</p>
                  <div className="mt-2 flex items-center gap-2">
                    <Badge variant="secondary" className="text-[10px]">하도급 계약서</Badge>
                    <Badge variant="secondary" className="text-[10px]">10개 조항</Badge>
                  </div>
                  <Link href="/contract-review/result" className="mt-2 block">
                    <Button variant="outline" size="sm" className="w-full text-xs">
                      <ExternalLink className="mr-1 h-3 w-3" />
                      전체 검토 결과 보기
                    </Button>
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default ContractQA;
