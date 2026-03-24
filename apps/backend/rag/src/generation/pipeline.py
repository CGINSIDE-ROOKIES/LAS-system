"""RAG 파이프라인 서비스.

retrieval → context → prompt → generation 전체 흐름을 조립한다.
API 레이어는 RagPipeline.run() / RagPipeline.stream()만 호출하면 된다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterator

from ..retrieval.common import DEFAULT_EMBEDDING_MODEL, RetrievalError
from ..retrieval.context import build_llm_context_rows, build_llm_context_text
from ..retrieval.fusion import fuse_rrf
from ..retrieval.opensearch import search_bm25
from ..retrieval.qdrant import search_qdrant
from ..retrieval.ranking import apply_law_boost, select_rows_with_law_policy
from ..retrieval.service import RetrievalConfig
from .service import GenerationConfig, GenerationService

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
    max_input_chars: int = 12000
    snippet_max_chars: int = 200


@dataclass
class RagResult:
    """run() 반환값. API 응답으로 직렬화한다."""

    answer: str
    retrieved_docs: list[dict[str, Any]]  # 컨텍스트에 사용된 문서 목록
    law_context_status: str               # "ok" | "missing" | "supplemented"


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
    if law_context_status == "missing":
        status_line = (
            "중요: 현재 검색 결과에서 법령(law) 근거가 충분하지 않습니다.\n"
            "확정적 결론 대신 근거 부족을 명시하고, 확인 가능한 범위만 답변하세요.\n\n"
        )
    elif law_context_status == "supplemented":
        status_line = "참고: 법령(law) 문서를 보강한 컨텍스트로 답변합니다.\n\n"

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
        context = context[:keep]
    return f"{prefix}{context}{suffix}"


# ── 파이프라인 ────────────────────────────────────────────────────────────────

class RagPipeline:
    def __init__(self, config: RagPipelineConfig) -> None:
        self._cfg = config
        self._generation = GenerationService(config.generation)

    @classmethod
    def from_env(cls) -> RagPipeline:
        """환경변수에서 설정을 읽어 인스턴스를 생성한다."""
        raw_collections = os.environ["QDRANT_COLLECTIONS"]
        collections = [c.strip() for c in raw_collections.split(",") if c.strip()]

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
                    embedding_model=os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
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
    ) -> tuple[list[dict[str, Any]], str, str, bool]:
        """검색 → 융합 → 순위 조정 → 컨텍스트 빌드.

        Returns:
            (llm_rows, context_text, law_context_status, law_context_added)
        """
        rcfg = self._cfg.retrieval
        candidate_k = max(rcfg.top_k, rcfg.candidate_k)

        qdrant_rows: list[dict[str, Any]] = []
        for collection in rcfg.qdrant_collections:
            rows = search_qdrant(
                question, candidate_k,
                qdrant_url=rcfg.qdrant_url,
                collection=collection,
                timeout=rcfg.timeout,
                embedding_model=rcfg.embedding_model,
                api_key=rcfg.qdrant_api_key,
                doc_types=doc_types,
                law_names=law_names,
                dedup=True,
                fetch_multiplier=2,
                vector_name=(rcfg.qdrant_vector_name_map or {}).get(collection),
            )
            qdrant_rows.extend(rows)

        # 컬렉션 간 score 기준으로 재정렬 후 rank 재부여
        qdrant_rows.sort(key=lambda r: r.get("score") or 0.0, reverse=True)
        for i, row in enumerate(qdrant_rows, start=1):
            row["rank"] = i

        if rcfg.opensearch_url:
            try:
                bm25_rows = search_bm25(
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
                )
            except RetrievalError:
                bm25_rows = []
        else:
            bm25_rows = []

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
            enforce_min_law_contexts=self._cfg.enforce_min_law_contexts,
        )

        contexts = build_llm_context_rows(
            llm_rows,
            max_content_chars=rcfg.max_content_chars,
            max_total_chars=rcfg.max_total_chars,
        )
        context_text = build_llm_context_text(question, contexts, law_context_added)

        return llm_rows, context_text, law_context_status, law_context_added

    def _build_result(
        self,
        answer: str,
        llm_rows: list[dict[str, Any]],
        law_context_status: str,
    ) -> RagResult:
        snippet_max = self._cfg.snippet_max_chars

        retrieved_docs = [
            {
                "rank": row.get("rank"),
                "source_id": str(row.get("source_id", "") or ""),
                "doc_type": str(row.get("doc_type", "") or ""),
                "law_name": str(row.get("law_name", "") or ""),
                "score": row.get("score"),
                "snippet": str(row.get("snippet", "") or "")[:snippet_max] if snippet_max > 0 else str(row.get("snippet", "") or ""),
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
    ) -> RagResult:
        """검색 + 생성 파이프라인을 실행하고 최종 결과를 반환한다."""
        llm_rows, context_text, law_context_status, law_context_added = self._retrieve(
            question, doc_types=doc_types, law_names=law_names
        )
        prompt = build_user_prompt_with_limit(
            retrieved_context_text=context_text,
            question=question,
            max_input_chars=self._cfg.max_input_chars,
            law_context_status=law_context_status,
        )
        result = self._generation.generate(prompt, system_prompt=system_prompt)
        return self._build_result(result.answer, llm_rows, law_context_status)

    def stream(
        self,
        question: str,
        *,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
        doc_types: list[str] | None = None,
        law_names: list[str] | None = None,
    ) -> tuple[RagResult, Iterator[str]]:
        """검색 후 생성을 스트리밍으로 반환한다.

        Returns:
            (meta, chunks): meta는 sources 등 메타데이터, chunks는 토큰 조각 이터레이터.
        """
        llm_rows, context_text, law_context_status, law_context_added = self._retrieve(
            question, doc_types=doc_types, law_names=law_names
        )
        prompt = build_user_prompt_with_limit(
            retrieved_context_text=context_text,
            question=question,
            max_input_chars=self._cfg.max_input_chars,
            law_context_status=law_context_status,
        )
        meta = self._build_result("", llm_rows, law_context_status)
        return meta, self._generation.stream(prompt, system_prompt=system_prompt)
