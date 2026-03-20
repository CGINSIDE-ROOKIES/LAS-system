"""FastAPI 애플리케이션 진입점.

실행:
  uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routers import health, qa

app = FastAPI(
    title="LAS API",
    description="Legal AI Assistant 백엔드 API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(qa.router, prefix="/api/v1/qa")
