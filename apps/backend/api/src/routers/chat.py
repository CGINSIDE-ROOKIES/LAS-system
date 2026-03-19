"""채팅 라우터.

엔드포인트:
  POST /chat         - 질문을 받아 RAG 기반 답변 반환 (단일 응답)
  POST /chat/stream  - 질문을 받아 RAG 기반 답변 스트리밍 반환 (NDJSON)
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from src.dependencies import get_generation_service, get_retrieval_service

router = APIRouter(tags=["chat"])


# TODO: 요청/응답 스키마는 rag/src/models/schemas.py 정의 후 import
# from rag.src.models.schemas import ChatRequest, ChatResponse


@router.post("")
async def chat(
    # request: ChatRequest,
    retrieval_service=Depends(get_retrieval_service),
    generation_service=Depends(get_generation_service),
):
    """질문을 받아 검색 + 생성 파이프라인을 실행하고 답변을 반환합니다."""
    # 1. retrieval_service.search(request.question) → contexts
    # 2. generation_service.generate(request.question, contexts) → answer
    # 3. return ChatResponse(answer=answer, contexts=contexts)
    raise NotImplementedError


@router.post("/stream")
async def chat_stream(
    # request: ChatRequest,
    retrieval_service=Depends(get_retrieval_service),
    generation_service=Depends(get_generation_service),
):
    """질문을 받아 검색 + 생성 파이프라인을 실행하고 답변을 스트리밍합니다."""
    # async def generate():
    #     contexts = await retrieval_service.search(request.question)
    #     async for chunk in generation_service.stream(request.question, contexts):
    #         yield chunk.model_dump_json() + "\n"
    # return StreamingResponse(generate(), media_type="application/x-ndjson")
    raise NotImplementedError
