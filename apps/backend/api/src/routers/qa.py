"""Q&A 라우터.

엔드포인트:
  POST /api/v1/qa/ask              - 질문을 받아 RAG 기반 답변 반환 (단일 응답)
  POST /api/v1/qa/ask/stream       - 질문을 받아 RAG 기반 답변 스트리밍 반환 (SSE)
  POST /api/v1/qa/{qa_id}/feedback - Q&A 답변에 대한 사용자 피드백 저장
"""

import json
import logging
import re
import time

import psycopg2.extensions
from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.db import get_db
from src.dependencies import get_generation_service, get_query_parser, get_rag_pipeline
from rag_pipeline.generation.pipeline import RagPipeline, build_system_prompt
from rag_pipeline.generation.service import GenerationService
from rag_pipeline.observability.tracing import end_span, start_span, start_trace, update_trace
from rag_pipeline.query_parser import QueryParser
from src.history import delete_history_item, delete_history_items, get_history, get_history_item, save_feedback, save_qa
from rag_pipeline.retrieval.common import EmbeddingError, LLMError, LLMTimeoutError, RetrievalError

router = APIRouter(tags=["qa"])
logger = logging.getLogger(__name__)

_ANSWERABLE_RE = re.compile(r'\n?\[ANSWERABLE:(yes|no)\]\s*$', re.IGNORECASE)


def _strip_answerable_flag(answer: str) -> tuple[str, bool]:
    """답변 끝의 [ANSWERABLE:yes/no] 플래그를 파싱해 제거한다.

    플래그가 없으면 (answer, True) 반환 (하위 호환).
    """
    m = _ANSWERABLE_RE.search(answer)
    if m:
        return answer[:m.start()].rstrip(), m.group(1).lower() == "yes"
    return answer, True

_IRRELEVANT_ANSWER = (
    "저는 노동법·하도급법 전문 법률 Q&A 어시스턴트입니다. "
    "법률 관련 질문을 해주시면 도움을 드릴 수 있습니다."
)
_VALID_DOC_TYPES = {"law", "prec", "detc", "decc", "expc"}


def _stream_error_payload(exc: Exception) -> dict[str, str]:
    """SSE 에러 이벤트용 코드/메시지 매핑."""
    if isinstance(exc, EmbeddingError):
        return {"type": "error", "code": "EMBEDDING_ERROR", "error": "검색 임베딩 처리 중 오류가 발생했습니다."}
    if isinstance(exc, LLMTimeoutError):
        return {"type": "error", "code": "LLM_TIMEOUT", "error": "응답 생성 시간이 초과되었습니다."}
    if isinstance(exc, LLMError):
        return {"type": "error", "code": "LLM_ERROR", "error": "LLM 응답 생성 중 오류가 발생했습니다."}
    if isinstance(exc, RetrievalError):
        return {"type": "error", "code": "PIPELINE_ERROR", "error": "검색 파이프라인 오류가 발생했습니다."}
    return {"type": "error", "code": "INTERNAL_ERROR", "error": "서버 오류가 발생했습니다."}


def _resolve_query_filters(
    request: "AskRequest",
    parser: QueryParser,
    trace: object | None = None,
) -> tuple[object, list[str] | None]:
    """질문 파싱 결과와 최종 법령 필터를 계산한다.

    법령 필터 우선순위:
      1) UI에서 전달한 request.law_filter
      2) QueryParser가 추출한 parsed.law_names
    """
    span = start_span(trace, "query_parse", input={"question": request.question})
    try:
        parsed = parser.parse(request.question, previous_question=request.previous_question)
    except Exception:
        end_span(span, level="ERROR")
        raise
    logger.info(
        "query_parser: law_names=%r intent=%r is_legal=%r parser_fallback=%r normalized_query=%r",
        parsed.law_names, parsed.intent, parsed.is_legal, parsed.parser_fallback, parsed.normalized_query,
    )
    end_span(
        span,
        output={
            "law_names": parsed.law_names,
            "intent": parsed.intent,
            "is_legal": parsed.is_legal,
            "parser_fallback": parsed.parser_fallback,
            "normalized_query": parsed.normalized_query,
        },
        level="DEFAULT",
    )
    effective_law_names = (
        request.law_filter
        if request.law_filter is not None
        else (parsed.law_names or None)
    )
    return parsed, effective_law_names


