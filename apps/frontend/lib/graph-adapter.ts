import { DataSet } from "vis-data";
import type { GraphEdge, GraphEdgeRelationType, GraphNode, GraphQueryResponse, LawGraphData } from "./graph-types";

// ── vis-network 색상 헬퍼 ─────────────────────────────────────────────────────

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

export function buildVisDatasets(graphData: LawGraphData) {
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

// ── 그래프 병합 (expand 시 증분 추가) ─────────────────────────────────────────

export function mergeGraphData(
  existing: LawGraphData,
  newNodes: GraphNode[],
  newEdges: GraphEdge[],
  sourceHop: number,
): LawGraphData {
  const seenNodes = new Set(existing.nodes.map((n) => n.id));
  const seenEdges = new Set(existing.edges.map((e) => e.id));

  const addedNodes = newNodes
    .filter((n) => !seenNodes.has(n.id))
    .map((n) => ({ ...n, hop: sourceHop + 1 }));

  const addedEdges = newEdges.filter((e) => !seenEdges.has(e.id));

  return {
    ...existing,
    nodes: [...existing.nodes, ...addedNodes],
    edges: [...existing.edges, ...addedEdges],
  };
}

export function toGraphData(resp: GraphQueryResponse): LawGraphData | null {
  if (!resp.law_name || !resp.results.length) return null;

  const relationType = resp.relation_type as GraphEdgeRelationType | null;

  // 중심 노드: article_no가 있으면 조문 노드, 없으면 법령 노드
  const centerId = resp.article_no
    ? `article:${resp.law_name}:${resp.article_no}`
    : `law:${resp.law_name}`;

  const centerNode: GraphNode = resp.article_no
    ? {
        id: centerId,
        label: `${resp.law_name}\n${resp.article_no}`,
        kind: "article",
        lawName: resp.law_name,
        articleNo: resp.article_no,
        isCenter: true,
        hop: 0,
      }
    : {
        id: centerId,
        label: resp.law_name,
        kind: "law",
        lawName: resp.law_name,
        isCenter: true,
        hop: 0,
      };

  const nodes: GraphNode[] = [centerNode];
  const edges: GraphEdge[] = [];
  const seen = new Set<string>([centerId]);

  for (const row of resp.results) {
    let targetNode: GraphNode | null = null;
    let edgeDetail: string | undefined;
    let edgeParagraphNos: string[] | undefined;

    switch (relationType) {
      case "child_law": {
        const name = row.child_law_name as string | null;
        const uid = row.child_law_uid as string | null;
        const level = row.classified_level as string | null;
        if (!name) continue;
        const id = uid ?? `law:${name}`;
        targetNode = { id, label: name, kind: "law", lawName: name, lawType: level ?? undefined };
        break;
      }
      case "delegation": {
        const name = row.target_law_name as string | null;
        const uid = row.target_law_uid as string | null;
        const level = row.classified_level as string | null;
        if (!name) continue;
        const id = uid ?? `law:${name}`;
        targetNode = { id, label: name, kind: "law", lawName: name, lawType: level ?? undefined };
        break;
      }
      case "reference": {
        const refType = row.ref_type as string | null;
        const refName = row.ref_name as string | null;
        const refUid = row.ref_uid as string | null;
        const refArticleNo = row.ref_article_no as string | null;
        if (!refName) continue;
        if (refType === "article" && refArticleNo) {
          const id = refUid ?? `article:${refName}:${refArticleNo}`;
          const srcArticleNo = row.src_article_no as string | null;
          const paragraphNos = row.ref_paragraph_nos as string[] | null;
          targetNode = {
            id,
            label: `${refName}\n${refArticleNo}`,
            kind: "article",
            lawName: refName,
            articleNo: refArticleNo,
          };
          edgeDetail = srcArticleNo && refArticleNo ? `${srcArticleNo} → ${refArticleNo}` : undefined;
          edgeParagraphNos = paragraphNos ?? undefined;
        } else {
          const level = row.ref_classified_level as string | null;
          const id = refUid ?? `law:${refName}`;
          targetNode = { id, label: refName, kind: "law", lawName: refName, lawType: level ?? undefined };
        }
        break;
      }
      case "structure": {
        const articleNo = row.article_no as string | null;
        const articleUid = row.article_uid as string | null;
        if (!articleNo) continue;
        const id = articleUid ?? `article:${resp.law_name}:${articleNo}`;
        targetNode = {
          id,
          label: articleNo,
          kind: "article",
          lawName: resp.law_name,
          articleNo,
        };
        break;
      }
      default:
        continue;
    }

    if (!targetNode || seen.has(targetNode.id)) continue;
    seen.add(targetNode.id);
    nodes.push(targetNode);
    edges.push({
      id: `${centerId}->${targetNode.id}`,
      source: centerId,
      target: targetNode.id,
      relationType: relationType ?? "reference",
      detail: edgeDetail,
      paragraphNos: edgeParagraphNos,
    });
  }

  if (nodes.length <= 1) return null;

  return { centerNodeId: centerId, nodes, edges, relationType };
}
