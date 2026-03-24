"""PostgreSQL 커넥션 풀 및 의존성 주입."""

from __future__ import annotations

import os

import psycopg2
import psycopg2.pool


_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def init_pool() -> None:
    global _pool
    dsn = os.environ["DATABASE_URL"]
    _pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=dsn)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


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
