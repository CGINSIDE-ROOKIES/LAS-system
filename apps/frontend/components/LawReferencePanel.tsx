import { ChevronDown, BookOpen } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useState } from "react";

const lawArticles = [
  {
    law: "근로기준법",
    articles: [
      { number: "제17조", title: "근로조건의 명시", summary: "사용자는 근로계약 체결 시 임금, 소정근로시간, 휴일, 연차 유급휴가에 관한 사항을 명시해야 함." },
      { number: "제50조", title: "근로시간", summary: "1주 간의 근로시간은 휴게시간을 제외하고 40시간을 초과할 수 없음." },
      { number: "제56조", title: "연장·야간 및 휴일 근로", summary: "연장근로에 대해서는 통상임금의 100분의 50 이상을 가산하여 지급해야 함." },
      { number: "제114조", title: "벌칙", summary: "제17조를 위반한 자는 500만원 이하의 벌금에 처한다." },
    ],
  },
  {
    law: "하도급거래 공정화에 관한 법률",
    articles: [
      { number: "제3조", title: "서면의 발급 및 서류의 보존", summary: "원사업자는 수급사업자에게 제조등의 위탁을 하는 경우 서면을 발급해야 함." },
      { number: "제13조", title: "하도급대금의 지급", summary: "원사업자는 수급사업자에게 목적물 수령일로부터 60일 이내에 하도급대금을 지급해야 함." },
    ],
  },
];

export function LawReferencePanel() {
  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">관련 법령</h2>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-3">
        {lawArticles.map((law) => (
          <LawGroup key={law.law} law={law} />
        ))}
      </div>
    </div>
  );
}

function LawGroup({ law }: { law: typeof lawArticles[0] }) {
  const [open, setOpen] = useState(true);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-left text-xs font-semibold text-foreground hover:bg-secondary transition-colors">
        <span>{law.law}</span>
        <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2 space-y-2">
          {law.articles.map((article) => (
            <div
              key={article.number}
              className="rounded-md border border-border bg-card p-3 transition-colors hover:border-primary/30"
            >
              <div className="flex items-baseline gap-2">
                <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                  {article.number}
                </span>
                <span className="text-xs font-medium text-foreground">{article.title}</span>
              </div>
              <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">{article.summary}</p>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
