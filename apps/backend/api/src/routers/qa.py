"""Q&A 라우터.

엔드포인트:
  POST /api/v1/qa/ask        - 질문을 받아 RAG 기반 답변 반환 (단일 응답)
  POST /api/v1/qa/ask/stream - 질문을 받아 RAG 기반 답변 스트리밍 반환 (SSE)
"""

import json
import logging
import time
import traceback

logger = logging.getLogger(__name__)

import psycopg2.extensions
from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.db import get_db
from src.dependencies import get_rag_pipeline
from src.generation.pipeline import RagPipeline
from src.history import delete_history_item, delete_history_items, get_history, get_history_item, save_qa
from src.retrieval.common import RetrievalError

router = APIRouter(tags=["qa"])


_VALID_DOC_TYPES = {"law", "prec", "detc", "decc", "expc"}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    doc_types: list[str] | None = None
    law_names: list[str] | None = None

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("질문은 공백만으로 이루어질 수 없습니다.")
        return v.strip()

    @field_validator("doc_types")
    @classmethod
    def doc_types_valid(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        invalid = [t for t in v if t not in _VALID_DOC_TYPES]
        if invalid:
            raise ValueError(f"유효하지 않은 doc_type: {invalid}. 허용값: {sorted(_VALID_DOC_TYPES)}")
        return v


class RetrievedDoc(BaseModel):
    rank: int
    source_id: str
    doc_type: str
    law_name: str
    article_no: str = ""
    score: float | None
    snippet: str
    text: str = ""


class AskResponse(BaseModel):
    answer: str
    retrieved_docs: list[RetrievedDoc]
    law_context_status: str


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
    return get_history(
        conn,
        q=q,
        session_id=session_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


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


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> AskResponse:
    """질문을 받아 RAG 파이프라인을 실행하고 답변을 반환합니다."""
    t0 = time.perf_counter()
    logger.info("ask 요청: %s", request.question[:80])
    try:
        result = pipeline.run(
            request.question,
            doc_types=request.doc_types,
            law_names=request.law_names,
        )
    except RetrievalError as exc:
        logger.error("ask RetrievalError: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        logger.error("INTERNAL_ERROR in ask:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    if result.answer.strip():
        try:
            save_qa(
                conn,
                question=request.question,
                answer=result.answer,
                law_context_status=result.law_context_status,
                retrieved_docs=result.retrieved_docs,
                session_id=request.session_id,
            )
        except Exception:
            logger.error("DB save failed in ask:\n%s", traceback.format_exc())
    logger.info("ask 완료: %.2fs | law_context_status=%s", time.perf_counter() - t0, result.law_context_status)
    return AskResponse(
        answer=result.answer,
        retrieved_docs=[RetrievedDoc(**doc) for doc in result.retrieved_docs],
        law_context_status=result.law_context_status,
    )


@router.post("/ask/stream")
def ask_stream(
    request: AskRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> StreamingResponse:
    """질문을 받아 RAG 파이프라인을 실행하고 답변을 SSE로 스트리밍합니다."""
    def generate():
        t0 = time.perf_counter()
        logger.info("ask_stream 요청: %s", request.question[:80])
        answer_parts: list[str] = []
        meta = None
        try:
            meta, chunks = pipeline.stream(
                request.question,
                doc_types=request.doc_types,
                law_names=request.law_names,
            )
            for chunk in chunks:
                answer_parts.append(chunk)
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
            done_payload = {
                "type": "done",
                "retrieved_docs": [RetrievedDoc(**doc).model_dump() for doc in meta.retrieved_docs],
                "law_context_status": meta.law_context_status,
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
        except RetrievalError as exc:
            logger.error("ask_stream RetrievalError: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'code': 'PIPELINE_ERROR', 'error': str(exc)}, ensure_ascii=False)}\n\n"
            return
        except Exception:
            logger.error("INTERNAL_ERROR in ask_stream:\n%s", traceback.format_exc())
            yield f"data: {json.dumps({'type': 'error', 'code': 'INTERNAL_ERROR', 'error': '서버 오류가 발생했습니다.'}, ensure_ascii=False)}\n\n"
            return

        if meta is not None:
            logger.info("ask_stream 완료: %.2fs | law_context_status=%s", time.perf_counter() - t0, meta.law_context_status)
            answer = "".join(answer_parts)
            if answer.strip():
                try:
                    save_qa(
                        conn,
                        question=request.question,
                        answer=answer,
                        law_context_status=meta.law_context_status,
                        retrieved_docs=meta.retrieved_docs,
                        session_id=request.session_id,
                    )
                except Exception:
                    logger.error("DB save failed in ask_stream:\n%s", traceback.format_exc())

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
