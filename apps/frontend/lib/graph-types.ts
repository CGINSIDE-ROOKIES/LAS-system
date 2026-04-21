export type GraphNodeKind = "law" | "article";

export type GraphNode = {
  id: string;
  label: string;
  kind: GraphNodeKind;
  lawName?: string;
  articleNo?: string;
  isCenter?: boolean;
};

export type GraphEdgeRelationType = "child_law" | "delegation" | "reference" | "structure";

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  relationType: GraphEdgeRelationType;
  label?: string;
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
