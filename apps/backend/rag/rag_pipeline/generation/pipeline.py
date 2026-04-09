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

from ..observability.tracing import start_trace, update_trace
from ..retrieval.common import DEFAULT_EMBEDDING_MODEL, RetrievalError, embed_query, is_embedding_model_cached
from ..retrieval.context import build_llm_context_rows, build_llm_context_text, truncate_on_semantic_boundary
from ..retrieval.fusion import fuse_rrf, fuse_rrf_multi
from ..retrieval.opensearch import search_bm25
from ..retrieval.qdrant import search_qdrant_with_vector
from ..retrieval.ranking import (
    LAW_CONTEXT_CASE_ONLY,
    LAW_CONTEXT_MISSING,
    LAW_CONTEXT_SUPPLEMENTED,
    apply_law_boost,
    select_rows_with_law_policy,
)
from ..retrieval.service import RetrievalConfig
from .service import GenerationConfig, GenerationService

_NO_RESULT_ANSWER = (
    "관련 법령·판례 문서를 찾지 못했습니다. "
    "질문을 더 구체적으로 입력하시거나, 법령 필터가 설정되어 있다면 해제 후 다시 시도해보세요."
)

DEFAULT_SYSTEM_PROMPT = (
    "당신은 노동법 및 하도급법 전문 법률 Q&A 어시스턴트입니다.\n"
    "주요 대상 법령은 근로기준법, 기간제 및 단시간근로자 보호 등에 관한 법률, "
    "파견근로자 보호 등에 관한 법률, 최저임금법, 남녀고용평등과 일·가정 양립 지원에 관한 법률, "
    "근로자퇴직급여 보장법, 하도급거래 공정화에 관한 법률, 건설산업기본법 등입니다.\n\n"
    "답변 시 다음 원칙을 따르세요:\n"
    "- 제공된 컨텍스트에 있는 내용만 근거로 답변하세요.\n"
    "- 조문 번호나 출처 표기는 하지 마세요. 근거 문서는 별도로 제공됩니다.\n"
    "- 핵심 내용을 3~5문장 이내로 간결하게 전달하세요.\n"
    "- 컨텍스트에 없는 사실은 추측하거나 단정하지 말고, 근거가 부족한 경우 한 문장으로 짧게 밝히세요.\n"
    "- 전문적이되 자연스러운 구어체로 작성하세요."
)


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
) -> str:
    """system_prompt를 제외한 user 메시지 본문(컨텍스트 + 질문)을 조립한다."""
    status_line = ""
    if law_context_status == LAW_CONTEXT_MISSING:
        status_line = (
            "중요: 현재 검색 결과에서 법령(law) 근거가 충분하지 않습니다.\n"
            "확정적 결론 대신 근거 부족을 명시하고, 확인 가능한 범위만 답변하세요.\n\n"
        )
    elif law_context_status == LAW_CONTEXT_SUPPLEMENTED:
        status_line = "참고: 법령(law) 문서를 보강한 컨텍스트로 답변합니다.\n\n"
    elif law_context_status == LAW_CONTEXT_CASE_ONLY:
        status_line = "참고: 현재 검색 결과에 법령 조문이 없고 판례·해석례만 포함되어 있습니다.\n조문 근거 없이 판례 중심으로 답변하세요.\n\n"

    prefix = (
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
                    opensearch_index=os.getenv("OPENSEARCH_INDEX", ""),
                    opensearch_api_key=os.getenv("OPENSEARCH_API_KEY") or None,
                    opensearch_username=os.getenv("OPENSEARCH_USERNAME") or None,
                    opensearch_password=os.getenv("OPENSEARCH_PASSWORD") or None,
                    opensearch_search_text_field=os.getenv("OPENSEARCH_SEARCH_TEXT_FIELD", "search_text"),
                    embedding_model=os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
                    embedding_provider=os.getenv("EMBEDDING_PROVIDER", "sentence_transformers"),
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
        candidate_k = max(rcfg.top_k, rcfg.candidate_k)

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

        t0 = time.perf_counter()

        # 임베딩을 한 번만 계산한 뒤 Qdrant(복수 컬렉션) + OpenSearch를 병렬 실행한다.
        vector = embed_query(
            question,
            rcfg.embedding_model,
            provider=rcfg.embedding_provider,
            api_key=rcfg.embedding_api_key,
            api_base_url=rcfg.embedding_api_base_url,
            dimensions=rcfg.embedding_dimensions,
        )
        logger.info("임베딩 완료: %.2fs", time.perf_counter() - t0)

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
                question, candidate_k,
                opensearch_url=rcfg.opensearch_url,
                index_name=rcfg.opensearch_index,
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

        qdrant_futures = [
            self._executor.submit(_qdrant_task, col)
            for col in rcfg.qdrant_collections
        ]
        bm25_future = self._executor.submit(_bm25_task) if rcfg.opensearch_url else None

        collection_rows = [f.result() for f in qdrant_futures]

        bm25_rows: list[dict[str, Any]] = []
        if bm25_future is not None:
            try:
                bm25_rows = bm25_future.result()
            except RetrievalError as exc:
                logger.warning("BM25 검색 실패로 스킵: %s", exc)
                bm25_rows = []

        qdrant_rows = fuse_rrf_multi(
            collection_rows,
            rrf_k=rcfg.rrf_k,
            top_k=candidate_k,
            backend_names=rcfg.qdrant_collections,
        )

        # candidate_k 전체를 융합해야 law 보강 시 top_k 바깥 문서를 참조할 수 있음
        rrf_rows = fuse_rrf(qdrant_rows, bm25_rows, rrf_k=rcfg.rrf_k, top_k=candidate_k)
        rrf_rows = apply_law_boost(
            rrf_rows,
            question=question,
            enabled=rcfg.auto_law_boost,
            law_boost_score=rcfg.law_boost_score,
        )

        llm_rows, law_context_status, law_context_added = select_rows_with_law_policy(
            rrf_rows,
            top_k=rcfg.top_k,
            min_law_contexts=rcfg.min_law_contexts,
            enforce_min_law_contexts=enforce,
        )

        contexts = build_llm_context_rows(
            llm_rows,
            max_content_chars=rcfg.max_content_chars,
            max_total_chars=rcfg.max_total_chars,
        )
        context_text = build_llm_context_text(question, contexts, law_context_added)
        logger.info(
            "retrieval 완료: %.2fs | docs=%d | law_context_status=%s",
            time.perf_counter() - t0, len(llm_rows), law_context_status,
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

    def is_embedding_cold_start(self) -> bool:
        """현재 프로세스에서 임베딩 모델 첫 로드가 필요한 상태인지 반환한다."""
        return not is_embedding_model_cached(
            self._cfg.retrieval.embedding_model,
            provider=self._cfg.retrieval.embedding_provider,
        )

    def run(
        self,
        question: str,
        *,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
        doc_types: list[str] | None = None,
        law_names: list[str] | None = None,
        intent: str | None = None,
        trace: Any | None = None,
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
                question, doc_types=doc_types, law_names=law_names, intent=intent
            )
            if not llm_rows:
                logger.info("run: 검색 결과 0건 — LLM 호출 생략")
                result = self._build_result(_NO_RESULT_ANSWER, [], law_context_status)
                update_trace(trace, output={"answer": _NO_RESULT_ANSWER}, level="DEFAULT")
                return result
            prompt = self._build_prompt(question, context_text, law_context_status)
            t_gen = time.perf_counter()
            gen_result = self._generation.generate(prompt, system_prompt=system_prompt)
            logger.info("generation 완료: %.2fs", time.perf_counter() - t_gen)
            result = self._build_result(gen_result.answer, llm_rows, law_context_status)
            update_trace(
                trace,
                output={"answer": gen_result.answer, "law_context_status": law_context_status},
                level="DEFAULT",
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
        trace: Any | None = None,
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
                question, doc_types=doc_types, law_names=law_names, intent=intent
            )
            if not llm_rows:
                logger.info("stream: 검색 결과 0건 — LLM 호출 생략")
                meta = self._build_result(_NO_RESULT_ANSWER, [], law_context_status)
                update_trace(trace, output={"answer": _NO_RESULT_ANSWER}, level="DEFAULT")
                return meta, iter([_NO_RESULT_ANSWER])
            prompt = self._build_prompt(question, context_text, law_context_status)
            meta = self._build_result("", llm_rows, law_context_status)
            # 스트리밍 출력 기록은 5단계(streaming 응답 종료 시 최종 결과 기록)에서 처리한다.
            return meta, self._generation.stream(prompt, system_prompt=system_prompt)
        except Exception:
            update_trace(trace, level="ERROR")
            raise

    def _build_prompt(self, question: str, context_text: str, law_context_status: str) -> str:
        return build_user_prompt_with_limit(
            retrieved_context_text=context_text,
            question=question,
            max_input_chars=self._cfg.max_input_chars,
            law_context_status=law_context_status,
        )

    def _prepare_generation(
        self,
        question: str,
        *,
        doc_types: list[str] | None,
        law_names: list[str] | None,
        intent: str | None,
    ) -> tuple[list[dict[str, Any]], str, str]:
        llm_rows, context_text, law_context_status, _ = self._retrieve(
            question, doc_types=doc_types, law_names=law_names, intent=intent
        )
        return llm_rows, context_text, law_context_status
