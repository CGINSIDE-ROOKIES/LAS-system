import { useState } from "react";
import { FileText, BookOpen, ExternalLink, ThumbsUp, ThumbsDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { submitFeedback } from "@/lib/api-client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface AnswerCardProps {
  data: {
    summary: string;
    citations: { article: string; content: string }[];
    references: string[];
  };
  qaId?: string;
}

export function AnswerCard({ data, qaId }: AnswerCardProps) {
  const [thumbsUp, setThumbsUp] = useState<boolean | null>(null);
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);

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
  return (
    <div className="space-y-3">
      {/* 답변 요약 */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-primary">
          <FileText className="h-3.5 w-3.5" />
          답변 요약
        </div>
        <p className="text-sm font-medium leading-relaxed text-foreground">{data.summary}</p>
      </div>

      {/* 근거 조문 */}
      <div className="rounded-lg border-2 border-legal-citation-border bg-legal-citation p-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-primary">
          <BookOpen className="h-3.5 w-3.5" />
          근거 조문
        </div>
        <div className="space-y-2">
          {data.citations.map((c, i) => (
            <div key={i} className="rounded-md border border-border bg-card p-3">
              <div className="mb-1 text-xs font-semibold text-primary">{c.article}</div>
              <p className="text-xs leading-relaxed text-legal-citation-foreground whitespace-pre-wrap line-clamp-6">{c.content}</p>
            </div>
          ))}
        </div>
      </div>

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
          <Separator />
          <div className="flex items-center gap-1.5 px-1">
            <span className="text-xs text-muted-foreground">이 답변이 도움이 되었나요?</span>
            <Button
              variant="ghost"
              size="sm"
              className={cn("h-7 px-2", thumbsUp === true && "text-green-600 bg-green-50 hover:bg-green-50")}
              onClick={() => handleFeedback(true)}
            >
              <ThumbsUp className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className={cn("h-7 px-2", thumbsUp === false && "text-red-500 bg-red-50 hover:bg-red-50")}
              onClick={() => handleFeedback(false)}
            >
              <ThumbsDown className="h-3.5 w-3.5" />
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
