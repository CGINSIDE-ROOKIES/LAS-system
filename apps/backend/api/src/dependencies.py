"""FastAPI 의존성 주입 정의.

각 라우터에서 Depends()로 주입받는 서비스 인스턴스를 여기서 관리한다.

사용 예시:
  from src.dependencies import get_rag_pipeline

  @router.post("/ask/stream")
  def ask_stream(request: ChatRequest, pipeline=Depends(get_rag_pipeline)):
      ...
"""

from functools import lru_cache

from src.generation.pipeline import RagPipeline


@lru_cache(maxsize=1)
def get_rag_pipeline() -> RagPipeline:
    """환경변수 기반으로 RagPipeline 인스턴스를 반환한다. 최초 1회만 생성된다."""
    return RagPipeline.from_env()
