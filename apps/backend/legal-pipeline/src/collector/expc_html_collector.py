"""expc(법령해석례) HTML 페이지에서 관련 판례 ID를 수집한다.

법제처 법령정보 웹페이지(expcInfoP.do)의 【해석대상 조문 관련 판례】 섹션에서
cachPrecLink('PREC_ID') 호출을 파싱하여 prec ID 리스트를 반환한다.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from src.common.io_utils import _iter_jsonl, _read_json

_BASE_URL = "https://www.law.go.kr/LSW/expcInfoP.do"
_PREC_LINK_PATTERN = re.compile(r"cachPrecLink\(['\"](\d+)['\"]\)")
_USER_AGENT = "Mozilla/5.0 (compatible; legal-pipeline/1.0)"


def fetch_expc_related_prec_ids(expc_seq: str, timeout: int = 10) -> list[str]:
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


def hydrate_expc_related_prec_ids(
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    overwrite: bool = False,
    rate_limit_sec: float = 0.3,
    timeout: int = 10,
) -> dict[str, Any]:
    """canonical_cases.jsonl에서 expc 건을 순회하며 관련 판례 ID를 수집한다."""
    base = Path(raw_related_base_dir)
    total = 0
    fetched = 0
    skipped = 0
    reused = 0
    errors: list[str] = []
    cached_prec_ids_by_expc_seq: dict[str, list[str]] = {}

    for jsonl_path in sorted(base.rglob("canonical_cases.jsonl")):
        canonical_dir = jsonl_path.parent / "canonical" / "expc"
        canonical_dir.mkdir(parents=True, exist_ok=True)

        for row in _iter_jsonl(jsonl_path):
            if str(row.get("target") or "").strip() != "expc":
                continue

            canonical_case_id = str(
                row.get("canonical_case_id") or row.get("canonical_id") or row.get("id") or ""
            ).strip()
            if not canonical_case_id:
                continue

            sidecar = _sidecar_path(canonical_dir, canonical_case_id)
            if sidecar.exists() and not overwrite:
                skipped += 1
                total += 1
                continue

            detail_path = row.get("detail_payload_path")
            expc_seq = None
            if detail_path:
                full_path = base.parent.parent.parent / detail_path if not Path(detail_path).is_absolute() else Path(detail_path)
                if full_path.exists():
                    payload = _read_json(full_path)
                    svc = payload.get("ExpcService", {})
                    expc_seq = str(svc.get("법령해석례일련번호") or "").strip()

            if not expc_seq:
                expc_seq = str(row.get("doc_id") or "").strip()

            if not expc_seq:
                total += 1
                continue

            try:
                if expc_seq in cached_prec_ids_by_expc_seq:
                    prec_ids = cached_prec_ids_by_expc_seq[expc_seq]
                    reused += 1
                else:
                    prec_ids = fetch_expc_related_prec_ids(expc_seq, timeout=timeout)
                    cached_prec_ids_by_expc_seq[expc_seq] = prec_ids
                    fetched += 1
                    if rate_limit_sec > 0:
                        time.sleep(rate_limit_sec)
                sidecar.write_text(
                    json.dumps(
                        {"expc_seq": expc_seq, "related_prec_ids": prec_ids},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except Exception as exc:
                errors.append(f"{canonical_case_id}: {exc}")

            total += 1

    return {
        "total_expc": total,
        "fetched": fetched,
        "reused_cached_fetch": reused,
        "unique_expc_seq_fetched": len(cached_prec_ids_by_expc_seq),
        "skipped_existing": skipped,
        "error_count": len(errors),
        "errors": errors[:20],
    }