def _irrelevant_ask_response() -> "AskResponse":
    """법률 무관 질문에 대한 고정 응답."""
    return AskResponse(
        answer=_IRRELEVANT_ANSWER,
        retrieved_docs=[],
        law_context_status="irrelevant",
    )


_VALID_ANSWER_DETAILS = {"brief", "normal", "detailed"}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    doc_types: list[str] | None = None
    law_filter: list[str] | None = None
    answer_detail: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    previous_question: str | None = Field(default=None, max_length=2000)
    previous_answer: str | None = Field(default=None, max_length=4000)

    @field_validator("answer_detail")
    @classmethod
    def answer_detail_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_ANSWER_DETAILS:
            raise ValueError(f"유효하지 않은 answer_detail: {v!r}. 허용값: {sorted(_VALID_ANSWER_DETAILS)}")
        return v

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
    qa_id: str | None = None


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


# ask/ask_stream은 동기 함수로 유지한다.
# - rag pipeline / psycopg2 연결이 동기 API이며
# - FastAPI가 sync endpoint를 worker thread에서 실행해 이벤트 루프 블로킹을 피한다.
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

    trace = start_trace(
        "qa_request",
        input={"question": request.question, "law_filter": request.law_filter, "doc_types": request.doc_types},
    )
    parsed, effective_law_names = _resolve_query_filters(request, parser, trace=trace)

    if not parsed.is_legal:
        logger.info("ask 조기 반환: 법률 무관 질문")
        update_trace(trace, output={"answer": _IRRELEVANT_ANSWER}, level="DEFAULT")
        return _irrelevant_ask_response()

    result = pipeline.run(
        request.question,
        system_prompt=build_system_prompt(request.answer_detail),
        doc_types=request.doc_types,
        law_names=effective_law_names,
        intent=parsed.intent,
        search_query=parsed.normalized_query or None,
        trace=trace,
        previous_question=request.previous_question,
        previous_answer=request.previous_answer,
        top_k=request.top_k,
    )
    answer, can_answer = _strip_answerable_flag(result.answer)
    qa_id: str | None = None
    if answer.strip() and can_answer:
        try:
            qa_id = save_qa(
                conn,
                question=request.question,
                answer=answer,
                law_context_status=result.law_context_status,
                retrieved_docs=result.retrieved_docs,
                session_id=request.session_id,
            )
        except Exception:
            logger.exception("DB save failed in ask")
    logger.info("ask 완료: %.2fs | law_context_status=%s | can_answer=%s", time.perf_counter() - t0, result.law_context_status, can_answer)
    return AskResponse(
        answer=answer,
        retrieved_docs=[RetrievedDoc(**doc) for doc in result.retrieved_docs],
        law_context_status=result.law_context_status,
        qa_id=qa_id,
    )


