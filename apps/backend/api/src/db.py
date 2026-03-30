"""PostgreSQL 커넥션 풀 및 의존성 주입."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg2
import psycopg2.pool

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _apply_migrations(conn: psycopg2.extensions.connection) -> None:
    if not _MIGRATIONS_DIR.exists():
        logger.warning("DB migrations directory not found: %s", _MIGRATIONS_DIR)
        return

    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8").strip()
        if not sql:
            continue
        logger.info("Applying DB migration: %s", path.name)
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def init_pool() -> None:
    global _pool
    dsn = os.environ["DATABASE_URL"]
    _pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=dsn)
    conn = _pool.getconn()
    try:
        _apply_migrations(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
    logger.info("DB 커넥션 풀 초기화 완료 (maxconn=10)")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("DB 커넥션 풀 종료")


def get_db():
    """FastAPI Depends()용 커넥션 제공자."""
    if _pool is None:
        raise RuntimeError("DB pool이 초기화되지 않았습니다.")
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
