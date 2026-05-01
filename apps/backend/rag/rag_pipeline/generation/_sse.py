"""SSE 스트림 파싱 유틸리티."""

from __future__ import annotations

import json
from typing import Any, Iterator


def iter_sse_json_events(resp: Any) -> Iterator[dict[str, Any]]:
    """SSE 응답 스트림에서 data: JSON 이벤트만 추출한다."""
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if not data_str or data_str == "[DONE]":
            continue
        try:
            data = json.loads(data_str)
        except Exception:
            continue
        if isinstance(data, dict):
            yield data