@router.post("/ask/stream")
def ask_stream(
    request: AskRequest,
    pipeline: RagPipeline = Depends(get_rag_pipeline),
    parser: QueryParser = Depends(get_query_parser),
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> StreamingResponse:
    """질문을 받아 RAG 파이프라인을 실행하고 답변을 SSE로 스트리밍합니다."""
    trace = start_trace(
        "qa_request",
        input={"question": request.question, "law_filter": request.law_filter, "doc_types": request.doc_types},
    )
    parsed, effective_law_names = _resolve_query_filters(request, parser, trace=trace)

    if not parsed.is_legal:
        logger.info("ask_stream 조기 반환: 법률 무관 질문")
        update_trace(trace, output={"answer": _IRRELEVANT_ANSWER}, level="DEFAULT")

        def _irrelevant():
            yield f"data: {json.dumps({'type': 'chunk', 'content': _IRRELEVANT_ANSWER}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'retrieved_docs': [], 'law_context_status': 'irrelevant'}, ensure_ascii=False)}\n\n"

        return StreamingResponse(_irrelevant(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    def generate():
        """SSE 제너레이터.

        `conn`은 FastAPI dependency 스코프 내 객체로, 스트리밍 응답이 종료될 때까지 유효하다.
        """
        t0 = time.perf_counter()
        logger.info("ask_stream 요청: %s", request.question[:80])
        answer_parts: list[str] = []
        meta = None
        try:
            meta, chunks = pipeline.stream(
                request.question,
                system_prompt=build_system_prompt(request.answer_detail),
                doc_types=request.doc_types,
                law_names=effective_law_names,
                intent=parsed.intent,
                search_query=parsed.normalized_query or None,
                trace=trace,
                previous_question=request.previous_question,
                previous_answer=request.previous_answer,
                top_k=request.top_k,
            )
            first_chunk = True
            for chunk in chunks:
                if first_chunk:
                    logger.info("ask_stream 첫 토큰: %.2fs", time.perf_counter() - t0)
                    first_chunk = False
                answer_parts.append(chunk)
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

            answer, can_answer = _strip_answerable_flag("".join(answer_parts))
            logger.info("ask_stream 완료: %.2fs | law_context_status=%s | can_answer=%s", time.perf_counter() - t0, meta.law_context_status, can_answer)
            qa_id = None
            if answer.strip() and can_answer:
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
                    logger.exception("DB save failed in ask_stream")

            if meta is None:
                raise RuntimeError("ask_stream meta is None")

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
            logger.exception("INTERNAL_ERROR in ask_stream")
            yield f"data: {json.dumps({'type': 'error', 'code': 'INTERNAL_ERROR', 'error': '서버 오류가 발생했습니다.'}, ensure_ascii=False)}\n\n"
            return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


_SUGGESTIONS_SYSTEM = (
    "당신은 노동법·하도급법 전문 법률 Q&A 어시스턴트입니다. "
    "사용자의 질문과 답변을 바탕으로 후속 질문 4개를 생성합니다. "
    "반드시 아래 규칙을 따르세요:\n"
    "1. 답변에서 실제로 언급된 개념·조건·예외 범위 안에서만 질문을 만드세요. 답변에 없는 내용은 추천하지 마세요.\n"
    "2. 각 질문은 20자 이내로 간결하게 작성하세요.\n"
    "3. 반드시 JSON 배열 형식으로만 반환하세요. 예: [\"질문1\", \"질문2\", \"질문3\", \"질문4\"]"
)


def _build_suggestions_prompt(question: str, answer: str, intent: str | None) -> str:
    intent_hint = f"\n질문 유형: {intent}" if intent else ""
    return (
        f"질문: {question}{intent_hint}\n\n"
        f"답변:\n{answer}\n\n"
        "위 대화를 바탕으로 사용자가 이어서 궁금해할 후속 질문 4개를 JSON 배열로 반환하세요."
    )


def _parse_suggestions(raw: str) -> list[str]:
    """LLM 응답에서 후속 질문 목록을 파싱한다. 파싱 실패 시 빈 리스트 반환."""
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        return []
    try:
        result = json.loads(match.group())
        if isinstance(result, list):
            return [str(s).strip() for s in result if isinstance(s, str) and str(s).strip()][:4]
    except json.JSONDecodeError:
        pass
    return []


class SuggestionsRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)
    intent: str | None = None


class SuggestionsResponse(BaseModel):
    suggestions: list[str]


@router.post("/suggestions", response_model=SuggestionsResponse)
def get_suggestions(
    request: SuggestionsRequest,
    gen_service: GenerationService = Depends(get_generation_service),
) -> SuggestionsResponse:
    """질문·답변을 바탕으로 후속 추천 질문 3개를 생성합니다."""
    try:
        result = gen_service.generate(
            _build_suggestions_prompt(request.question, request.answer, request.intent),
            system_prompt=_SUGGESTIONS_SYSTEM,
        )
        suggestions = _parse_suggestions(result.answer)
    except Exception:
        logger.exception("suggestions 생성 실패")
        suggestions = []
    return SuggestionsResponse(suggestions=suggestions)
