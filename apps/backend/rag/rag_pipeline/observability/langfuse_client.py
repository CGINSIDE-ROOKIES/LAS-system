"""Langfuse 클라이언트 초기화/종료 유틸.

Langfuse 환경변수가 없으면 조용히 비활성화하고, 있으면 싱글톤 클라이언트를 반환한다.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_langfuse_client: Any | None = None
_langfuse_initialized = False


def _is_langfuse_enabled() -> bool:
    return bool(
        os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        and os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    )


def initialize_langfuse() -> Any | None:
    """Langfuse 클라이언트를 1회 초기화하고 반환한다."""
    global _langfuse_client, _langfuse_initialized
    if _langfuse_initialized:
        return _langfuse_client

    _langfuse_initialized = True
    if not _is_langfuse_enabled():
        logger.info("Langfuse 비활성화: LANGFUSE_PUBLIC_KEY/SECRET_KEY 미설정")
        _langfuse_client = None
        return None

    try:
        from langfuse import get_client

        _langfuse_client = get_client()
        logger.info("Langfuse 클라이언트 초기화 완료")
        return _langfuse_client
    except Exception as exc:
        logger.warning("Langfuse 초기화 실패: %s", exc)
        _langfuse_client = None
        return None


def get_langfuse_client() -> Any | None:
    """초기화된 Langfuse 클라이언트를 반환한다. 없으면 초기화 시도 후 반환한다."""
    if not _langfuse_initialized:
        return initialize_langfuse()
    return _langfuse_client


def score_trace(trace_id: str, name: str, value: float, comment: str | None = None) -> None:
    """Langfuse trace에 score를 기록한다. 클라이언트 비활성 시 no-op."""
    if not trace_id:
        return
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.create_score(trace_id=trace_id, name=name, value=value, comment=comment)
    except Exception as exc:
        logger.debug("score 기록 실패: %s", exc)


def shutdown_langfuse() -> None:
    """프로세스 종료 시 Langfuse 버퍼를 flush한다."""
    client = get_langfuse_client()
    if client is None:
        return
    flush = getattr(client, "flush", None)
    if callable(flush):
        try:
            flush()
            logger.info("Langfuse flush 완료")
        except Exception as exc:
            logger.warning("Langfuse flush 실패: %s", exc)
