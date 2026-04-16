"""그래프 라우터.

엔드포인트:
  POST /api/v1/graph/query - 자연어 질의 → Neo4j Cypher 실행 → 법령 구조 반환
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.dependencies import get_cypher_planner, get_neo4j_client
from rag_pipeline.graph.neo4j_client import Neo4jClient, Neo4jClientError
from rag_pipeline.graph.cypher_planner import CypherPlanner

logger = logging.getLogger(__name__)

router = APIRouter(tags=["graph"])


class GraphQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="법령 구조 질의 (자연어)")


class GraphQueryResponse(BaseModel):
    query: str
    law_name: str | None
    article_no: str | None
    relation_type: str | None
    results: list[dict[str, Any]]
    cypher: str | None = None  # 디버그용


@router.post("/query", response_model=GraphQueryResponse)
def graph_query(
    request: GraphQueryRequest,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
    planner: CypherPlanner = Depends(get_cypher_planner),
) -> GraphQueryResponse:
    """자연어 질의를 받아 Neo4j에서 법령 구조를 조회하고 반환한다.

    - graph_lookup intent 전용: Qdrant / OpenSearch 검색 없이 Neo4j만 사용한다.
    - Cypher는 고정 템플릿에서 조립하므로 주입 공격이 불가능하다.
    - 에러 시 JSONResponse 직접 반환 → 앱 전역 HTTPException 핸들러 우회, 에러 코드 보존.
    """
    plan = planner.plan(request.query)

    if plan is None:
        return JSONResponse(
            status_code=422,
            content={
                "code": "GRAPH_PLAN_FAILED",
                "error": "법령명 또는 관계 타입을 파악할 수 없습니다. 질의를 구체적으로 입력해주세요.",
            },
        )

    try:
        results = neo4j.run_query(plan.cypher, plan.params)
    except Neo4jClientError as exc:
        logger.error("graph_query Neo4j 실패: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"code": "GRAPH_QUERY_ERROR", "error": str(exc)},
        )

    return GraphQueryResponse(
        query=request.query,
        law_name=plan.slots.law_name,
        article_no=plan.slots.article_no,
        relation_type=plan.relation_type,
        results=results,
        cypher=plan.cypher,
    )
