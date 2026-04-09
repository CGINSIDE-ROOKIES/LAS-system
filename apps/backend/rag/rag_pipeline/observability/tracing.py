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
        return client.trace(name=name, **kwargs)
    except Exception as exc:
        logger.debug("trace 생성 실패 (무시): %s", exc)
        return None


def start_span(parent: Any, name: str, **kwargs: Any) -> Any | None:
    """trace 또는 span에 하위 span을 생성한다. parent가 None이면 no-op."""
    if parent is None:
        return None
    try:
        return parent.span(name=name, **kwargs)
    except Exception as exc:
        logger.debug("span 생성 실패 (무시): %s", exc)
        return None


def start_generation_span(parent: Any, name: str, **kwargs: Any) -> Any | None:
    """LLM 호출 전용 generation span을 생성한다."""
    if parent is None:
        return None
    try:
        return parent.generation(name=name, **kwargs)
    except Exception as exc:
        logger.debug("generation span 생성 실패 (무시): %s", exc)
        return None


def end_span(span: Any, **kwargs: Any) -> None:
    """span을 종료한다. None이면 no-op."""
    if span is None:
        return
    try:
        span.end(**kwargs)
    except Exception as exc:
        logger.debug("span 종료 실패 (무시): %s", exc)


def update_trace(trace: Any, **kwargs: Any) -> None:
    """trace 메타데이터를 업데이트한다. None이면 no-op."""
    if trace is None:
        return
    try:
        trace.update(**kwargs)
    except Exception as exc:
        logger.debug("trace 업데이트 실패 (무시): %s", exc)
