from pydantic import BaseModel, Field

from typing import Literal


class RiskItem(BaseModel):
    """A single risk identified in a contract article."""
    clause_text: str = Field(description="문제가 되는 조항 텍스트 (formatted_str에서 정확히 복사)")
    risk_type: Literal["법령위반", "불공정", "불명확", "편무적", "누락"] = Field(
        description="리스크 유형"
    )
    severity: Literal["high", "medium", "low"] = Field(description="심각도")
    explanation: str = Field(description="왜 문제인지 설명")
    needs_search: bool = Field(default=False, description="관련 법령 검색이 필요한지")
    search_query: str = Field(default="", description="검색이 필요하면 검색 쿼리")
    legal_basis: str = Field(default="", description="관련 법령 근거 (검색 후 채워짐)")


class RiskAnalysisResult(BaseModel):
    """Structured LLM output for risk analysis."""
    reasoning: str = Field(description="분석 근거. 여기를 먼저 채워넣으세요!")
    risks: list[RiskItem] = Field(default_factory=list, description="발견된 리스크 목록")


class ArticleRiskReport(BaseModel):
    """Per-article final risk report."""
    group_idx: int
    article_n: str
    risks: list[RiskItem] = Field(default_factory=list)
    referenced_laws: str = ""
    disclaimer: str = "본 분석은 AI 참고의견이며, 법적 효력이 없습니다."
