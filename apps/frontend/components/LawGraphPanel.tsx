import { useEffect, useRef, useState } from "react";
import { Network as NetworkIcon, Loader2, AlertCircle, BarChart3 } from "lucide-react";
import { DataSet } from "vis-data";
import { Network } from "vis-network";
import type { Options } from "vis-network";
import { queryGraph } from "@/lib/api-client";
import { buildVisDatasets, toGraphData } from "@/lib/graph-adapter";
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

export function LawGraphPanel({ lastQuery, queryKey, isActive, onNodeSelect, onGraphDataChange }: LawGraphPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  // DataSet을 ref로 관리 — expand 시 add()로 증분 추가
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const nodesDataSetRef = useRef<DataSet<any> | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const edgesDataSetRef = useRef<DataSet<any> | null>(null);
  // click handler stale closure 방지용 ref
  const graphDataRef = useRef<LawGraphData | null>(null);
  const onNodeSelectRef = useRef(onNodeSelect);

  const [state, setState] = useState<PanelState>("idle");
  const [graphData, setGraphData] = useState<LawGraphData | null>(null);
  const lastSuccessKey = useRef<number>(-1);
  const requestToken = useRef<number>(0);
  const abortRef = useRef<AbortController | null>(null);

  // onNodeSelect가 바뀌면 ref 동기화
  useEffect(() => {
    onNodeSelectRef.current = onNodeSelect;
  }, [onNodeSelect]);

  // Network 초기화 — 마운트 시 한 번만 생성, DataSet은 재사용
  useEffect(() => {
    if (!containerRef.current) return;

    const nodesDS = new DataSet<object>([]);
    const edgesDS = new DataSet<object>([]);
    nodesDataSetRef.current = nodesDS;
    edgesDataSetRef.current = edgesDS;

    const network = new Network(
      containerRef.current,
      { nodes: nodesDS, edges: edgesDS },
      VIS_OPTIONS,
    );
    networkRef.current = network;

    network.on("click", (params) => {
      if (params.nodes.length === 0) {
        onNodeSelectRef.current(null);
        return;
      }
      const nodeId = params.nodes[0] as string;
      const found = graphDataRef.current?.nodes.find((n) => n.id === nodeId) ?? null;
      onNodeSelectRef.current(found);
    });

    return () => {
      network.destroy();
      networkRef.current = null;
      nodesDataSetRef.current = null;
      edgesDataSetRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 새 질의 — API 호출 후 graphData 교체
  useEffect(() => {
    if (!isActive || !lastQuery || queryKey === lastSuccessKey.current) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const token = ++requestToken.current;

    setState("loading");
    setGraphData(null);
    graphDataRef.current = null;
    onGraphDataChange?.(null);
    onNodeSelectRef.current(null);

    queryGraph(lastQuery, controller.signal)
      .then((resp) => {
        if (token !== requestToken.current || controller.signal.aborted) return;
        const data = toGraphData(resp);
        if (!data) {
          setState("empty");
          return;
        }
        lastSuccessKey.current = queryKey;
        graphDataRef.current = data;
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
  }, [isActive, queryKey, lastQuery, onGraphDataChange]);

  // graphData 변경 시 DataSet 갱신 — 새 질의는 clear 후 교체, expand는 add만
  useEffect(() => {
    if (!graphData || !nodesDataSetRef.current || !edgesDataSetRef.current) return;

    const { nodes, edges } = buildVisDatasets(graphData);
    nodesDataSetRef.current.clear();
    edgesDataSetRef.current.clear();
    nodesDataSetRef.current.add(nodes.get());
    edgesDataSetRef.current.add(edges.get());
    networkRef.current?.fit();
  }, [graphData]);

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
        {/* vis-network 컨테이너 — 항상 마운트, display로 표시/숨김 제어 */}
        <div
          ref={containerRef}
          className="absolute inset-0"
          style={{ display: state === "success" ? "block" : "none" }}
        />

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
