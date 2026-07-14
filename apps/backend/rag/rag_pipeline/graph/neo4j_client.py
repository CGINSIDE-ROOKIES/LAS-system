"""Neo4j 연결 래퍼.

환경변수 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 로 연결한다.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_URI = "bolt://localhost:7687"
_DEFAULT_USER = "neo4j"


class Neo4jClientError(Exception):
    """Neo4j 조회 실패."""


class Neo4jClient:
    """Neo4j Python driver 동기 래퍼."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "neo4j 패키지가 설치되지 않았습니다. "
                "apps/backend/api/pyproject.toml에 neo4j>=5 를 추가하세요."
            ) from exc

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.debug("Neo4j 연결: %s (user=%s)", uri, user)

    @classmethod
    def from_env(cls) -> "Neo4jClient":
        """환경변수 NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD 로 인스턴스를 생성한다."""
        uri = os.getenv("NEO4J_URI", _DEFAULT_URI).strip()
        user = os.getenv("NEO4J_USER", _DEFAULT_USER).strip()
        password = os.getenv("NEO4J_PASSWORD", "").strip()
        return cls(uri=uri, user=user, password=password)

    def run_query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Cypher 쿼리를 실행하고 결과를 list[dict]로 반환한다.

        주의: 이 메서드는 코드에서 조립된 템플릿 Cypher만 실행한다.
              외부 입력을 직접 Cypher 문자열에 포함하지 말고 반드시 params로 전달하라.
        """
        params = params or {}
        try:
            with self._driver.session() as session:
                result = session.run(cypher, **params)
                return [dict(record) for record in result]
        except Exception as exc:
            logger.error("Neo4j 쿼리 실패: %s | params=%s | error=%s", cypher[:120], params, exc)
            raise Neo4jClientError(f"Neo4j 쿼리 실패: {exc}") from exc

    def verify_connectivity(self) -> None:
        """연결 가능 여부를 확인한다. 실패 시 예외를 raise한다."""
        try:
            self._driver.verify_connectivity()
        except Exception as exc:
            raise Neo4jClientError(f"Neo4j 연결 실패: {exc}") from exc

    def close(self) -> None:
        self._driver.close()
