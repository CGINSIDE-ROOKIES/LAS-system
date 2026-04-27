export type GraphNodeKind = "law" | "article";

export type GraphNode = {
  id: string;
  label: string;
  kind: GraphNodeKind;
  lawName?: string;
  lawType?: string;    // "법" | "시행령" | "시행규칙" | "규정" 등
  articleNo?: string;
  isCenter?: boolean;
  hop?: number;        // 0=중심, 1=1차확장, 2=2차확장(expand 불가)
};

export type GraphEdgeRelationType = "child_law" | "delegation" | "reference" | "structure";

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  relationType: GraphEdgeRelationType;
  label?: string;
  detail?: string;         // "제3조 → 제5조" 형태 관계 요약
  paragraphNos?: string[]; // ["제1항", "제2항"]
};

export type LawGraphData = {
  centerNodeId: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  relationType: GraphEdgeRelationType | null;
};

export type GraphQueryResponse = {
  query: string;
  law_name: string | null;
  article_no: string | null;
  relation_type: string | null;
  results: Record<string, unknown>[];
  cypher?: string;
};
