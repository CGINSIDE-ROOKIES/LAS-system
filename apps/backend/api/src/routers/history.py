"""히스토리 라우터.

엔드포인트:
  GET    /api/v1/qa/history          - Q&A 히스토리 목록
  GET    /api/v1/qa/history/{qa_id}  - 단건 히스토리
  DELETE /api/v1/qa/history          - 복수 히스토리 삭제
  DELETE /api/v1/qa/history/{qa_id}  - 단건 히스토리 삭제
  POST   /api/v1/qa/{qa_id}/feedback - 피드백 저장
"""

import psycopg2.extensions
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.db import get_db
from src.history import delete_history_item, delete_history_items, get_history, get_history_item, save_feedback

router = APIRouter(tags=["history"])


@router.get("/history")
def history(
    q: str | None = Query(default=None, description="질문/답변 검색어"),
    session_id: str | None = Query(default=None, description="세션 ID 필터"),
    date_from: str | None = Query(default=None, description="시작 날짜 (ISO 8601, 예: 2026-01-01)"),
    date_to: str | None = Query(default=None, description="종료 날짜 (ISO 8601, 예: 2026-12-31)"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    """Q&A 히스토리 목록을 반환합니다."""
    try:
        return get_history(
            conn,
            q=q,
            session_id=session_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(min_length=1)


@router.delete("/history", status_code=200)
def delete_history_bulk(
    request: BulkDeleteRequest,
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    """여러 Q&A 히스토리를 한 번에 삭제합니다."""
    deleted = delete_history_items(conn, request.ids)
    return {"deleted": deleted}


@router.delete("/history/{qa_id}", status_code=204)
def delete_history(
    qa_id: str,
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    """단건 Q&A 히스토리를 삭제합니다."""
    deleted = delete_history_item(conn, qa_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="히스토리를 찾을 수 없습니다.")


@router.get("/history/{qa_id}")
def history_item(
    qa_id: str,
    conn: psycopg2.extensions.connection = Depends(get_db),
):
    """단건 Q&A 히스토리를 반환합니다."""
    item = get_history_item(conn, qa_id)
    if item is None:
        raise HTTPException(status_code=404, detail="히스토리를 찾을 수 없습니다.")
    return item


class FeedbackRequest(BaseModel):
    thumbs_up: bool
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    id: str


@router.post("/{qa_id}/feedback", response_model=FeedbackResponse, status_code=201)
def submit_feedback(
    qa_id: str,
    request: FeedbackRequest,
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> FeedbackResponse:
    """Q&A 답변에 대한 사용자 피드백(평점·코멘트)을 저장합니다."""
    try:
        feedback_id = save_feedback(conn, qa_id=qa_id, thumbs_up=request.thumbs_up, comment=request.comment)
    except ValueError:
        raise HTTPException(status_code=404, detail="히스토리를 찾을 수 없습니다.")
    return FeedbackResponse(id=feedback_id)
