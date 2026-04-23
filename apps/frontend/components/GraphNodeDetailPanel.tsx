import type { GraphEdge, GraphNode } from "@/lib/graph-types";

interface GraphNodeDetailPanelProps {
  node: GraphNode;
  edges: GraphEdge[];
  nodes: GraphNode[];
}

const KIND_LABEL: Record<string, string> = {
  law: "법령",
  article: "조문",
};

const RELATION_LABEL: Record<string, string> = {
  child_law: "하위법령",
  delegation: "위임",
  reference: "참조",
  structure: "구조",
};

function edgeCounterpartLabel(e: GraphEdge, nodeId: string, nodes: GraphNode[]): string {
  const otherId = e.source === nodeId ? e.target : e.source;
  const other = nodes.find((n) => n.id === otherId);
  if (!other) return e.detail ?? "";
  const direction = e.source === nodeId ? "→" : "←";
  const name = other.articleNo
    ? `${other.lawName ?? ""} ${other.articleNo}`.trim()
    : (other.lawName ?? other.label);
  return `${direction} ${name}`;
}

export function GraphNodeDetailPanel({ node, edges, nodes }: GraphNodeDetailPanelProps) {
  const connectedEdges = edges.filter(
    (e) => e.source === node.id || e.target === node.id
  );

  const refEdgesWithParagraphs = connectedEdges.filter(
    (e) => e.relationType === "reference" && e.paragraphNos?.length
  );

  return (
    <div className="shrink-0 border-t border-border bg-muted/30 px-4 py-3">
      {/* 종류 배지 행 */}
      <div className="mb-1.5 flex items-center gap-1.5 flex-wrap">
        <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
          {KIND_LABEL[node.kind] ?? node.kind}
        </span>
        {node.kind === "law" && node.lawType && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground border border-border">
            {node.lawType}
          </span>
        )}
        {node.isCenter && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            중심 노드
          </span>
        )}
      </div>

      {/* 법령명 */}
      {node.lawName && (
        <p className="text-xs font-semibold text-foreground">{node.lawName}</p>
      )}

      {/* 조문번호 */}
      {node.articleNo && (
        <p className="mt-0.5 text-xs text-muted-foreground">{node.articleNo}</p>
      )}

      {/* 참조 항 정보 */}
      {refEdgesWithParagraphs.length > 0 && (
        <div className="mt-2 border-t border-border/60 pt-2">
          <p className="text-[10px] font-medium text-muted-foreground mb-1">참조 항</p>
          {refEdgesWithParagraphs.map((e) => (
            <div key={e.id} className="flex flex-wrap gap-1">
              {e.paragraphNos!.map((p) => (
                <span
                  key={p}
                  className="rounded bg-primary/8 px-1.5 py-0.5 text-[10px] text-primary"
                >
                  {p}
                </span>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* 연결 관계 목록 */}
      {connectedEdges.length > 0 && (
        <div className="mt-2 border-t border-border/60 pt-2">
          <p className="text-[10px] font-medium text-muted-foreground mb-1">연결 관계</p>
          <div className="flex flex-col gap-0.5">
            {connectedEdges.map((e) => (
              <div key={e.id} className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <span className="rounded bg-muted px-1 py-0.5 text-[9px] font-medium shrink-0">
                  {RELATION_LABEL[e.relationType] ?? e.relationType}
                </span>
                <span className="truncate">{edgeCounterpartLabel(e, node.id, nodes)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
