"""expc(법령해석례) HTML 페이지에서 관련 판례 ID를 수집한다.

법제처 법령정보 웹페이지(expcInfoP.do)의 【해석대상 조문 관련 판례】 섹션에서
cachPrecLink('PREC_ID') 호출을 파싱하여 prec ID 리스트를 반환한다.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from src.common.io_utils import _iter_jsonl

_BASE_URL = "https://www.law.go.kr/LSW/expcInfoP.do"
_PREC_LINK_PATTERN = re.compile(r"cachPrecLink\(['\"](\d+)['\"]\)")
_USER_AGENT = "Mozilla/5.0 (compatible; legal-pipeline/1.0)"


def fetch_expc_related_prec_ids(expc_seq: str, timeout: int = 5) -> list[str]:
    """expc 일련번호로 HTML을 가져와 관련 판례 ID를 추출한다."""
    url = f"{_BASE_URL}?expcSeq={expc_seq}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    return list(dict.fromkeys(_PREC_LINK_PATTERN.findall(html)))


def _sidecar_path(canonical_dir: Path, canonical_case_id: str) -> Path:
    safe_id = str(canonical_case_id).replace("::", "__").replace("/", "_")
    return canonical_dir / f"{safe_id}__related_prec_ids.json"


def _iter_unique_expc_targets(base: Path) -> list[dict[str, Any]]:
    """canonical_case_id 기준으로 중복 제거하되, 해당 케이스가 등장하는 모든 canonical_dir를 수집한다.

    같은 expc 케이스가 여러 법령 디렉토리에 나타나는 경우
    _load_expc_related_prec_ids가 root_law_name 기준으로 sidecar를 조회하므로
    모든 law 디렉토리에 sidecar를 저장해야 한다.
    """
    unique_rows: dict[str, dict[str, Any]] = {}

    for jsonl_path in sorted(base.rglob("canonical_cases.jsonl")):
        canonical_dir = jsonl_path.parent / "canonical" / "expc"

        for row in _iter_jsonl(jsonl_path):
            if str(row.get("target") or "").strip() != "expc":
                continue

            canonical_case_id = str(
                row.get("canonical_case_id") or row.get("canonical_id") or row.get("id") or ""
            ).strip()
            if not canonical_case_id:
                continue

            if canonical_case_id not in unique_rows:
                unique_rows[canonical_case_id] = {
                    "row": row,
                    "canonical_dirs": [],
                    "canonical_case_id": canonical_case_id,
                }

            if canonical_dir not in unique_rows[canonical_case_id]["canonical_dirs"]:
                unique_rows[canonical_case_id]["canonical_dirs"].append(canonical_dir)

    return [unique_rows[key] for key in sorted(unique_rows)]


def _fetch_one(
    item: dict[str, Any],
    overwrite: bool,
    rate_limit_sec: float,
    timeout: int,
) -> dict[str, Any]:
    """단일 expc 항목을 fetch하고 모든 canonical_dir에 sidecar를 저장한다."""
    canonical_case_id = str(item["canonical_case_id"]).strip()
    canonical_dirs = [Path(d) for d in item["canonical_dirs"]]
    row = dict(item.get("row") or {})

    sidecars = [_sidecar_path(d, canonical_case_id) for d in canonical_dirs]

    # 모든 디렉토리에 sidecar가 이미 존재하면 skip
    if not overwrite and all(s.exists() for s in sidecars):
        return {"status": "skipped", "canonical_case_id": canonical_case_id}

    # doc_id == 법령해석례일련번호 (검증됨) — detail JSON 읽기 불필요
    expc_seq = str(row.get("doc_id") or "").strip()
    if not expc_seq:
        return {"status": "no_seq", "canonical_case_id": canonical_case_id}

    try:
        prec_ids = fetch_expc_related_prec_ids(expc_seq, timeout=timeout)
        if rate_limit_sec > 0:
            time.sleep(rate_limit_sec)
        content = json.dumps(
            {"expc_seq": expc_seq, "related_prec_ids": prec_ids},
            ensure_ascii=False,
        )
        for sidecar in sidecars:
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(content, encoding="utf-8")
        return {"status": "fetched", "canonical_case_id": canonical_case_id}
    except Exception as exc:
        return {"status": "error", "canonical_case_id": canonical_case_id, "error": str(exc)}


def hydrate_expc_related_prec_ids(
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    overwrite: bool = False,
    rate_limit_sec: float = 0.3,
    timeout: int = 5,
    max_workers: int = 10,
) -> dict[str, Any]:
    """canonical_cases.jsonl에서 expc 건을 순회하며 관련 판례 ID를 수집한다.

    - canonical_case_id 기준 중복 제거 후 HTTP fetch (1회/케이스)
    - 동일 케이스가 등장하는 모든 law canonical_dir에 sidecar 저장
    - max_workers개 스레드 병렬 fetch
    """
    base = Path(raw_related_base_dir)
    unique_targets = _iter_unique_expc_targets(base)

    fetched = 0
    skipped = 0
    no_seq = 0
    errors: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_one, item, overwrite, rate_limit_sec, timeout): item
            for item in unique_targets
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            status = result.get("status")
            if status == "skipped":
                skipped += 1
            elif status == "fetched":
                fetched += 1
            elif status == "no_seq":
                no_seq += 1
            elif status == "error":
                errors.append(f"{result['canonical_case_id']}: {result.get('error')}")

    return {
        "total_unique_expc": len(unique_targets),
        "fetched": fetched,
        "skipped_existing": skipped,
        "no_seq": no_seq,
        "error_count": len(errors),
        "errors": errors[:20],
    }
