"""FastAPI 애플리케이션 진입점.

실행:
  uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI
from src.routers import chat, health

app = FastAPI(
    title="LAS API",
    description="Legal AI Assistant 백엔드 API",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(chat.router, prefix="/chat")
