from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from .api import parse_document, render_review_html
from .api_types import (
    ClauseSummary,
    DocumentInput,
    ParagraphPreview,
    ParseDocumentResult,
    TextAnnotation,
    TextEdit,
)
from .parser_types import RelevanceMode

Severity = Literal["info", "low", "medium", "high", "critical"]
SuggestionStatus = Literal["pending", "accepted", "rejected", "feedback"]

_SEVERITY_COLORS: dict[Severity, str] = {
    "info": "#DBEAFE",
    "low": "#D9F99D",
    "medium": "#FEF08A",
    "high": "#FDBA74",
    "critical": "#FCA5A5",
}

_CONTRACT_REVIEW_SYSTEM_PROMPT = """You are a legal contract review assistant.
Review one contract clause at a time using only the supplied legal RAG evidence.
Return strict JSON only. Do not include markdown, prose, or unsupported claims.
If the evidence does not show a concrete legal or drafting risk, return {"findings":[]}.
Each finding must cite source_ids from the evidence and must preserve human control:
recommend edits, but do not imply they should be applied without user approval."""


class RagEvidenceClient(Protocol):
    def query_legal_db(
        self,
        query: str,
        *,
        doc_types: list[str] | None = None,
        law_names: list[str] | None = None,
        intent: str | None = None,
        search_query: str | None = None,
        hypothetical_doc: str | None = None,
        top_k: int | None = None,
    ) -> Mapping[str, Any]:
        ...


class ReviewGenerationClient(Protocol):
    def generate(self, prompt: str, *, system_prompt: str | None = None) -> Any:
        ...


class ContractReviewConfig(BaseModel):
    top_k: int = Field(default=8, ge=1, le=50)
    max_clauses: int | None = Field(default=None, ge=1)
    max_clause_chars: int = Field(default=4000, ge=500)
    max_source_text_chars: int = Field(default=1200, ge=100)
    max_sources_per_finding: int = Field(default=3, ge=1)
    doc_types: list[str] | None = Field(default_factory=lambda: ["law", "prec", "detc", "decc", "expc"])
    law_names: list[str] | None = None
    include_review_html: bool = True
    review_title: str = "Contract Review"


class ReviewContractRequest(BaseModel):
    document: DocumentInput | None = None
    source_path: str | None = None
    relevance_mode: RelevanceMode = RelevanceMode.KEYWORD_THEN_LLM
    boundary_review_enabled: bool = True
    label_review_enabled: bool = True
    prompt_profile: str = "default"
    config: ContractReviewConfig = Field(default_factory=ContractReviewConfig)

    @model_validator(mode="after")
    def _validate_source(self) -> "ReviewContractRequest":
        if self.document is not None and self.source_path is not None:
            raise ValueError("Specify either document or source_path, not both.")
        if self.document is None and self.source_path is None:
            raise ValueError("Provide either document or source_path.")
        return self


class ContractReviewSource(BaseModel):
    rank: int | None = None
    source_id: str
    doc_type: str = ""
    law_name: str = ""
    article_no: str = ""
    citation: str = ""
    snippet: str = ""
    text: str = ""
    score: int | float | str | None = None


class ContractReviewFinding(BaseModel):
    finding_id: str
    clause_id: str
    clause_no: str | None = None
    target_node_ids: list[str] = Field(default_factory=list)
    severity: Severity = "medium"
    issue_type: str = "contract_risk"
    title: str
    problematic_text: str = ""
    rationale: str
    recommendation: str
    sources: list[ContractReviewSource] = Field(default_factory=list)
    annotation: TextAnnotation | None = None
    proposed_edit: TextEdit | None = None
    status: SuggestionStatus = "pending"


