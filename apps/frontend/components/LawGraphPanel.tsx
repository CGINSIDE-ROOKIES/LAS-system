import { useEffect, useRef, useState } from "react";
import { Network as NetworkIcon, Loader2, AlertCircle, BarChart3 } from "lucide-react";
import { DataSet } from "vis-data";
import { Network } from "vis-network";
import type { Options } from "vis-network";
import { queryGraph } from "@/lib/api-client";
import { toGraphData } from "@/lib/graph-adapter";
import type { GraphNode, LawGraphData } from "@/lib/graph-types";

interface LawGraphPanelProps {
  lastQuery: string;
  queryKey: number;
  isActive: boolean;
  onNodeSelect: (node: GraphNode | null) => void;
  onGraphDataChange?: (data: LawGraphData | null) => void;
}

type PanelState = "idle" | "loading" | "success" | "empty" | "plan_failed" | "error";

const VIS_OPTIONS: Options = {
  nodes: {
    shape: "dot",
    font: { size: 12, face: "system-ui, sans-serif" },
    borderWidth: 1.5,
    chosen: true,
  },
  edges: {
    arrows: { to: { enabled: true, scaleFactor: 0.6 } },
    color: { color: "hsl(220, 16%, 75%)", highlight: "hsl(217, 91%, 50%)" },
    font: { size: 10, align: "middle" },
    smooth: { enabled: true, type: "curvedCW", roundness: 0.2 },
  },
  interaction: {
    hover: true,
    tooltipDelay: 200,
    navigationButtons: false,
    keyboard: false,
  },
  physics: {
    enabled: true,
    barnesHut: {
      gravitationalConstant: -3000,
      centralGravity: 0.4,
      springLength: 120,
      springConstant: 0.05,
      damping: 0.4,
    },
    stabilization: { iterations: 150, fit: true },
  },
};

function lawNodeColor(lawType: string | undefined) {
  switch (lawType) {
    case "시행령":
      return { background: "hsl(217, 75%, 86%)", border: "hsl(217, 55%, 65%)", highlight: { background: "hsl(217, 75%, 79%)", border: "hsl(217, 55%, 55%)" } };
    case "시행규칙":
      return { background: "hsl(217, 55%, 82%)", border: "hsl(217, 40%, 62%)", highlight: { background: "hsl(217, 55%, 75%)", border: "hsl(217, 40%, 52%)" } };
    case "법":
    default:
      return { background: "hsl(217, 91%, 92%)", border: "hsl(217, 60%, 70%)", highlight: { background: "hsl(217, 91%, 85%)", border: "hsl(217, 60%, 60%)" } };
  }
}

function buildVisDatasets(graphData: LawGraphData) {
  const visNodes = graphData.nodes.map((n) => ({
    id: n.id,
    label: n.label,
    size: n.isCenter ? 28 : 18,
    color: n.isCenter
      ? { background: "hsl(217, 91%, 50%)", border: "hsl(217, 91%, 40%)", highlight: { background: "hsl(217, 91%, 45%)", border: "hsl(217, 91%, 35%)" } }
      : n.kind === "law"
        ? lawNodeColor(n.lawType)
        : { background: "hsl(142, 71%, 93%)", border: "hsl(142, 60%, 65%)", highlight: { background: "hsl(142, 71%, 86%)", border: "hsl(142, 60%, 55%)" } },
    font: { color: n.isCenter ? "hsl(217, 91%, 30%)" : "hsl(220, 30%, 20%)", size: n.isCenter ? 13 : 12 },
  }));

  const visEdges = graphData.edges.map((e) => ({
    id: e.id,
    from: e.source,
    to: e.target,
    label: e.relationType === "child_law"
      ? "하위"
      : e.relationType === "delegation"
        ? "위임"
        : e.relationType === "reference"
          ? (e.paragraphNos?.length ? `참조 · 제${parseInt(e.paragraphNos[0], 10) || e.paragraphNos[0]}항` : "참조")
          : "",
  }));

  return {
    nodes: new DataSet(visNodes),
    edges: new DataSet(visEdges),
  };
}

