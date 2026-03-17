#!/usr/bin/env python3
"""Qdrant(벡터) + OpenSearch(BM25) 결과를 RRF 방식으로 융합하는 유틸리티 모듈.

이 파일은 라이브러리 역할만 한다. 직접 실행하지 말 것.
엔트리포인트는 query_all_retrieval.py 를 사용한다.

  from query_hybrid_rrf import fuse_rrf
"""

from __future__ import annotations

import hashlib

from retrieval_common import normalize_source_id


# ── 문서 동일성 키 ────────────────────────────────────────────────────────────
def _rrf_key(row: dict[str, object]) -> str:
    """두 백엔드의 결과를 같은 문서인지 판별하기 위한 정규화 키를 반환한다.

    source_id가 있으면 정규화(suffix 제거)해서 키로 사용하고,
    없으면 텍스트 앞 800자의 SHA-1 해시를 fallback으로 사용한다.
    """
    sid = str(row.get("source_id", "") or "")
    key = normalize_source_id(sid) if sid else ""
    if key:
        return key
    text = str(row.get("text", "") or "")
    return f"text::{hashlib.sha1(text[:800].encode('utf-8')).hexdigest()}"


# ── 단일 백엔드 내 중복 제거 ──────────────────────────────────────────────────
def _dedup_backend_rows_for_rrf(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """단일 백엔드 결과에서 같은 문서가 여러 번 등장하면 가장 높은 순위(낮은 rank 숫자)만 남긴다.

    RRF 점수 계산 전에 각 백엔드 내부 중복을 제거해야 순위 왜곡을 방지할 수 있다.
    """
    best_by_key: dict[str, dict[str, object]] = {}  # 키 -> 대표 행
    best_rank_by_key: dict[str, int] = {}  # 키 -> 가장 좋은(낮은) rank

    for row in rows:
        rank = int(row.get("rank", 0) or 0)
        if rank <= 0:
            continue
        key = _rrf_key(row)
        prev_rank = best_rank_by_key.get(key)
        # 처음 등장이거나 현재 rank가 더 좋으면 갱신
        if prev_rank is None or rank < prev_rank:
            best_rank_by_key[key] = rank
            best_by_key[key] = row

    # rank 오름차순(=점수 내림차순)으로 정렬해서 반환
    return sorted(best_by_key.values(), key=lambda r: int(r.get("rank", 0) or 0))


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

    Args:
        qdrant_rows: Qdrant 벡터 검색 결과.
        os_rows:     OpenSearch BM25 검색 결과.
        rrf_k:       RRF k 상수 (기본 60).
        top_k:       최종 반환할 결과 수.

    Returns:
        rank, score(=rrf_score), source_id 등이 포함된 결과 리스트.
    """
    # 문서 키 기준으로 두 백엔드 결과를 누적하는 딕셔너리
    merged: dict[str, dict[str, object]] = {}

    def add_rows(rows: list[dict[str, object]], backend: str) -> None:
        # 백엔드 결과를 merged에 RRF 점수로 누적
        deduped_rows = _dedup_backend_rows_for_rrf(rows)
        for row in deduped_rows:
            rank = int(row.get("rank", 0) or 0)
            if rank <= 0:
                continue

            sid = str(row.get("source_id", "") or "")
            key = _rrf_key(row)
            sid_norm = normalize_source_id(sid) if sid else ""

            rrf_score = 1.0 / (rrf_k + rank)  # 이 백엔드에서의 RRF 기여 점수
            cur = merged.get(key)
            if cur is None:
                # 처음 등장: 새 항목 생성
                cur = {
                    "source_id_raw": sid,
                    "source_id_normalized": sid_norm,
                    "doc_type": row.get("doc_type", ""),
                    "law_name": row.get("law_name", ""),
                    "text": row.get("text", ""),
                    "snippet": row.get("snippet", ""),
                    "rrf_score": 0.0,
                    "sources": [],  # 어느 백엔드에서 몇 위로 왔는지 기록
                }
                merged[key] = cur
            else:
                # 두 번째 백엔드에서 source_id가 보완될 수 있으면 업데이트
                if not str(cur.get("source_id_raw", "") or "") and sid:
                    cur["source_id_raw"] = sid
                if not str(cur.get("source_id_normalized", "") or "") and sid_norm:
                    cur["source_id_normalized"] = sid_norm

            # 기존 점수에 이번 백엔드 점수 누적
            cur["rrf_score"] = float(cur["rrf_score"]) + rrf_score

            # 출처 정보 추가 (디버깅 및 설명 목적)
            cast_sources = cur["sources"]
            if isinstance(cast_sources, list):
                cast_sources.append(
                    {"backend": backend, "rank": rank, "score": row.get("score")}
                )

    add_rows(qdrant_rows, "qdrant")
    add_rows(os_rows, "opensearch_bm25")

    def _tie_break_sort_key(row: dict[str, object]) -> tuple[float, int, int, str]:
        # 동점 시 정렬 기준 반환 (오름차순으로 정렬하므로 부호 반전에 주의)
        sources_obj = row.get("sources", [])
        source_count = 0
        best_rank = 10**9  # 초기값: 충분히 큰 수

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

        if best_rank == 10**9:
            best_rank = 10**8  # sources가 비어있는 경우 안전값

        source_id = str(
            row.get("source_id_normalized", "")
            or row.get("source_id_raw", "")
            or ""
        )
        return (
            -float(row["rrf_score"]),  # 1순위: 점수 내림차순
            -source_count,  # 2순위: 등장 백엔드 수 내림차순
            best_rank,  # 3순위: 최고 개별 rank 오름차순
            source_id,  # 4순위: source_id 오름차순 (결정적 정렬)
        )

    ranked = sorted(merged.values(), key=_tie_break_sort_key)

    # Top-k 추출 및 rank 부여
    out: list[dict[str, object]] = []
    for i, row in enumerate(ranked[: max(1, top_k)], start=1):
        source_id_raw = str(row.get("source_id_raw", "") or "")
        source_id_normalized = str(row.get("source_id_normalized", "") or "")
        source_id = source_id_normalized or source_id_raw
        out.append(
            {
                "rank": i,
                "score": round(float(row["rrf_score"]), 6),
                "source_id": source_id,
                "source_id_raw": source_id_raw,
                "source_id_normalized": source_id_normalized,
                "doc_type": row.get("doc_type", ""),
                "law_name": row.get("law_name", ""),
                "text": row.get("text", ""),
                "snippet": row.get("snippet", ""),
                "sources": row.get("sources", []),
            }
        )
    return out
