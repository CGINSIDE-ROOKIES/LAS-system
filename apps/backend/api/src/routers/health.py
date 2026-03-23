"""헬스체크 라우터.

엔드포인트:
  GET /health  - 서버 상태 확인 (로드밸런서, 컨테이너 헬스체크용)
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """서버가 정상 동작 중인지 확인한다."""
    return {"status": "ok"}
