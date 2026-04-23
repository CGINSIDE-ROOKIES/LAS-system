import { useState } from "react";
import { SimpleMarkdown } from "./SimpleMarkdown";
import { FileText, BookOpen, ExternalLink, ThumbsUp, ThumbsDown, ChevronDown, FilterX, Scale } from "lucide-react";
import { renderMarkdown } from "@/lib/render-markdown";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { submitFeedback } from "@/lib/api-client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useSettings } from "@/hooks/useSettings";

const CITATIONS_DEFAULT_SHOW = 3;

function CitationsBlock({ citations }: { citations: { article: string; content: string }[] }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? citations : citations.slice(0, CITATIONS_DEFAULT_SHOW);
  const hasMore = citations.length > CITATIONS_DEFAULT_SHOW;

  return (
    <Collapsible defaultOpen>
      <div className="rounded-lg border-2 border-legal-citation-border bg-legal-citation p-4">
        <CollapsibleTrigger className="flex w-full items-center justify-between mb-1">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-primary">
            <BookOpen className="h-3.5 w-3.5" />
            근거 조문
          </div>
          <ChevronDown className="h-3.5 w-3.5 text-primary transition-transform duration-200 [[data-state=open]_&]:rotate-180" />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-2 mt-3">
            {shown.map((c, i) => (
              <div key={i} className="rounded-md border border-border bg-card p-3">
                <div className="mb-1 text-xs font-semibold text-primary">{c.article}</div>
                <p className="text-xs leading-relaxed text-legal-citation-foreground whitespace-pre-wrap line-clamp-6">{c.content}</p>
              </div>
            ))}
            {hasMore && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="w-full pt-1 text-xs text-muted-foreground hover:text-primary transition-colors"
              >
                {expanded ? "접기" : `+${citations.length - CITATIONS_DEFAULT_SHOW}개 더 보기`}
              </button>
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

interface AnswerCardProps {
  data: {
    summary: string;
    citations: { article: string; content: string }[];
    references: string[];
    isIrrelevant?: boolean;
    lawContextStatus?: string;
    lawFilterActive?: boolean;
  };
  qaId?: string;
}

export function AnswerCard({ data, qaId }: AnswerCardProps) {
  const [thumbsUp, setThumbsUp] = useState<boolean | null>(null);
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);
  const { showCitations } = useSettings();

  const handleFeedback = async (value: boolean) => {
    if (thumbsUp === value) return;
    setThumbsUp(value);
    setShowComment(!value);
    try {
      await submitFeedback(qaId!, { thumbs_up: value });
      if (value) toast.success("피드백이 제출되었습니다.");
    } catch {
      toast.error("피드백 제출에 실패했습니다.");
    }
  };

  const handleCommentSubmit = async () => {
    try {
      await submitFeedback(qaId!, { thumbs_up: false, comment: comment || undefined });
      setShowComment(false);
      toast.success("의견이 제출되었습니다. 감사합니다.");
    } catch {
      toast.error("피드백 제출에 실패했습니다.");
    }
  };
  const showFilterHint = data.lawContextStatus === "missing" && data.lawFilterActive;
  const showCaseOnlyHint = data.lawContextStatus === "case_only";

  const handleClearFilter = () => {
    try { localStorage.removeItem("las_law_filter"); } catch {}
    window.dispatchEvent(new Event("las_law_filter_cleared"));
  };

  return (
    <div className="space-y-3">
      {/* 판례 전용 안내 */}
      {showCaseOnlyHint && (
        <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2.5 text-xs text-blue-800">
          <Scale className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>법령 조문 없이 판례·해석례 기반으로 답변합니다. 조문 근거가 필요하다면 더 구체적으로 질문해보세요.</span>
        </div>
      )}

      {/* 법령 필터 힌트 */}
      {showFilterHint && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
          <FilterX className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            선택한 법령 범위에서 관련 정보를 찾지 못했습니다.{" "}
            <button
              type="button"
              className="underline underline-offset-2 hover:text-amber-900"
              onClick={handleClearFilter}
            >
              필터를 해제
            </button>
            하고 다시 질문해보세요.
          </span>
        </div>
      )}
      {/* 답변 요약 */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-primary">
          <FileText className="h-3.5 w-3.5" />
          답변 요약
        </div>
        <SimpleMarkdown>{data.summary}</SimpleMarkdown>
      </div>

      {/* 근거 조문 */}
      {showCitations && !data.isIrrelevant && data.citations.length > 0 && (
        <CitationsBlock citations={data.citations} />
      )}

      {/* 관련 문서 */}
      {data.references.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">관련 문서 · 참고 자료</div>
          <ul className="space-y-1">
            {data.references.map((ref, i) => (
              <li key={i} className="flex items-center gap-2 text-xs text-muted-foreground hover:text-primary cursor-pointer">
                <ExternalLink className="h-3 w-3 shrink-0" />
                {ref}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 피드백 */}
      {qaId && (
        <div className="space-y-2">
          <div className="flex items-center gap-0.5 px-1">
            <span className="text-[10px] text-muted-foreground">이 답변이 도움이 되었나요?</span>
            <Button
              variant="ghost"
              size="sm"
              className={cn("h-4 px-1", thumbsUp === true && "text-green-600 bg-green-50 hover:bg-green-50")}
              onClick={() => handleFeedback(true)}
            >
              <ThumbsUp className="h-2 w-2" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className={cn("h-4 px-1", thumbsUp === false && "text-red-500 bg-red-50 hover:bg-red-50")}
              onClick={() => handleFeedback(false)}
            >
              <ThumbsDown className="h-2 w-2" />
            </Button>
          </div>
          {showComment && (
            <div className="flex flex-col gap-1.5 px-1 w-1/3">
              <Textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="어떤 점이 아쉬웠나요? (선택)"
                className="min-h-[60px] resize-none rounded-xl text-xs"
              />
              <div className="flex gap-1">
                <Button size="sm" className="h-7 text-xs" onClick={handleCommentSubmit}>
                  제출
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs text-muted-foreground"
                  onClick={() => setShowComment(false)}
                >
                  닫기
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
