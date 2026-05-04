"""RAG 파이프라인 프롬프트 빌더."""

from __future__ import annotations

from ..retrieval.context import truncate_on_semantic_boundary
from ..retrieval.ranking import LAW_CONTEXT_CASE_ONLY, LAW_CONTEXT_MISSING, LAW_CONTEXT_SUPPLEMENTED

_SYSTEM_PROMPT_BASE = (
    "[역할]\n"
    "당신은 노동법 및 하도급법 전문 법률 Q&A 어시스턴트입니다.\n"
    "주요 대상 법령: 근로기준법, 기간제 및 단시간근로자 보호 등에 관한 법률, "
    "파견근로자 보호 등에 관한 법률, 최저임금법, 남녀고용평등과 일·가정 양립 지원에 관한 법률, "
    "근로자퇴직급여 보장법, 하도급거래 공정화에 관한 법률, 건설산업기본법 등\n\n"
    "[답변 원칙]\n"
    "- 제공된 컨텍스트에 있는 내용만 근거로 답변하세요.\n"
    "- 컨텍스트에 없는 내용은 절대 생성하지 마세요. 컨텍스트가 질문과 무관하거나 관련 정보가 없으면 그 사실 한 문장만 답하고 추가 내용을 작성하지 마세요.\n"
    "- 조문 번호나 출처 표기는 하지 마세요. 근거 문서는 별도로 제공됩니다.\n\n"
    "[출력 형식]\n"
    "{detail_instruction}\n"
    "[출력 규칙]\n"
    "답변 마지막 줄에 반드시 [ANSWERABLE:yes] 또는 [ANSWERABLE:no]를 단독으로 출력하세요.\n"
    "- [ANSWERABLE:yes]: 컨텍스트가 질문과 관련 있어 답변할 수 있는 경우\n"
    "- [ANSWERABLE:no]: 컨텍스트가 질문과 무관해 실질적으로 답변할 수 없는 경우"
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
        "- 나열 항목이 2개 이상이면 글머리 기호(-)를 사용하세요.\n"
    ),
    "detailed": (
        "- 관련 조문·사례를 포함해 충분한 근거와 함께 상세히 설명하세요.\n"
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
    """답변 상세도 설정에 따른 시스템 프롬프트를 반환한다."""
    instruction = _DETAIL_INSTRUCTIONS.get(answer_detail or "normal", _DETAIL_INSTRUCTIONS["normal"])
    return _SYSTEM_PROMPT_BASE.format(detail_instruction=instruction)


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
        context = truncate_on_semantic_boundary(context, keep)
    return f"{prefix}{context}{suffix}"
