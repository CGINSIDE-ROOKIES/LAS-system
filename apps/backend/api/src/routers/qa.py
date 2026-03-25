"""Q&A 라우터.

엔드포인트:
  POST /api/v1/qa/ask        - 질문을 받아 RAG 기반 답변 반환 (단일 응답)
  POST /api/v1/qa/ask/stream - 질문을 받아 RAG 기반 답변 스트리밍 반환 (SSE)
"""

import json
import logging
import traceback

logger = logging.getLogger(__name__)

import psycopg2.extensions
from fastapi import APIRouter, Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.db import get_db
from src.dependencies import get_rag_pipeline
from src.generation.pipeline import RagPipeline
from src.history import save_qa
from src.retrieval.common import RetrievalError

router = APIRouter(tags=["qa"])


_VALID_DOC_TYPES = {"law", "prec", "detc", "decc", "expc"}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
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
    score: float | None
    snippet: str
    text: str = ""


class AskResponse(BaseModel):
    answer: str
    retrieved_docs: list[RetrievedDoc]
    law_context_status: str


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> AskResponse:
    """질문을 받아 RAG 파이프라인을 실행하고 답변을 반환합니다."""
    try:
        result = pipeline.run(
            request.question,
            doc_types=request.doc_types,
            law_names=request.law_names,
        )
    except RetrievalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        logger.error("INTERNAL_ERROR in ask:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    try:
        save_qa(
            conn,
            question=request.question,
            answer=result.answer,
            law_context_status=result.law_context_status,
            retrieved_docs=result.retrieved_docs,
        )
    except Exception:
        logger.error("DB save failed in ask:\n%s", traceback.format_exc())
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
            yield f"data: {json.dumps({'type': 'error', 'code': 'PIPELINE_ERROR', 'error': str(exc)}, ensure_ascii=False)}\n\n"
            return
        except Exception:
            logger.error("INTERNAL_ERROR in ask_stream:\n%s", traceback.format_exc())
            yield f"data: {json.dumps({'type': 'error', 'code': 'INTERNAL_ERROR', 'error': '서버 오류가 발생했습니다.'}, ensure_ascii=False)}\n\n"
            return

        if meta is not None:
            try:
                save_qa(
                    conn,
                    question=request.question,
                    answer="".join(answer_parts),
                    law_context_status=meta.law_context_status,
                    retrieved_docs=meta.retrieved_docs,
                )
            except Exception:
                logger.error("DB save failed in ask_stream:\n%s", traceback.format_exc())

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
