"""Qdrant + OpenSearch 결과를 RRF 방식으로 융합하는 모듈."""

from __future__ import annotations

import hashlib


_RANK_NOT_FOUND = 1_000_000_000


def _sha1_hex(data: bytes) -> str:
    """FIPS 환경 호환 SHA-1 헥사 문자열."""
    try:
        h = hashlib.sha1(data, usedforsecurity=False)  # type: ignore[call-arg]
    except TypeError:
        h = hashlib.sha1(data)
    return h.hexdigest()


# ── 문서 동일성 키 ────────────────────────────────────────────────────────────

def _rrf_key(row: dict[str, object]) -> str:
    """두 백엔드의 결과를 같은 문서인지 판별하기 위한 정규화 키를 반환한다.

    source_id가 있으면 그대로 키로 사용하고,
    없으면 텍스트 앞 800자의 SHA-1 해시를 fallback으로 사용한다.
    """
    sid = str(row.get("source_id", "") or "")
    if sid:
        return sid
    text = str(row.get("text", "") or "")
    return f"text::{_sha1_hex(text[:800].encode('utf-8'))}"


# ── 단일 백엔드 내 중복 제거 ──────────────────────────────────────────────────

def _dedup_backend_rows_for_rrf(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """단일 백엔드 결과에서 같은 문서가 여러 번 등장하면 가장 높은 순위(낮은 rank 숫자)만 남긴다.

    RRF 점수 계산 전에 각 백엔드 내부 중복을 제거해야 순위 왜곡을 방지할 수 있다.
    """
    best_by_key: dict[str, dict[str, object]] = {}
    best_rank_by_key: dict[str, int] = {}

    for row in rows:
        rank = int(row.get("rank", 0) or 0)
        if rank <= 0:
            continue
        key = _rrf_key(row)
        prev_rank = best_rank_by_key.get(key)
        if prev_rank is None or rank < prev_rank:
            best_rank_by_key[key] = rank
            best_by_key[key] = row

    return sorted(best_by_key.values(), key=lambda r: int(r.get("rank", 0) or 0))


def _merge_rows_into_rrf(
    merged: dict[str, dict[str, object]],
    rows: list[dict[str, object]],
    *,
    backend: str,
    rrf_k: int,
) -> None:
    """단일 소스 랭킹 리스트를 merged 맵에 누적한다."""
    deduped_rows = _dedup_backend_rows_for_rrf(rows)
    for row in deduped_rows:
        rank = int(row.get("rank", 0) or 0)
        if rank <= 0:
            continue

        sid = str(row.get("source_id", "") or "")
        key = _rrf_key(row)
        rrf_score = 1.0 / (rrf_k + rank)

        cur = merged.get(key)
        if cur is None:
            cur = {
                "source_id_raw": sid,
                "doc_type": row.get("doc_type", ""),
                "law_name": row.get("law_name", ""),
                "article_no": row.get("article_no", ""),
                "text": row.get("text", ""),
                "snippet": row.get("snippet", ""),
                "rrf_score": 0.0,
                "sources": [],
            }
            merged[key] = cur
        else:
            if not str(cur.get("source_id_raw", "") or "") and sid:
                cur["source_id_raw"] = sid

        cur["rrf_score"] = float(cur["rrf_score"]) + rrf_score
        cast_sources = cur["sources"]
        if isinstance(cast_sources, list):
            cast_sources.append(
                {"backend": backend, "rank": rank, "score": row.get("score")}
            )


def _tie_break_sort_key(row: dict[str, object]) -> tuple[float, int, int, str]:
    """RRF 동점 해소용 결정적 정렬 키."""
    sources_obj = row.get("sources", [])
    source_count = 0
    best_rank = _RANK_NOT_FOUND
    if isinstance(sources_obj, list):
        backends: set[str] = set()
        for s in sources_obj:
            if not isinstance(s, dict):
                continue
            backend = str(s.get("backend", "") or "")
            if backend:
                backends.add(backend)
            rank = int(s.get("rank", 0) or 0)
            if rank > 0:
                best_rank = min(best_rank, rank)
        source_count = len(backends)
    source_id = str(row.get("source_id_raw", "") or "")
    return (-float(row["rrf_score"]), -source_count, best_rank, source_id)


def _materialize_fused_rows(
    merged: dict[str, dict[str, object]],
    *,
    top_k: int,
) -> list[dict[str, object]]:
    """누적된 merged 맵을 최종 출력 포맷으로 변환한다."""
    ranked = sorted(merged.values(), key=_tie_break_sort_key)
    out: list[dict[str, object]] = []
    for i, row in enumerate(ranked[:top_k], start=1):
        source_id = str(row.get("source_id_raw", "") or "")
        out.append(
            {
                "rank": i,
                "score": round(float(row["rrf_score"]), 6),
                "source_id": source_id,
                "doc_type": row.get("doc_type", ""),
                "law_name": row.get("law_name", ""),
                "article_no": row.get("article_no", ""),
                "text": row.get("text", ""),
                "snippet": row.get("snippet", ""),
                "sources": row.get("sources", []),
            }
        )
    return out


# ── RRF 융합 ──────────────────────────────────────────────────────────────────

def fuse_rrf(
    qdrant_rows: list[dict[str, object]],
    os_rows: list[dict[str, object]],
    *,
    rrf_k: int,
    top_k: int,
) -> list[dict[str, object]]:
    """Qdrant + OpenSearch 결과를 RRF 방식으로 융합해 Top-K를 반환한다.

    RRF 점수 공식: score = Σ 1 / (k + rank_i)
      - k: 순위 편향 조절 상수 (보통 60). 클수록 하위 순위 문서도 점수를 받음.
      - rank_i: 각 백엔드에서의 순위 (1-based).
      - 두 백엔드에 모두 등장하면 점수가 합산되어 순위가 높아짐.

    동점(tie-break) 정렬 기준:
      1. rrf_score 내림차순
      2. 등장한 백엔드 수 내림차순 (두 백엔드에 모두 있으면 우선)
      3. 개별 백엔드 내 최고 rank 오름차순
      4. source_id 오름차순 (결정적 정렬 보장)
    """
    if top_k <= 0:
        return []

    merged: dict[str, dict[str, object]] = {}
    _merge_rows_into_rrf(merged, qdrant_rows, backend="qdrant", rrf_k=rrf_k)
    _merge_rows_into_rrf(merged, os_rows, backend="opensearch_bm25", rrf_k=rrf_k)
    return _materialize_fused_rows(merged, top_k=top_k)


# ── 다중 리스트 RRF 융합 ──────────────────────────────────────────────────────

def fuse_rrf_multi(
    ranked_lists: list[list[dict[str, object]]],
    *,
    rrf_k: int,
    top_k: int,
    backend_names: list[str] | None = None,
) -> list[dict[str, object]]:
    """N개의 랭킹 리스트를 RRF 방식으로 융합해 Top-K를 반환한다.

    컬렉션이 1개면 그대로 반환하고, 2개 이상이면 각 리스트를 독립 소스로 취급해
    RRF 점수를 누적한다. fuse_rrf와 동일한 알고리즘을 N개 소스로 일반화한 버전.
    """
    if top_k <= 0:
        return []
    if not ranked_lists:
        return []
    if len(ranked_lists) == 1:
        return ranked_lists[0]

    merged: dict[str, dict[str, object]] = {}
    # backend_names가 제공되면 사람이 읽기 쉬운 컬렉션명을 source backend로 보존한다.
    # 미제공 시 기존과 동일하게 인덱스 기반 이름을 사용한다.
    for i, rows in enumerate(ranked_lists):
        backend = (
            backend_names[i]
            if backend_names is not None and i < len(backend_names) and backend_names[i]
            else f"qdrant_col_{i}"
        )
        _merge_rows_into_rrf(merged, rows, backend=backend, rrf_k=rrf_k)

    return _materialize_fused_rows(merged, top_k=top_k)
