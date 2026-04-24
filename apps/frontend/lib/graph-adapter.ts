import type { GraphEdge, GraphEdgeRelationType, GraphNode, GraphQueryResponse, LawGraphData } from "./graph-types";

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
      }
    : {
        id: centerId,
        label: resp.law_name,
        kind: "law",
        lawName: resp.law_name,
        isCenter: true,
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
