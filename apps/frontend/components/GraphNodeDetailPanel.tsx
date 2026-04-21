import type { GraphNode } from "@/lib/graph-types";

interface GraphNodeDetailPanelProps {
  node: GraphNode;
}

const KIND_LABEL: Record<string, string> = {
  law: "법령",
  article: "조문",
};

export function GraphNodeDetailPanel({ node }: GraphNodeDetailPanelProps) {
  return (
    <div className="shrink-0 border-t border-border bg-muted/30 px-4 py-3">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
          {KIND_LABEL[node.kind] ?? node.kind}
        </span>
        {node.isCenter && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            중심 노드
          </span>
        )}
      </div>
      {node.lawName && (
        <p className="text-xs font-semibold text-foreground">{node.lawName}</p>
      )}
      {node.articleNo && (
        <p className="mt-0.5 text-xs text-muted-foreground">{node.articleNo}</p>
      )}
    </div>
  );
}
