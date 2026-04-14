"""Langfuse trace/span 생성 헬퍼.

get_langfuse_client()가 None이면 모든 함수는 no-op으로 동작한다.
호출부는 반환값이 None인지 확인하지 않아도 된다 — end_span/update_trace는 None을 받으면 그냥 반환한다.
"""

from __future__ import annotations

import logging
from typing import Any

from .langfuse_client import get_langfuse_client

logger = logging.getLogger(__name__)


def start_trace(name: str, **kwargs: Any) -> Any | None:
    """루트 trace를 생성한다. Langfuse 비활성 시 None 반환."""
    client = get_langfuse_client()
    if client is None:
        return None
    try:
        return client.start_observation(name=name, as_type="span", **kwargs)
    except Exception as exc:
        logger.warning("Langfuse trace 생성 실패: %s", exc)
        return None


def start_span(parent: Any, name: str, **kwargs: Any) -> Any | None:
    """trace 또는 span에 하위 span을 생성한다. parent가 None이면 no-op."""
    if parent is None:
        return None
    try:
        return parent.start_observation(name=name, as_type="span", **kwargs)
    except Exception as exc:
        logger.warning("Langfuse span 생성 실패: %s", exc)
        return None


def start_generation_span(parent: Any, name: str, **kwargs: Any) -> Any | None:
    """LLM 호출 전용 generation span을 생성한다."""
    if parent is None:
        return None
    try:
        return parent.start_observation(name=name, as_type="generation", **kwargs)
    except Exception as exc:
        logger.warning("Langfuse generation span 생성 실패: %s", exc)
        return None


def end_span(span: Any, **kwargs: Any) -> None:
    """span을 업데이트하고 종료한다. None이면 no-op.

    span.end()는 end_time만 받으므로, 나머지 kwargs는 span.update()로 먼저 전달한다.
    usage → usage_details 변환도 여기서 처리한다.
    """
    if span is None:
        return
    try:
        end_time = kwargs.pop("end_time", None)
        if "usage" in kwargs:
            kwargs["usage_details"] = kwargs.pop("usage")
        if kwargs:
            span.update(**kwargs)
        span.end() if end_time is None else span.end(end_time=end_time)
    except Exception as exc:
        logger.warning("Langfuse span 종료 실패: %s", exc)


def get_trace_id(span: Any) -> str | None:
    """span에서 Langfuse trace_id를 반환한다. 없으면 None."""
    if span is None:
        return None
    return getattr(span, "trace_id", None)


def update_trace(trace: Any, **kwargs: Any) -> None:
    """trace 메타데이터를 업데이트하고 span을 종료한다. None이면 no-op."""
    if trace is None:
        return
    try:
        trace.update(**kwargs)
        trace.end()
    except Exception as exc:
        logger.warning("Langfuse trace 업데이트 실패: %s", exc)
