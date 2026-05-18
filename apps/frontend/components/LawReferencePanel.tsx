import { ChevronDown, BookOpen } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useState } from "react";
import type { Citation } from "./ChatContainer";

interface LawReferencePanelProps {
  citations: Citation[];
}

export function LawReferencePanel({ citations }: LawReferencePanelProps) {
  // law_name 기준으로 그룹핑
  const groups = citations.reduce<Record<string, Citation[]>>((acc, c) => {
    (acc[c.lawName] ??= []).push(c);
    return acc;
  }, {});

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">관련 법령</h2>
          {citations.length > 0 && (
            <span className="ml-auto rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
              {citations.length}
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-3">
        {citations.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
              <BookOpen className="h-5 w-5 text-muted-foreground/50" />
            </div>
            <p className="text-center text-[13.5px] text-muted-foreground leading-relaxed">
              질문을 입력하면<br />관련 법령 조문이 표시됩니다.
            </p>
          </div>
        ) : (
          Object.entries(groups).map(([lawName, items]) => (
            <LawGroup key={lawName} lawName={lawName} citations={items} />
          ))
        )}
      </div>
    </div>
  );
}

function LawGroup({ lawName, citations }: { lawName: string; citations: Citation[] }) {
  const [open, setOpen] = useState(true);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-left text-xs font-semibold text-foreground hover:bg-secondary transition-colors">
        <span>{lawName}</span>
        <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2 space-y-2">
          {citations.filter((c, idx, arr) => arr.findIndex((x) => x.article === c.article) === idx).map((c) => (
            <div
              key={c.article}
              className="rounded-md border border-border bg-card p-3 transition-colors hover:border-primary/30"
            >
              <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                {c.article.replace(lawName, "").trim() || c.article}
              </span>
              <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground whitespace-pre-wrap">{c.content}</p>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
