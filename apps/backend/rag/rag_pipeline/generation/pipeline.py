"""RAG 파이프라인 서비스.

retrieval → context → prompt → generation 전체 흐름을 조립한다.
API 레이어는 RagPipeline.run() / RagPipeline.stream()만 호출하면 된다.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Iterator

logger = logging.getLogger(__name__)

from ..observability.langfuse_client import score_trace
from ..observability.tracing import end_span, get_trace_id, start_generation_span, start_span, start_trace, update_trace
from ..retrieval.common import DEFAULT_EMBEDDING_MODEL, RetrievalError, embed_query
from ..retrieval.context import build_llm_context_rows, build_llm_context_text, truncate_on_semantic_boundary
from ..retrieval.fusion import fuse_rrf, fuse_rrf_multi
from ..retrieval.opensearch import search_bm25
from ..retrieval.qdrant import search_qdrant_with_vector
from ..retrieval.ranking import (
    LAW_CONTEXT_CASE_ONLY,
    LAW_CONTEXT_MISSING,
    LAW_CONTEXT_OK,
    LAW_CONTEXT_SUPPLEMENTED,
    apply_law_boost,
    filter_noise_chunks,
    rank_rows,
    select_rows_with_law_policy,
)
from ..retrieval.service import RetrievalConfig
from .service import GenerationConfig, GenerationService

_LAW_CONTEXT_SCORES: dict[str, float] = {
    LAW_CONTEXT_OK: 1.0,
    LAW_CONTEXT_SUPPLEMENTED: 0.7,
    LAW_CONTEXT_CASE_ONLY: 0.5,
    LAW_CONTEXT_MISSING: 0.0,
}

_NO_RESULT_ANSWER = (
    "관련 법령·판례 문서를 찾지 못했습니다. "
    "질문을 더 구체적으로 입력하시거나, 법령 필터가 설정되어 있다면 해제 후 다시 시도해보세요."
)

_SYSTEM_PROMPT_BASE = (
    "당신은 노동법 및 하도급법 전문 법률 Q&A 어시스턴트입니다.\n"
    "주요 대상 법령은 근로기준법, 기간제 및 단시간근로자 보호 등에 관한 법률, "
    "파견근로자 보호 등에 관한 법률, 최저임금법, 남녀고용평등과 일·가정 양립 지원에 관한 법률, "
    "근로자퇴직급여 보장법, 하도급거래 공정화에 관한 법률, 건설산업기본법 등입니다.\n\n"
    "답변 시 다음 원칙을 따르세요:\n"
    "- 제공된 컨텍스트에 있는 내용만 근거로 답변하세요.\n"
    "- 조문 번호나 출처 표기는 하지 마세요. 근거 문서는 별도로 제공됩니다.\n"
    "- 컨텍스트에 없는 내용은 절대 생성하지 마세요. 컨텍스트가 질문과 무관하거나 관련 정보가 없으면 그 사실 한 문장만 답하고 추가 내용을 작성하지 마세요.\n"
    "{detail_instruction}"
    "- 답변 마지막 줄에 반드시 [ANSWERABLE:yes] 또는 [ANSWERABLE:no]를 단독으로 출력하세요. "
    "컨텍스트가 질문과 관련 있어 답변할 수 있으면 [ANSWERABLE:yes], "
    "컨텍스트가 질문과 무관해 실질적으로 답변할 수 없으면 [ANSWERABLE:no]입니다."
)

_DETAIL_INSTRUCTIONS: dict[str, str] = {
    "brief": (
        "- 핵심 내용을 3~5문장 이내로 간결하게 전달하세요.\n"
        "- 법령명·핵심 개념·중요 조건은 **볼드**로 강조하세요.\n"
        "- 전문적이되 자연스러운 구어체로 작성하세요.\n"
    ),
    "normal": (
        "- 핵심 내용을 5~10문장 내외로 전달하세요.\n"
        "- 법령명·핵심 개념·중요 조건은 **볼드**로 강조하세요.\n"
        "- 전문적이되 자연스러운 구어체로 작성하세요.\n"
    ),
    "detailed": (
        "- 관련 조문·사례를 포함해 충분한 근거와 함께 상세히 설명하세요.\n\n"
        "**[출력 형식 — 반드시 준수]**\n"
        "- 연속 문단(산문) 나열 금지. 구조화된 마크다운으로만 작성하세요.\n"
        "- 주제나 단계가 2개 이상이면 ## 소제목으로 섹션을 나누세요.\n"
        "- 나열 항목은 번호 목록(1. 2. 3.) 또는 글머리 기호(-)를 사용하세요.\n"
        "- 법령명, 핵심 개념, 중요 조건은 **볼드**로 강조하세요.\n"
    ),
}

DEFAULT_SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE.format(
    detail_instruction=_DETAIL_INSTRUCTIONS["normal"]
)


def build_system_prompt(answer_detail: str | None) -> str:
    """답변 상세도 설정에 따른 시스템 프롬프트를 반환한다.

    Args:
        answer_detail: "brief" | "normal" | "detailed" | None.
            None 또는 미지원 값이면 기본(normal) 프롬프트를 반환한다.
    """
    instruction = _DETAIL_INSTRUCTIONS.get(answer_detail or "normal", _DETAIL_INSTRUCTIONS["normal"])
    return _SYSTEM_PROMPT_BASE.format(detail_instruction=instruction)


@dataclass
class RagPipelineConfig:
    """RagPipeline 전체 설정."""

    retrieval: RetrievalConfig
    generation: GenerationConfig
    enforce_min_law_contexts: bool = True
    max_input_chars: int = 6000
    snippet_max_chars: int = 200


@dataclass
class RagResult:
    """run() 반환값. API 응답으로 직렬화한다."""

    answer: str
    retrieved_docs: list[dict[str, Any]]  # 컨텍스트에 사용된 문서 목록
    law_context_status: str               # ranking.LAW_CONTEXT_* 상수 중 하나


# ── 프롬프트 빌더 ─────────────────────────────────────────────────────────────

def build_user_prompt_with_limit(
    *,
    retrieved_context_text: str,
    question: str,
    max_input_chars: int,
    law_context_status: str,
    previous_question: str | None = None,
    previous_answer: str | None = None,
) -> str:
    """system_prompt를 제외한 user 메시지 본문(컨텍스트 + 질문)을 조립한다."""
    status_line = ""
    if law_context_status == LAW_CONTEXT_MISSING:
        status_line = (
            "중요: 현재 검색 결과에서 법령(law) 근거가 충분하지 않습니다.\n"
            "관련 법령 근거가 없음을 명시하고, 컨텍스트에 있는 내용만 답하세요. 컨텍스트 외 지식으로 내용을 채우지 마세요.\n\n"
        )
    elif law_context_status == LAW_CONTEXT_SUPPLEMENTED:
        status_line = "참고: 법령(law) 문서를 보강한 컨텍스트로 답변합니다.\n\n"
    elif law_context_status == LAW_CONTEXT_CASE_ONLY:
        status_line = "참고: 현재 검색 결과에 법령 조문이 없고 판례·해석례만 포함되어 있습니다.\n조문 근거 없이 판례 중심으로 답변하세요.\n\n"

    prev_section = ""
    if previous_question and previous_answer:
        prev_section = (
            "[이전 Q&A 맥락]\n"
            f"질문: {previous_question}\n"
            f"답변: {previous_answer}\n\n"
        )

    prefix = (
        f"{prev_section}"
        f"{status_line}"
        "아래 검색 컨텍스트를 근거로만 답변하세요.\n"
        "근거가 부족하면 부족하다고 명시하세요.\n\n"
    )
    suffix = f"\n\n[최종 질문]\n{question}"

    if max_input_chars <= 0:
        return f"{prefix}{retrieved_context_text}{suffix}"

    keep = max_input_chars - len(prefix) - len(suffix)
    if keep <= 0:
        return f"[최종 질문]\n{question}"

    context = retrieved_context_text
    if len(context) > keep:
        # 단순 슬라이싱 대신 의미 경계 기준으로 자른다.
        context = truncate_on_semantic_boundary(context, keep)
    return f"{prefix}{context}{suffix}"


# ── 파이프라인 ────────────────────────────────────────────────────────────────

class RagPipeline:
    def __init__(self, config: RagPipelineConfig) -> None:
        self._cfg = config
        self._generation = GenerationService(config.generation)
        # 요청마다 ThreadPoolExecutor를 새로 만들지 않고 파이프라인 인스턴스 단위로 재사용한다.
        # api/dependencies.py에서 RagPipeline은 lru_cache 싱글톤으로 관리된다.
        max_workers = max(2, len(config.retrieval.qdrant_collections) + 2)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    @classmethod
    def from_env(cls) -> RagPipeline:
        """환경변수에서 설정을 읽어 인스턴스를 생성한다."""
        raw_collections = os.getenv("QDRANT_COLLECTIONS", "").strip()
        if not raw_collections:
            raise RetrievalError("QDRANT_COLLECTIONS 환경변수가 필요합니다. 예: law_article,legal_case,legal_relation")
        collections = [c.strip() for c in raw_collections.split(",") if c.strip()]
        if not collections:
            raise RetrievalError("QDRANT_COLLECTIONS가 비어 있습니다.")

        # QDRANT_VECTOR_NAME_MAP=law_article=body,legal_case= 형식 파싱
        vector_name_map: dict[str, str] = {}
        raw_map = os.getenv("QDRANT_VECTOR_NAME_MAP", "")
        for entry in raw_map.split(","):
            entry = entry.strip()
            if "=" in entry:
                col, _, name = entry.partition("=")
                if col.strip() and name.strip():
                    vector_name_map[col.strip()] = name.strip()

        return cls(
            RagPipelineConfig(
                retrieval=RetrievalConfig(
                    qdrant_url=os.environ["QDRANT_URL"],
                    qdrant_collections=collections,
                    qdrant_vector_name_map=vector_name_map or None,
                    qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
                    opensearch_url=os.getenv("OPENSEARCH_URL", ""),
                    opensearch_indices=[i.strip() for i in os.getenv("OPENSEARCH_INDEX", "").split(",") if i.strip()],
                    opensearch_api_key=os.getenv("OPENSEARCH_API_KEY") or None,
                    opensearch_username=os.getenv("OPENSEARCH_USERNAME") or None,
                    opensearch_password=os.getenv("OPENSEARCH_PASSWORD") or None,
                    opensearch_search_text_field=os.getenv("OPENSEARCH_SEARCH_TEXT_FIELD", "search_text"),
                    embedding_model=os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
                    embedding_api_key=os.getenv("OPENAI_API_KEY") or None,
                    embedding_api_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                    embedding_dimensions=int(d) if (d := os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "").strip()) else None,
                ),
                generation=GenerationConfig.from_env(),
            )
        )

    def _retrieve(
        self,
        question: str,
        *,
        doc_types: list[str] | None,
        law_names: list[str] | None,
        intent: str | None = None,
        search_query: str | None = None,
        hypothetical_doc: str | None = None,
        trace: Any | None = None,
        top_k: int | None = None,
    ) -> tuple[list[dict[str, Any]], str, str, bool]:
        """검색 → 융합 → 순위 조정 → 컨텍스트 빌드.

        intent에 따라 law_names 필터 전략과 law 문서 보강 강제 여부를 조정한다.
          - case_law : 판례 중심 질의. law_names 필터 미적용, law 문서 강제 보강 해제.
          - mixed    : 법령+판례 혼합. law_names 유지하되 강제 보강 해제.
          - normative: 조문 중심 질의. 현재 동작 유지 (law_names 필터 + 강제 보강).
          - None     : 파서 미적용. 현재 동작 유지.

        Returns:
            (llm_rows, context_text, law_context_status, law_context_added)
        """
        rcfg = self._cfg.retrieval
        effective_top_k = top_k or rcfg.top_k
        candidate_k = max(effective_top_k, rcfg.candidate_k)

        if intent == "case_law":
            law_names = None
            enforce = False
            # 판례 중심 질의 — 법령 조문이 섞이지 않도록 판례류로만 제한
            if doc_types is None:
                doc_types = ["prec", "decc", "detc", "expc"]
                logger.info("intent=case_law: doc_types 미지정이어서 판례류로 제한 %s", doc_types)
        elif intent == "mixed":
            enforce = False
        else:
            enforce = self._cfg.enforce_min_law_contexts

        effective_search_query = search_query or question
        # normative intent이고 hypothetical_doc이 있으면 임베딩에 가상 조문 텍스트를 사용한다.
        # BM25는 키워드 매칭 특성상 normalized_query(effective_search_query)를 그대로 유지한다.
        embed_text = (
            hypothetical_doc
            if intent == "normative" and hypothetical_doc
            else effective_search_query
        )

        t0 = time.perf_counter()
        retrieval_span = start_span(
            trace, "retrieval",
            input={"question": question, "doc_types": doc_types, "law_names": law_names, "intent": intent},
        )

        # ── embed ──────────────────────────────────────────────────────────────
        embed_span = start_span(
            retrieval_span, "embed",
            input={"model": rcfg.embedding_model},
        )
        try:
            vector = embed_query(
                embed_text,
                rcfg.embedding_model,
                api_key=rcfg.embedding_api_key,
                api_base_url=rcfg.embedding_api_base_url,
                dimensions=rcfg.embedding_dimensions,
            )
        except Exception:
            end_span(embed_span, level="ERROR")
            end_span(retrieval_span, level="ERROR")
            raise
        t_embed = time.perf_counter() - t0
        logger.info("임베딩 완료: %.2fs", t_embed)
        end_span(embed_span, output={"dim": len(vector)}, level="DEFAULT")

        # ── qdrant + opensearch 병렬 실행 ──────────────────────────────────────
        # normative 쿼리에서 legal_relation 컬렉션은 그래프 탐색용 메타데이터라
        # 코사인 유사도가 높게 나와 실제 법령 조문을 candidate pool에서 밀어낸다.
        effective_collections = (
            [c for c in rcfg.qdrant_collections if c != "legal_relation"]
            if intent == "normative"
            else rcfg.qdrant_collections
        )

        def _qdrant_task(collection: str) -> list[dict[str, Any]]:
            return search_qdrant_with_vector(
                vector, candidate_k,
                qdrant_url=rcfg.qdrant_url,
                collection=collection,
                timeout=rcfg.timeout,
                api_key=rcfg.qdrant_api_key,
                doc_types=doc_types,
                law_names=law_names,
                dedup=True,
                fetch_multiplier=2,
                vector_name=(rcfg.qdrant_vector_name_map or {}).get(collection),
            )

        def _bm25_task() -> list[dict[str, Any]]:
            return search_bm25(
                effective_search_query, candidate_k,
                opensearch_url=rcfg.opensearch_url,
                index_name=rcfg.opensearch_indices,
                timeout=rcfg.timeout,
                api_key=rcfg.opensearch_api_key,
                username=rcfg.opensearch_username,
                password=rcfg.opensearch_password,
                doc_types=doc_types,
                law_names=law_names,
                dedup=True,
                fetch_multiplier=5,
                search_text_field=rcfg.opensearch_search_text_field,
            )

        # span을 submit 전에 생성해야 실제 실행 시작 시각이 반영된다.
        qdrant_span = start_span(
            retrieval_span, "qdrant",
            input={"collections": effective_collections, "candidate_k": candidate_k},
        )
        opensearch_span = start_span(
            retrieval_span, "opensearch",
            input={"index": rcfg.opensearch_indices, "candidate_k": candidate_k},
        )
        qdrant_futures = [
            self._executor.submit(_qdrant_task, col)
            for col in effective_collections
        ]
        bm25_future = self._executor.submit(_bm25_task) if rcfg.opensearch_url else None

        try:
            collection_rows = [f.result() for f in qdrant_futures]
        except Exception as exc:
            end_span(qdrant_span, output={"error": str(exc)}, level="ERROR")
            end_span(retrieval_span, level="ERROR")
            raise
        end_span(qdrant_span, output={"hits": [len(r) for r in collection_rows]}, level="DEFAULT")

        bm25_rows: list[dict[str, Any]] = []
        if bm25_future is not None:
            try:
                bm25_rows = bm25_future.result()
                end_span(opensearch_span, output={"hits": len(bm25_rows)}, level="DEFAULT")
            except RetrievalError as exc:
                logger.warning("BM25 검색 실패로 스킵: %s", exc)
                end_span(opensearch_span, output={"error": str(exc)}, level="WARNING")
        else:
            end_span(opensearch_span, output={"skipped": True}, level="DEFAULT")
        logger.info("검색 완료: %.2fs", time.perf_counter() - t0)

        # ── fusion ─────────────────────────────────────────────────────────────
        fusion_span = start_span(
            retrieval_span, "fusion",
            input={"rrf_k": rcfg.rrf_k, "candidate_k": candidate_k, "auto_law_boost": rcfg.auto_law_boost},
        )
        try:
            _is_normative_slot = intent == "normative" and "law_article" in effective_collections
            if _is_normative_slot:
                # normative 슬롯 기반: law_article 슬롯 상위 고정 + case 슬롯 후순위
                law_idx = effective_collections.index("law_article")
                law_article_rows = collection_rows[law_idx]
                non_law_col_rows = [r for i, r in enumerate(collection_rows) if i != law_idx]
                non_law_col_names = [c for i, c in enumerate(effective_collections) if i != law_idx]

                law_quota = max(1, round(effective_top_k * rcfg.normative_law_ratio))
                case_quota = effective_top_k - law_quota
                logger.info("normative slot: top_k=%d law_quota=%d case_quota=%d", effective_top_k, law_quota, case_quota)

                law_slots = rank_rows(law_article_rows)[:law_quota]
                case_merged = (
                    fuse_rrf_multi(non_law_col_rows, rrf_k=rcfg.rrf_k, top_k=candidate_k, backend_names=non_law_col_names)
                    if non_law_col_rows else []
                )
                case_fused = fuse_rrf(case_merged, bm25_rows, rrf_k=rcfg.rrf_k, top_k=candidate_k)
                case_slots = [r for r in case_fused if str(r.get("doc_type", "") or "") != "law"][:case_quota]

                rrf_rows = law_slots + case_slots
                for i, row in enumerate(rrf_rows, start=1):
                    row["rank"] = i
            else:
                qdrant_rows = fuse_rrf_multi(
                    collection_rows,
                    rrf_k=rcfg.rrf_k,
                    top_k=candidate_k,
                    backend_names=effective_collections,
                )
                # candidate_k 전체를 융합해야 law 보강 시 top_k 바깥 문서를 참조할 수 있음
                rrf_rows = fuse_rrf(qdrant_rows, bm25_rows, rrf_k=rcfg.rrf_k, top_k=candidate_k)
                rrf_rows = apply_law_boost(
                    rrf_rows,
                    intent=intent,
                    enabled=rcfg.auto_law_boost,
                    law_boost_score=rcfg.law_boost_score,
                )
        except Exception as exc:
            end_span(fusion_span, output={"error": str(exc)}, level="ERROR")
            end_span(retrieval_span, level="ERROR")
            raise
        rrf_rows = filter_noise_chunks(rrf_rows, min_text_len=rcfg.min_chunk_text_len)
        end_span(fusion_span, output={"fused_docs": len(rrf_rows)}, level="DEFAULT")

        # ── ranking ────────────────────────────────────────────────────────────
        ranking_span = start_span(
            retrieval_span, "ranking",
            input={"top_k": effective_top_k, "min_law_contexts": rcfg.min_law_contexts},
        )
        try:
            if _is_normative_slot:
                # 슬롯 할당으로 law 우선순위가 보장됨 — 보강 정책 불필요
                llm_rows = rrf_rows
                law_count_in = sum(1 for r in llm_rows if str(r.get("doc_type", "") or "") == "law")
                law_context_status = LAW_CONTEXT_OK if law_count_in > 0 else LAW_CONTEXT_MISSING
                law_context_added = law_count_in > 0
            else:
                llm_rows, law_context_status, law_context_added = select_rows_with_law_policy(
                    rrf_rows,
                    top_k=effective_top_k,
                    min_law_contexts=rcfg.min_law_contexts,
                    enforce_min_law_contexts=enforce,
                )
        except Exception as exc:
            end_span(ranking_span, output={"error": str(exc)}, level="ERROR")
            end_span(retrieval_span, level="ERROR")
            raise
        law_count = sum(1 for r in llm_rows if str(r.get("doc_type", "") or "") == "law")
        end_span(
            ranking_span,
            output={
                "selected_docs": len(llm_rows),
                "law_count": law_count,
                "non_law_count": len(llm_rows) - law_count,
                "law_context_status": law_context_status,
            },
            level="DEFAULT",
        )

        contexts = build_llm_context_rows(
            llm_rows,
            max_content_chars=rcfg.max_content_chars,
            max_total_chars=rcfg.max_total_chars,
        )
        context_text = build_llm_context_text(question, contexts, law_context_added)
        context_chars = len(context_text)
        logger.info(
            "retrieval 완료: %.2fs | docs=%d | law_count=%d | context_chars=%d | law_context_status=%s",
            time.perf_counter() - t0, len(llm_rows), law_count, context_chars, law_context_status,
        )
        end_span(
            retrieval_span,
            output={
                "docs": len(llm_rows),
                "law_count": law_count,
                "context_chars": context_chars,
                "law_context_status": law_context_status,
            },
            level="DEFAULT",
        )
        return llm_rows, context_text, law_context_status, law_context_added

    def _build_result(
        self,
        answer: str,
        llm_rows: list[dict[str, Any]],
        law_context_status: str,
    ) -> RagResult:
        snippet_max = self._cfg.snippet_max_chars
        def _snippet(row: dict[str, Any]) -> str:
            raw = str(row.get("snippet", "") or "")
            return raw[:snippet_max] if snippet_max > 0 else raw

        retrieved_docs = [
            {
                "rank": row.get("rank"),
                "source_id": str(row.get("source_id", "") or ""),
                "doc_type": str(row.get("doc_type", "") or ""),
                "law_name": str(row.get("law_name", "") or ""),
                "article_no": str(row.get("article_no", "") or ""),
                "score": row.get("score"),
                "snippet": _snippet(row),
                "text": str(row.get("text", "") or ""),
            }
            for row in llm_rows
        ]

        return RagResult(
            answer=answer,
            retrieved_docs=retrieved_docs,
            law_context_status=law_context_status,
        )

    def run(
        self,
        question: str,
        *,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
        doc_types: list[str] | None = None,
        law_names: list[str] | None = None,
        intent: str | None = None,
        search_query: str | None = None,
        hypothetical_doc: str | None = None,
        trace: Any | None = None,
        previous_question: str | None = None,
        previous_answer: str | None = None,
        top_k: int | None = None,
    ) -> RagResult:
        """검색 + 생성 파이프라인을 실행하고 최종 결과를 반환한다."""
        if trace is None:
            trace = start_trace(
                "qa_request",
                input={
                    "question": question,
                    "doc_types": doc_types,
                    "law_names": law_names,
                    "intent": intent,
                },
            )
        try:
            llm_rows, context_text, law_context_status = self._prepare_generation(
                question, doc_types=doc_types, law_names=law_names, intent=intent,
                search_query=search_query, hypothetical_doc=hypothetical_doc, trace=trace, top_k=top_k,
            )
            if not llm_rows:
                logger.info("run: 검색 결과 0건 — LLM 호출 생략")
                result = self._build_result(_NO_RESULT_ANSWER, [], law_context_status)
                update_trace(trace, output={"answer": _NO_RESULT_ANSWER}, level="DEFAULT")
                return result
            prompt = self._build_prompt(
                question, context_text, law_context_status,
                previous_question=previous_question,
                previous_answer=previous_answer,
            )
            cfg = self._generation._cfg
            gen_span = start_generation_span(
                trace, "generation",
                model=cfg.model,
                model_parameters={"temperature": cfg.temperature, "max_tokens": cfg.max_tokens},
                input=prompt,
            )
            t_gen = time.perf_counter()
            try:
                gen_result = self._generation.generate(prompt, system_prompt=system_prompt)
            except Exception:
                end_span(gen_span, level="ERROR")
                raise
            logger.info("generation 완료: %.2fs", time.perf_counter() - t_gen)
            end_span(
                gen_span,
                output=gen_result.answer,
                usage=gen_result.usage,
                level="DEFAULT",
            )
            result = self._build_result(gen_result.answer, llm_rows, law_context_status)
            update_trace(
                trace,
                output={"answer": gen_result.answer, "law_context_status": law_context_status},
                level="DEFAULT",
            )
            score_trace(
                get_trace_id(trace) or "",
                name="law_context_quality",
                value=_LAW_CONTEXT_SCORES.get(law_context_status, 0.0),
                comment=law_context_status,
            )
            return result
        except Exception:
            update_trace(trace, level="ERROR")
            raise

    def stream(
        self,
        question: str,
        *,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
        doc_types: list[str] | None = None,
        law_names: list[str] | None = None,
        intent: str | None = None,
        search_query: str | None = None,
        hypothetical_doc: str | None = None,
        trace: Any | None = None,
        previous_question: str | None = None,
        previous_answer: str | None = None,
        top_k: int | None = None,
    ) -> tuple[RagResult, Iterator[str]]:
        """검색 후 생성을 스트리밍으로 반환한다.

        Returns:
            (meta, chunks): meta는 sources 등 메타데이터, chunks는 토큰 조각 이터레이터.
        """
        if trace is None:
            trace = start_trace(
                "qa_request",
                input={
                    "question": question,
                    "doc_types": doc_types,
                    "law_names": law_names,
                    "intent": intent,
                },
            )
        try:
            llm_rows, context_text, law_context_status = self._prepare_generation(
                question, doc_types=doc_types, law_names=law_names, intent=intent,
                search_query=search_query, hypothetical_doc=hypothetical_doc, trace=trace, top_k=top_k,
            )
            if not llm_rows:
                logger.info("stream: 검색 결과 0건 — LLM 호출 생략")
                meta = self._build_result(_NO_RESULT_ANSWER, [], law_context_status)
                update_trace(trace, output={"answer": _NO_RESULT_ANSWER}, level="DEFAULT")
                return meta, iter([_NO_RESULT_ANSWER])
            prompt = self._build_prompt(
                question, context_text, law_context_status,
                previous_question=previous_question,
                previous_answer=previous_answer,
            )
            cfg = self._generation._cfg
            gen_span = start_generation_span(
                trace, "generation",
                model=cfg.model,
                model_parameters={"temperature": cfg.temperature, "max_tokens": cfg.max_tokens},
                input=prompt,
            )
            usage_out: dict[str, int] = {}
            raw_chunks = self._generation.stream(prompt, system_prompt=system_prompt, usage_out=usage_out)
            meta = self._build_result("", llm_rows, law_context_status)
            return meta, self._traced_stream(raw_chunks, gen_span, trace, law_context_status, usage_out)
        except Exception:
            update_trace(trace, level="ERROR")
            raise

    def _traced_stream(
        self,
        chunks: Iterator[str],
        gen_span: Any,
        trace: Any,
        law_context_status: str,
        usage_out: dict[str, int],
    ) -> Iterator[str]:
        """chunk를 yield하면서 스트림 종료 시 generation span과 trace를 닫는 래퍼."""
        answer_parts: list[str] = []
        try:
            for chunk in chunks:
                answer_parts.append(chunk)
                yield chunk
            answer = "".join(answer_parts)
            end_span(gen_span, output=answer, usage=usage_out or None, level="DEFAULT")
            update_trace(
                trace,
                output={"answer": answer, "law_context_status": law_context_status},
                level="DEFAULT",
            )
            score_trace(
                get_trace_id(trace) or "",
                name="law_context_quality",
                value=_LAW_CONTEXT_SCORES.get(law_context_status, 0.0),
                comment=law_context_status,
            )
        except Exception:
            end_span(gen_span, level="ERROR")
            update_trace(trace, level="ERROR")
            raise

    def _build_prompt(
        self,
        question: str,
        context_text: str,
        law_context_status: str,
        previous_question: str | None = None,
        previous_answer: str | None = None,
    ) -> str:
        return build_user_prompt_with_limit(
            retrieved_context_text=context_text,
            question=question,
            max_input_chars=self._cfg.max_input_chars,
            law_context_status=law_context_status,
            previous_question=previous_question,
            previous_answer=previous_answer,
        )

    def _prepare_generation(
        self,
        question: str,
        *,
        doc_types: list[str] | None,
        law_names: list[str] | None,
        intent: str | None,
        search_query: str | None = None,
        hypothetical_doc: str | None = None,
        trace: Any | None = None,
        top_k: int | None = None,
    ) -> tuple[list[dict[str, Any]], str, str]:
        llm_rows, context_text, law_context_status, _ = self._retrieve(
            question, doc_types=doc_types, law_names=law_names, intent=intent,
            search_query=search_query, hypothetical_doc=hypothetical_doc, trace=trace, top_k=top_k,
        )
        return llm_rows, context_text, law_context_status
