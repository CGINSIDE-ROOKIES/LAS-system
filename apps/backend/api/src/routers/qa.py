"""Q&A 라우터.

엔드포인트:
  POST /api/v1/qa/ask              - 질문을 받아 RAG 기반 답변 반환 (단일 응답)
  POST /api/v1/qa/ask/stream       - 질문을 받아 RAG 기반 답변 스트리밍 반환 (SSE)
  POST /api/v1/qa/{qa_id}/feedback - Q&A 답변에 대한 사용자 피드백 저장
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
from src.dependencies import get_query_parser, get_rag_pipeline
from rag_pipeline.generation.pipeline import RagPipeline
from rag_pipeline.query_parser import QueryParser
from src.history import delete_history_item, delete_history_items, get_history, get_history_item, save_feedback, save_qa
from rag_pipeline.retrieval.common import EmbeddingError, LLMError, LLMTimeoutError, RetrievalError

router = APIRouter(tags=["qa"])

_IRRELEVANT_ANSWER = (
    "저는 노동법·하도급법 전문 법률 Q&A 어시스턴트입니다. "
    "법률 관련 질문을 해주시면 도움을 드릴 수 있습니다."
)
_VALID_DOC_TYPES = {"law", "prec", "detc", "decc", "expc"}


def _stream_error_payload(exc: Exception) -> dict[str, str]:
    """SSE 에러 이벤트용 코드/메시지 매핑."""
    if isinstance(exc, EmbeddingError):
        return {"type": "error", "code": "EMBEDDING_ERROR", "error": str(exc)}
    if isinstance(exc, LLMTimeoutError):
        return {"type": "error", "code": "LLM_TIMEOUT", "error": str(exc)}
    if isinstance(exc, LLMError):
        return {"type": "error", "code": "LLM_ERROR", "error": str(exc)}
    if isinstance(exc, RetrievalError):
        return {"type": "error", "code": "PIPELINE_ERROR", "error": str(exc)}
    return {"type": "error", "code": "INTERNAL_ERROR", "error": "서버 오류가 발생했습니다."}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    doc_types: list[str] | None = None
    law_filter: list[str] | None = None

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


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
    parser: QueryParser = Depends(get_query_parser),
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> AskResponse:
    """질문을 받아 RAG 파이프라인을 실행하고 답변을 반환합니다."""
    t0 = time.perf_counter()
    logger.info("ask 요청: %s", request.question[:80])

    parsed = parser.parse(request.question)
    logger.info(
        "query_parser: law_names=%r article_no=%r intent=%r is_legal=%r parser_fallback=%r",
        parsed.law_names, parsed.article_no, parsed.intent, parsed.is_legal, parsed.parser_fallback,
    )

    if not parsed.is_legal:
        logger.info("ask 조기 반환: 법률 무관 질문")
        return AskResponse(
            answer=_IRRELEVANT_ANSWER,
            retrieved_docs=[],
            law_context_status="irrelevant",
        )

    # UI 법령 필터 우선, 없으면 파서 결과 사용
    effective_law_names = (
        request.law_filter
        if request.law_filter is not None
        else (parsed.law_names or None)
    )

    result = pipeline.run(
        request.question,
        doc_types=request.doc_types,
        law_names=effective_law_names,
        intent=parsed.intent,
    )
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
    parser: QueryParser = Depends(get_query_parser),
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> StreamingResponse:
    """질문을 받아 RAG 파이프라인을 실행하고 답변을 SSE로 스트리밍합니다."""
    parsed = parser.parse(request.question)
    logger.info(
        "query_parser: law_names=%r article_no=%r intent=%r is_legal=%r parser_fallback=%r",
        parsed.law_names, parsed.article_no, parsed.intent, parsed.is_legal, parsed.parser_fallback,
    )

    if not parsed.is_legal:
        logger.info("ask_stream 조기 반환: 법률 무관 질문")
        def _irrelevant():
            yield f"data: {json.dumps({'type': 'chunk', 'content': _IRRELEVANT_ANSWER}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'retrieved_docs': [], 'law_context_status': 'irrelevant'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(_irrelevant(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    # UI 법령 필터 우선, 없으면 파서 결과 사용
    effective_law_names = (
        request.law_filter
        if request.law_filter is not None
        else (parsed.law_names or None)
    )

    def generate():
        t0 = time.perf_counter()
        logger.info("ask_stream 요청: %s", request.question[:80])
        answer_parts: list[str] = []
        meta = None
        try:
            if pipeline.is_embedding_cold_start():
                logger.info("ask_stream cold start: embedding model initialization required")
                status_payload = {
                    "type": "status",
                    "code": "EMBEDDING_COLD_START",
                    "message": "초기 요청이라 임베딩 모델을 준비 중입니다. 첫 응답은 30~90초 정도 걸릴 수 있습니다.",
                }
                yield f"data: {json.dumps(status_payload, ensure_ascii=False)}\n\n"
            meta, chunks = pipeline.stream(
                request.question,
                doc_types=request.doc_types,
                law_names=effective_law_names,
                intent=parsed.intent,
            )
            first_chunk = True
            for chunk in chunks:
                if first_chunk:
                    logger.info("ask_stream 첫 토큰: %.2fs", time.perf_counter() - t0)
                    first_chunk = False
                answer_parts.append(chunk)
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

            logger.info("ask_stream 완료: %.2fs | law_context_status=%s", time.perf_counter() - t0, meta.law_context_status)
            answer = "".join(answer_parts)
            qa_id = None
            if answer.strip():
                try:
                    qa_id = save_qa(
                        conn,
                        question=request.question,
                        answer=answer,
                        law_context_status=meta.law_context_status,
                        retrieved_docs=meta.retrieved_docs,
                        session_id=request.session_id,
                    )
                except Exception:
                    logger.error("DB save failed in ask_stream:\n%s", traceback.format_exc())

            done_payload = {
                "type": "done",
                "retrieved_docs": [RetrievedDoc(**doc).model_dump() for doc in meta.retrieved_docs],
                "law_context_status": meta.law_context_status,
                "qa_id": qa_id,
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
        except (EmbeddingError, LLMTimeoutError, LLMError, RetrievalError) as exc:
            payload = _stream_error_payload(exc)
            logger.error("%s in ask_stream: %s", payload["code"], exc)
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return
        except Exception:
            logger.error("INTERNAL_ERROR in ask_stream:\n%s", traceback.format_exc())
            yield f"data: {json.dumps({'type': 'error', 'code': 'INTERNAL_ERROR', 'error': '서버 오류가 발생했습니다.'}, ensure_ascii=False)}\n\n"
            return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
