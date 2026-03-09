import { FileText, BookOpen, ExternalLink } from "lucide-react";

interface AnswerCardProps {
  data: {
    summary: string;
    detail: string;
    citations: { article: string; content: string }[];
    references: string[];
  };
}

export function AnswerCard({ data }: AnswerCardProps) {
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

      {/* 상세 설명 */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">상세 설명</div>
        <p className="text-sm leading-relaxed text-foreground">{data.detail}</p>
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
              <p className="text-xs leading-relaxed text-legal-citation-foreground">{c.content}</p>
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
    </div>
  );
}
