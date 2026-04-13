"""FastAPI 애플리케이션 진입점.

실행:
  uv run uvicorn main:app --reload
"""

import logging
import logging.config
import os
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
import tomllib

from dotenv import load_dotenv

# ─── 환경 변수 로드 ────────────────────────────────────────────────────────────
# 시스템 환경 변수보다 .env 파일의 값을 우선 적용.
load_dotenv(override=True)


def _resolve_app_version() -> str:
    """앱 버전을 단일 출처에서 읽어온다.

    우선순위:
      1) 설치된 패키지 메타데이터(importlib.metadata)
      2) 로컬 pyproject.toml
      3) fallback("0.1.0")
    """
    try:
        return pkg_version("las-api")
    except PackageNotFoundError:
        pass
    except Exception:
        pass

    try:
        pyproject_path = Path(__file__).resolve().parent / "pyproject.toml"
        if pyproject_path.exists():
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            return str(data.get("project", {}).get("version", "0.1.0"))
    except Exception:
        pass
    return "0.1.0"

# ─── 로깅 설정 ────────────────────────────────────────────────────────────────
# dictConfig를 사용해 선언적으로 로거 구조를 정의
# disable_existing_loggers=False: 서드파티 라이브러리(uvicorn 등)의 기존 로거를 비활성화하지 않고 유지
logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        }
    },
    "root": {"level": os.getenv("LOG_LEVEL", "INFO").upper(), "handlers": ["console"]},
    "loggers": {
        "uvicorn": {"propagate": True},
        "uvicorn.access": {"propagate": True},  # HTTP 접근 로그
    },
})

logger = logging.getLogger(__name__)

#  ─── FastAPI 및 내부 모듈 임포트 ───────────────────────────────────────────────
# 주의: load_dotenv 이후에 임포트해야 환경 변수 의존 모듈이 올바르게 초기화됨
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.db import close_pool, init_pool
from src.dependencies import warmup_dependencies
from rag_pipeline.observability import initialize_langfuse, shutdown_langfuse
from rag_pipeline.retrieval.common import EmbeddingError, LLMError, LLMTimeoutError, RetrievalError
from src.routers import health, qa


# ─── 앱 생명주기 관리 (Lifespan) ──────────────────────────────────────────────
# asynccontextmanager 패턴: yield 이전 = 시작(startup), 이후 = 종료(shutdown)
# FastAPI 0.93+ 권장 방식 (구 on_event("startup") 대체)
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("애플리케이션 시작")
    # DB 풀 초기화/해제는 동기 함수이므로 이벤트 루프 블로킹을 피하려고 스레드풀에서 실행한다.
    await run_in_threadpool(init_pool)
    # 의존성 선초기화: 첫 요청 전에 환경변수/설정 오류를 조기 발견한다.
    await run_in_threadpool(warmup_dependencies)
    # Langfuse 클라이언트를 조기 초기화해 첫 트레이스 지연을 줄인다.
    await run_in_threadpool(initialize_langfuse)
    yield
    await run_in_threadpool(shutdown_langfuse)
    await run_in_threadpool(close_pool)
    logger.info("애플리케이션 종료")


app = FastAPI(
    title="LAS API",
    description="Legal AI Assistant 백엔드 API",
    version=_resolve_app_version(),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    message = errors[0].get("msg", "요청 형식이 올바르지 않습니다.") if errors else "요청 형식이 올바르지 않습니다."
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "error": message},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": "HTTP_ERROR", "error": exc.detail},
    )


@app.exception_handler(RetrievalError)
async def retrieval_exception_handler(request: Request, exc: RetrievalError):
    logger.error("PIPELINE_ERROR %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"code": "PIPELINE_ERROR", "error": str(exc)},
    )


@app.exception_handler(EmbeddingError)
async def embedding_exception_handler(request: Request, exc: EmbeddingError):
    logger.error("EMBEDDING_ERROR %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"code": "EMBEDDING_ERROR", "error": str(exc)},
    )


@app.exception_handler(LLMTimeoutError)
async def llm_timeout_exception_handler(request: Request, exc: LLMTimeoutError):
    logger.error("LLM_TIMEOUT %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=504,
        content={"code": "LLM_TIMEOUT", "error": str(exc)},
    )


@app.exception_handler(LLMError)
async def llm_exception_handler(request: Request, exc: LLMError):
    logger.error("LLM_ERROR %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=502,
        content={"code": "LLM_ERROR", "error": str(exc)},
    )


@app.exception_handler(Exception)
async def internal_exception_handler(request: Request, exc: Exception):
    logger.exception("INTERNAL_ERROR %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "error": "서버 오류가 발생했습니다."},
    )


app.include_router(health.router)
app.include_router(qa.router, prefix="/api/v1/qa")