class ClauseReviewResult(BaseModel):
    clause_id: str
    clause_no: str | None = None
    title: str | None = None
    target_node_ids: list[str] = Field(default_factory=list)
    query: str
    law_context_status: str = ""
    source_count: int = 0
    findings: list[ContractReviewFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ContractReviewResult(BaseModel):
    parse_result: ParseDocumentResult
    clause_reviews: list[ClauseReviewResult] = Field(default_factory=list)
    findings: list[ContractReviewFinding] = Field(default_factory=list)
    review_html: str | None = None
    warnings: list[str] = Field(default_factory=list)


def review_contract_document(
    request: ReviewContractRequest,
    *,
    rag_client: RagEvidenceClient,
    generation_client: ReviewGenerationClient,
) -> ContractReviewResult:
    parse_result = parse_document(
        document=request.document,
        source_path=request.source_path,
        relevance_mode=request.relevance_mode,
        boundary_review_enabled=request.boundary_review_enabled,
        label_review_enabled=request.label_review_enabled,
        prompt_profile=request.prompt_profile,
        include_paragraphs=True,
        include_clauses=True,
        include_editable_targets=False,
        max_paragraphs=None,
        paragraph_excerpt_length=None,
    )
    return review_parsed_contract(
        parse_result,
        rag_client=rag_client,
        generation_client=generation_client,
        config=request.config,
        render_document=request.document,
        render_source_path=request.source_path,
    )


def review_parsed_contract(
    parse_result: ParseDocumentResult,
    *,
    rag_client: RagEvidenceClient,
    generation_client: ReviewGenerationClient,
    config: ContractReviewConfig | None = None,
    render_document: DocumentInput | None = None,
    render_source_path: str | None = None,
) -> ContractReviewResult:
    cfg = config or ContractReviewConfig()
    paragraph_by_id = {paragraph.node_id: paragraph for paragraph in parse_result.paragraphs}
    clause_units = _review_clause_units(parse_result, paragraph_by_id, cfg)
    clause_reviews: list[ClauseReviewResult] = []
    warnings: list[str] = []

    for clause, paragraphs in clause_units:
        clause_text = _clause_text(clause, paragraphs, cfg.max_clause_chars)
        if not clause_text.strip():
            clause_reviews.append(
                ClauseReviewResult(
                    clause_id=clause.clause_id,
                    clause_no=clause.clause_no,
                    title=clause.title,
                    target_node_ids=clause.member_node_ids,
                    query="",
                    warnings=["Clause has no reviewable text."],
                )
            )
            continue

        query = _build_rag_query(clause, clause_text)
        evidence_result = rag_client.query_legal_db(
            query,
            doc_types=cfg.doc_types,
            law_names=cfg.law_names,
            intent="normative",
            search_query=clause_text,
            top_k=cfg.top_k,
        )
        sources = _sources_from_evidence(evidence_result, cfg)
        prompt = _build_generation_prompt(clause, paragraphs, sources)
        answer = _generation_answer(
            generation_client.generate(prompt, system_prompt=_CONTRACT_REVIEW_SYSTEM_PROMPT)
        )
        payload, parse_warning = _parse_generation_payload(answer)
        clause_warnings = [parse_warning] if parse_warning else []
        findings = _findings_from_payload(
            payload,
            clause=clause,
            paragraphs=paragraphs,
            sources=sources,
            max_sources=cfg.max_sources_per_finding,
        )
        clause_reviews.append(
            ClauseReviewResult(
                clause_id=clause.clause_id,
                clause_no=clause.clause_no,
                title=clause.title,
                target_node_ids=clause.member_node_ids,
                query=query,
                law_context_status=str(evidence_result.get("law_context_status", "") or ""),
                source_count=len(sources),
                findings=findings,
                warnings=clause_warnings,
            )
        )
        warnings.extend(clause_warnings)

    findings = [finding for review in clause_reviews for finding in review.findings]
    review_html = _render_findings_html(
        findings,
        cfg=cfg,
        render_document=render_document,
        render_source_path=render_source_path,
        warnings=warnings,
    )
    return ContractReviewResult(
        parse_result=parse_result,
        clause_reviews=clause_reviews,
        findings=findings,
        review_html=review_html,
        warnings=warnings,
    )


def _review_clause_units(
    parse_result: ParseDocumentResult,
    paragraph_by_id: dict[str, ParagraphPreview],
    cfg: ContractReviewConfig,
) -> list[tuple[ClauseSummary, list[ParagraphPreview]]]:
    clauses = parse_result.clauses
    if cfg.max_clauses is not None:
        clauses = clauses[: cfg.max_clauses]
    if clauses:
        return [
            (
                clause,
                [paragraph_by_id[node_id] for node_id in clause.member_node_ids if node_id in paragraph_by_id],
            )
            for clause in clauses
        ]
    paragraph_ids = [paragraph.node_id for paragraph in parse_result.paragraphs]
    if not paragraph_ids:
        return []
    fallback = ClauseSummary(
        clause_id="document",
        clause_no="",
        title="Document",
        start_node_id=paragraph_ids[0],
        end_node_id=paragraph_ids[-1],
        member_node_ids=paragraph_ids,
    )
    return [(fallback, parse_result.paragraphs)]


def _clause_text(clause: ClauseSummary, paragraphs: Sequence[ParagraphPreview], max_chars: int) -> str:
    lines = []
    heading = " ".join(part for part in (clause.clause_no, clause.title) if part)
    if heading:
        lines.append(heading)
    for paragraph in paragraphs:
        text = paragraph.text_excerpt.strip()
        if text:
            lines.append(f"[{paragraph.node_id}] {text}")
    joined = "\n".join(lines)
    return joined[:max_chars]


def _build_rag_query(clause: ClauseSummary, clause_text: str) -> str:
    label = " ".join(part for part in (clause.clause_no, clause.title) if part).strip()
    return (
        "계약 조항의 법적 위험과 불공정하거나 문제될 수 있는 부분을 검토해 주세요.\n"
        f"조항: {label or clause.clause_id}\n"
        f"조항 내용:\n{clause_text}"
    )


def _sources_from_evidence(evidence_result: Mapping[str, Any], cfg: ContractReviewConfig) -> list[ContractReviewSource]:
    documents = evidence_result.get("documents") or []
    sources: list[ContractReviewSource] = []
    for raw in documents:
        if not isinstance(raw, Mapping):
            continue
        text = str(raw.get("text", "") or "")
        sources.append(
            ContractReviewSource(
                rank=_as_int(raw.get("rank")),
                source_id=str(raw.get("source_id", "") or ""),
                doc_type=str(raw.get("doc_type", "") or ""),
                law_name=str(raw.get("law_name", "") or ""),
                article_no=str(raw.get("article_no", "") or ""),
                citation=str(raw.get("citation", "") or ""),
                snippet=str(raw.get("snippet", "") or ""),
                text=text[: cfg.max_source_text_chars],
                score=raw.get("score"),
            )
        )
    return sources


def _build_generation_prompt(
    clause: ClauseSummary,
    paragraphs: Sequence[ParagraphPreview],
    sources: Sequence[ContractReviewSource],
) -> str:
    evidence = [
        {
            "source_id": source.source_id,
            "citation": source.citation,
            "doc_type": source.doc_type,
            "law_name": source.law_name,
            "article_no": source.article_no,
            "snippet": source.snippet,
            "text": source.text,
        }
        for source in sources
    ]
    paragraph_payload = [
        {
            "node_id": paragraph.node_id,
            "text": paragraph.text_excerpt,
            "clause_id": paragraph.clause_id,
            "subclause_id": paragraph.subclause_id,
        }
        for paragraph in paragraphs
    ]
    schema = {
        "findings": [
            {
                "severity": "info|low|medium|high|critical",
                "issue_type": "short machine label",
                "title": "short user-facing title",
                "target_node_id": "paragraph node_id from clause_paragraphs",
                "selected_text": "exact risky substring in that paragraph, or empty string",
                "rationale": "why this may be problematic, grounded in evidence",
                "recommendation": "human-reviewable fix strategy",
                "replacement_text": "replacement for selected_text, or empty string",
                "full_replacement_text": "full paragraph replacement, or empty string",
                "source_ids": ["source ids used"],
            }
        ]
    }
    return "\n\n".join(
        [
            "[clause]",
            json.dumps(
                {
                    "clause_id": clause.clause_id,
                    "clause_no": clause.clause_no,
                    "title": clause.title,
                    "paragraphs": paragraph_payload,
                },
                ensure_ascii=False,
            ),
            "[rag_evidence]",
            json.dumps(evidence, ensure_ascii=False),
            "[required_json_schema]",
            json.dumps(schema, ensure_ascii=False),
        ]
    )


def _generation_answer(result: Any) -> str:
    if isinstance(result, str):
        return result
    answer = getattr(result, "answer", None)
    if isinstance(answer, str):
        return answer
    return str(result)


def _parse_generation_payload(answer: str) -> tuple[Mapping[str, Any], str | None]:
    cleaned = re.sub(r"\[ANSWERABLE:(yes|no)\]\s*$", "", answer.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned.strip(), flags=re.IGNORECASE | re.MULTILINE)
    start = min([idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx >= 0], default=-1)
    if start > 0:
        cleaned = cleaned[start:]
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end >= 0:
        cleaned = cleaned[: end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return {"findings": []}, f"Could not parse review generation JSON: {exc.msg}."
    if isinstance(parsed, list):
        return {"findings": parsed}, None
    if isinstance(parsed, Mapping):
        return parsed, None
    return {"findings": []}, "Review generation JSON must be an object or list."


def _findings_from_payload(
    payload: Mapping[str, Any],
    *,
    clause: ClauseSummary,
    paragraphs: Sequence[ParagraphPreview],
    sources: Sequence[ContractReviewSource],
    max_sources: int,
) -> list[ContractReviewFinding]:
    raw_findings = payload.get("findings") or []
    if not isinstance(raw_findings, Sequence) or isinstance(raw_findings, (str, bytes)):
        return []
    paragraph_by_id = {paragraph.node_id: paragraph for paragraph in paragraphs}
    fallback_node_id = paragraphs[0].node_id if paragraphs else clause.start_node_id
    findings: list[ContractReviewFinding] = []
    for index, raw in enumerate(raw_findings):
        if not isinstance(raw, Mapping):
            continue
        target_node_id = str(raw.get("target_node_id", "") or fallback_node_id)
        target = paragraph_by_id.get(target_node_id) or paragraph_by_id.get(fallback_node_id)
        target_text = target.text_excerpt if target is not None else ""
        selected_text = str(raw.get("selected_text", "") or raw.get("problematic_text", "") or "")
        if selected_text and selected_text not in target_text:
            selected_text = ""
        severity = _normalize_severity(raw.get("severity"))
        selected_sources = _select_sources(raw.get("source_ids"), sources, max_sources)
        proposed_edit = _build_proposed_edit(raw, target_node_id, target_text, selected_text)
        findings.append(
            ContractReviewFinding(
                finding_id=f"{clause.clause_id}:finding:{index + 1}",
                clause_id=clause.clause_id,
                clause_no=clause.clause_no,
                target_node_ids=[target_node_id],
                severity=severity,
                issue_type=str(raw.get("issue_type", "") or "contract_risk"),
                title=str(raw.get("title", "") or "Contract review finding"),
                problematic_text=selected_text,
                rationale=str(raw.get("rationale", "") or ""),
                recommendation=str(raw.get("recommendation", "") or ""),
                sources=selected_sources,
                annotation=_build_annotation(raw, target_node_id, target_text, selected_text, severity),
                proposed_edit=proposed_edit,
            )
        )
    return findings


def _normalize_severity(value: Any) -> Severity:
    normalized = str(value or "medium").strip().lower()
    if normalized in {"info", "low", "medium", "high", "critical"}:
        return normalized  # type: ignore[return-value]
    return "medium"


def _select_sources(
    raw_source_ids: Any,
    sources: Sequence[ContractReviewSource],
    max_sources: int,
) -> list[ContractReviewSource]:
    if isinstance(raw_source_ids, Sequence) and not isinstance(raw_source_ids, (str, bytes)):
        wanted = {str(source_id) for source_id in raw_source_ids}
        selected = [source for source in sources if source.source_id in wanted]
        if selected:
            return selected[:max_sources]
    return list(sources[:max_sources])


def _build_annotation(
    raw: Mapping[str, Any],
    target_node_id: str,
    target_text: str,
    selected_text: str,
    severity: Severity,
) -> TextAnnotation:
    occurrence_index = None
    if selected_text and target_text.count(selected_text) > 1:
        occurrence_index = 0
    return TextAnnotation(
        target_kind="paragraph",
        target_id=target_node_id,
        selected_text=selected_text or None,
        occurrence_index=occurrence_index,
        label=str(raw.get("title", "") or severity),
        color=_SEVERITY_COLORS[severity],
        note=str(raw.get("rationale", "") or ""),
    )


def _build_proposed_edit(
    raw: Mapping[str, Any],
    target_node_id: str,
    target_text: str,
    selected_text: str,
) -> TextEdit | None:
    full_replacement = str(raw.get("full_replacement_text", "") or "")
    replacement = str(raw.get("replacement_text", "") or "")
    new_text = ""
    if full_replacement:
        new_text = full_replacement
    elif selected_text and replacement:
        new_text = target_text.replace(selected_text, replacement, 1)
    if not new_text or new_text == target_text:
        return None
    return TextEdit(
        target_kind="paragraph",
        target_id=target_node_id,
        expected_text_hash=_text_hash(target_text),
        new_text=new_text,
        reason=str(raw.get("recommendation", "") or raw.get("title", "") or "Contract review suggestion"),
    )


def _render_findings_html(
    findings: Sequence[ContractReviewFinding],
    *,
    cfg: ContractReviewConfig,
    render_document: DocumentInput | None,
    render_source_path: str | None,
    warnings: list[str],
) -> str | None:
    if not cfg.include_review_html or (render_document is None and render_source_path is None):
        return None
    annotations = [finding.annotation for finding in findings if finding.annotation is not None]
    if not annotations:
        return None
    result = render_review_html(
        document=render_document,
        source_path=render_source_path,
        annotations=annotations,
        title=cfg.review_title,
    )
    if not result.ok:
        warnings.extend(issue.message for issue in result.validation.issues)
        return None
    return result.html


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


__all__ = [
    "ClauseReviewResult",
    "ContractReviewConfig",
    "ContractReviewFinding",
    "ContractReviewResult",
    "ContractReviewSource",
    "RagEvidenceClient",
    "ReviewContractRequest",
    "ReviewGenerationClient",
    "Severity",
    "SuggestionStatus",
    "review_contract_document",
    "review_parsed_contract",
]
