"""FastAPI 애플리케이션 진입점.

실행:
  uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
import logging.config
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv(override=True)

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
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "uvicorn": {"propagate": True},
        "uvicorn.access": {"propagate": True},
    },
})

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.db import close_pool, init_pool
from src.retrieval.common import RetrievalError
from src.routers import health, qa


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("애플리케이션 시작")
    init_pool()
    yield
    close_pool()
    logger.info("애플리케이션 종료")


app = FastAPI(
    title="LAS API",
    description="Legal AI Assistant 백엔드 API",
    version="0.1.0",
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
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "error": exc.errors()[0]["msg"]},
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


@app.exception_handler(Exception)
async def internal_exception_handler(request: Request, exc: Exception):
    logger.exception("INTERNAL_ERROR %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "error": "서버 오류가 발생했습니다."},
    )


app.include_router(health.router)
app.include_router(qa.router, prefix="/api/v1/qa")