export function LawGraphPanel({ lastQuery, queryKey, isActive, onNodeSelect, onGraphDataChange }: LawGraphPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const [state, setState] = useState<PanelState>("idle");
  const [graphData, setGraphData] = useState<LawGraphData | null>(null);
  const lastSuccessKey = useRef<number>(-1);  // 성공한 queryKey만 기록
  const requestToken = useRef<number>(0);     // 요청 순서 토큰
  const abortRef = useRef<AbortController | null>(null);

  // 그래프 탭 활성화 + 새 질문(queryKey 변경)이 있을 때 API 호출
  useEffect(() => {
    if (!isActive || !lastQuery || queryKey === lastSuccessKey.current) return;

    // 이전 요청 중단
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const token = ++requestToken.current;

    setState("loading");
    setGraphData(null);
    onGraphDataChange?.(null);
    onNodeSelect(null);

    queryGraph(lastQuery, controller.signal)
      .then((resp) => {
        if (token !== requestToken.current || controller.signal.aborted) return;
        const data = toGraphData(resp);
        if (!data) {
          setState("empty");
          return;
        }
        lastSuccessKey.current = queryKey;  // 성공 시에만 기록
        setGraphData(data);
        onGraphDataChange?.(data);
        setState("success");
      })
      .catch((err) => {
        if (token !== requestToken.current || controller.signal.aborted) return;
        if (err?.code === "GRAPH_PLAN_FAILED") {
          setState("plan_failed");
        } else {
          setState("error");
        }
      });

    return () => { controller.abort(); };
  }, [isActive, queryKey, lastQuery, onNodeSelect]);

  // graphData가 바뀔 때 vis-network 렌더링
  useEffect(() => {
    if (!containerRef.current || !graphData) return;

    networkRef.current?.destroy();

    const { nodes, edges } = buildVisDatasets(graphData);
    const network = new Network(containerRef.current, { nodes, edges }, VIS_OPTIONS);
    networkRef.current = network;

    network.on("click", (params) => {
      if (params.nodes.length === 0) {
        onNodeSelect(null);
        return;
      }
      const nodeId = params.nodes[0] as string;
      const found = graphData.nodes.find((n) => n.id === nodeId) ?? null;
      onNodeSelect(found);
    });

    return () => {
      network.destroy();
      networkRef.current = null;
    };
  }, [graphData, onNodeSelect]);

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <NetworkIcon className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">법령 관계 그래프</h2>
          {state === "loading" && (
            <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-muted-foreground" />
          )}
        </div>
      </div>

      <div className="relative flex-1 overflow-hidden">
        {/* vis-network 컨테이너 — success일 때만 표시 */}
        <div
          ref={containerRef}
          className="absolute inset-0"
          style={{ display: state === "success" ? "block" : "none" }}
        />

        {/* 상태별 안내 메시지 */}
        {state !== "success" && (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
            {state === "idle" && (
              <>
                <BarChart3 className="h-8 w-8 text-muted-foreground/40" />
                <p className="text-xs text-muted-foreground">
                  질문을 입력하면 법령 구조 그래프가 표시됩니다
                </p>
              </>
            )}
            {state === "loading" && (
              <>
                <Loader2 className="h-6 w-6 animate-spin text-primary/60" />
                <p className="text-xs text-muted-foreground">그래프 조회 중...</p>
              </>
            )}
            {state === "plan_failed" && (
              <>
                <AlertCircle className="h-6 w-6 text-amber-500/70" />
                <p className="text-xs text-muted-foreground">
                  법령 구조 질의로 해석되지 않았습니다
                  <br />
                  <span className="text-muted-foreground/60">예: &quot;근로기준법 하위법령은?&quot;</span>
                </p>
              </>
            )}
            {state === "empty" && (
              <>
                <NetworkIcon className="h-6 w-6 text-muted-foreground/40" />
                <p className="text-xs text-muted-foreground">그래프 결과가 없습니다</p>
              </>
            )}
            {state === "error" && (
              <>
                <AlertCircle className="h-6 w-6 text-destructive/70" />
                <p className="text-xs text-muted-foreground">
                  일시적 오류가 발생했습니다
                  <br />
                  <span className="text-muted-foreground/60">잠시 후 다시 시도해주세요</span>
                </p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
