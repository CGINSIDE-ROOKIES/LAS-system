import type { GraphEdge, GraphNode } from "@/lib/graph-types";

interface GraphNodeDetailPanelProps {
  node: GraphNode;
  edges: GraphEdge[];
  nodes: GraphNode[];
  onClose?: () => void;
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

function formatParagraphNo(raw: string): string {
  const n = parseInt(raw, 10);
  if (!isNaN(n)) return `제${n}항`;
  return raw.startsWith("제") ? raw : `제${raw}항`;
}

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

export function GraphNodeDetailPanel({ node, edges, nodes, onClose }: GraphNodeDetailPanelProps) {
  const connectedEdges = edges.filter(
    (e) => e.source === node.id || e.target === node.id
  );

  const refEdgesWithParagraphs = connectedEdges.filter(
    (e) => e.relationType === "reference" && e.paragraphNos?.length
  );

  return (
    <div className="shrink-0 border-t border-border max-h-[45%] flex flex-col">
      {/* 고정 헤더: 배지 + 닫기 버튼 */}
      <div className="shrink-0 bg-muted/30 px-4 pt-3 pb-1.5 flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 flex-wrap">
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
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            aria-label="닫기"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="1" y1="1" x2="11" y2="11" />
              <line x1="11" y1="1" x2="1" y2="11" />
            </svg>
          </button>
        )}
      </div>

      {/* 스크롤 가능한 콘텐츠 */}
      <div className="flex-1 overflow-y-auto scrollbar-thin bg-muted/30 px-4 pb-3">
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
                    {formatParagraphNo(p)}
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
    </div>
  );
}
