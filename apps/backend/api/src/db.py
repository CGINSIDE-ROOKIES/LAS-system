"""PostgreSQL 커넥션 풀 및 의존성 주입."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from pathlib import Path

import psycopg2
import psycopg2.pool
from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _run_migrations() -> None:
    cfg = Config(_ALEMBIC_INI)
    # SQLAlchemy 2.0은 postgres:// 미지원 → postgresql://로 정규화
    url = os.environ["DATABASE_URL"].replace("postgres://", "postgresql://", 1)
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    logger.info("DB 마이그레이션 완료 (alembic upgrade head)")


def init_pool() -> None:
    global _pool
    dsn = os.environ["DATABASE_URL"]
    _pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=dsn)
    try:
        _run_migrations()
    except Exception:
        _pool.closeall()
        _pool = None
        raise
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


@contextmanager
def db_connection():
    """Background 작업/SSE polling에서 사용할 커넥션 컨텍스트."""
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
