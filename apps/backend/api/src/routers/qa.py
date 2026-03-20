"""Q&A 라우터.

엔드포인트:
  POST /api/v1/qa/ask        - 질문을 받아 RAG 기반 답변 반환 (단일 응답)
  POST /api/v1/qa/ask/stream - 질문을 받아 RAG 기반 답변 스트리밍 반환 (SSE)
"""

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.dependencies import get_rag_pipeline
from src.generation.pipeline import RagPipeline

router = APIRouter(tags=["qa"])


class AskRequest(BaseModel):
    question: str
    doc_types: list[str] | None = None
    law_names: list[str] | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]
    retrieved_docs: list[dict[str, Any]]
    law_context_status: str
    law_context_added: bool


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
) -> AskResponse:
    """질문을 받아 RAG 파이프라인을 실행하고 답변을 반환합니다."""
    result = pipeline.run(
        request.question,
        doc_types=request.doc_types,
        law_names=request.law_names,
    )
    return AskResponse(
        answer=result.answer,
        sources=result.sources,
        retrieved_docs=result.retrieved_docs,
        law_context_status=result.law_context_status,
        law_context_added=result.law_context_added,
    )


@router.post("/ask/stream")
def ask_stream(
    request: AskRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
) -> StreamingResponse:
    """질문을 받아 RAG 파이프라인을 실행하고 답변을 SSE로 스트리밍합니다."""
    def generate():
        for chunk in pipeline.stream(
            request.question,
            doc_types=request.doc_types,
            law_names=request.law_names,
        ):
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
