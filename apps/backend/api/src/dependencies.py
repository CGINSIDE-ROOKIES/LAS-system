"""FastAPI 의존성 주입 정의.

각 라우터에서 Depends()로 주입받는 서비스 인스턴스를 여기서 관리한다.
서비스 구현체가 완성되면 rag/src/에서 import해서 연결한다.

사용 예시:
  from src.dependencies import get_retrieval_service

  @router.post("/")
  async def chat(service=Depends(get_retrieval_service)):
      ...
"""

# TODO: rag/src/retrieval/service.py 구현 후 import 연결
# from rag.src.retrieval.service import RetrievalService
# from rag.src.generation.service import GenerationService


def get_retrieval_service():
    """RetrievalService 인스턴스를 반환한다."""
    # TODO: 환경변수 기반으로 초기화
    raise NotImplementedError


def get_generation_service():
    """GenerationService 인스턴스를 반환한다."""
    # TODO: 환경변수 기반으로 초기화
    raise NotImplementedError
