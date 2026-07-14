"""그래프 라우터.

엔드포인트:
  POST /api/v1/graph/query  - 자연어 질의 → Neo4j Cypher 실행 → 법령 구조 반환
  POST /api/v1/graph/expand - 법령 노드 클릭 시 연결 법령 직접 조회 (LLM 불필요)
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
    except Neo4jClientError:
        logger.error("graph_query Neo4j 실패", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={
                "code": "GRAPH_QUERY_ERROR",
                "error": "그래프 조회 중 내부 오류가 발생했습니다.",
            },
        )

    return GraphQueryResponse(
        query=request.query,
        law_name=plan.slots.law_name,
        article_no=plan.slots.article_no,
        relation_type=plan.relation_type,
        results=results,
        cypher=plan.cypher,
    )


# ── /expand ──────────────────────────────────────────────────────────────────

class GraphExpandRequest(BaseModel):
    law_name: str = Field(..., min_length=1, max_length=200, description="확장할 법령명")


class LawRef(BaseModel):
    law_name: str
    law_uid: str | None
    classified_level: str | None


class GraphExpandResponse(BaseModel):
    law_name: str
    child_laws: list[LawRef]
    delegated_laws: list[LawRef]
    referred_laws: list[LawRef]


# COLLECT로 관계별 리스트를 각각 수집 — OPTIONAL MATCH 카르테시안 곱 방지
# [0..$limit] 슬라이싱으로 관계별 최대 건수를 제한해 대규모 fan-out 방지
_EXPAND_CYPHER = """\
MATCH (l:Law {law_name: $law_name})
OPTIONAL MATCH (l)-[:HAS_CHILD_LAW]->(child:Law)
WITH l,
  COLLECT(DISTINCT {law_name: child.law_name, law_uid: child.law_uid, classified_level: child.classified_level})[0..$limit] AS child_laws
OPTIONAL MATCH (l)-[:DELEGATES_TO_LAW]->(delegated:Law)
WITH l, child_laws,
  COLLECT(DISTINCT {law_name: delegated.law_name, law_uid: delegated.law_uid, classified_level: delegated.classified_level})[0..$limit] AS delegated_laws
OPTIONAL MATCH (l)-[:REFERS_TO_LAW]->(referred:Law)
WITH child_laws, delegated_laws,
  COLLECT(DISTINCT {law_name: referred.law_name, law_uid: referred.law_uid, classified_level: referred.classified_level})[0..$limit] AS referred_laws
RETURN child_laws, delegated_laws, referred_laws
"""

_EXPAND_LIMIT = 50


def _parse_law_refs(items: list[dict]) -> list[LawRef]:
    return [
        LawRef(
            law_name=item["law_name"],
            law_uid=item.get("law_uid"),
            classified_level=item.get("classified_level"),
        )
        for item in (items or [])
        if item.get("law_name")
    ]


@router.post("/expand", response_model=GraphExpandResponse)
def graph_expand(
    request: GraphExpandRequest,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> GraphExpandResponse:
    """법령 노드 클릭 시 연결된 법령 간 관계를 직접 조회한다.

    LLM 없이 Neo4j Cypher를 직접 실행하므로 지연 없이 즉시 응답한다.
    관계 타입: HAS_CHILD_LAW(하위), DELEGATES_TO_LAW(위임), REFERS_TO_LAW(참조)
    """
    try:
        rows = neo4j.run_query(_EXPAND_CYPHER, {"law_name": request.law_name, "limit": _EXPAND_LIMIT})
    except Neo4jClientError:
        logger.error("graph_expand Neo4j 실패", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"code": "GRAPH_EXPAND_ERROR", "error": "그래프 확장 조회 중 오류가 발생했습니다."},
        )

    if not rows:
        return GraphExpandResponse(
            law_name=request.law_name,
            child_laws=[],
            delegated_laws=[],
            referred_laws=[],
        )

    row = rows[0]
    return GraphExpandResponse(
        law_name=request.law_name,
        child_laws=_parse_law_refs(row.get("child_laws", [])),
        delegated_laws=_parse_law_refs(row.get("delegated_laws", [])),
        referred_laws=_parse_law_refs(row.get("referred_laws", [])),
    )
