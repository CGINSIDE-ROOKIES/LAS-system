"""FastAPI 의존성 주입 정의.

각 라우터에서 Depends()로 주입받는 서비스 인스턴스를 여기서 관리한다.

주의사항:
  - lru_cache(maxsize=1)로 프로세스 내 싱글톤처럼 동작하지만, 멀티 워커 환경에서는 워커별로 1개씩 생성된다.
  - lazy 초기화이므로 기본적으로 첫 요청 시점에 인스턴스 생성/환경변수 검증이 일어난다.
  - 런타임 중 .env/환경변수 변경은 자동 반영되지 않으며, 프로세스 재시작(또는 캐시 초기화)이 필요하다.

사용 예시:
  from src.dependencies import get_rag_pipeline

  @router.post("/ask/stream")
  def ask_stream(request: ChatRequest, pipeline=Depends(get_rag_pipeline)):
      ...
"""

from functools import lru_cache

from rag_pipeline.generation.pipeline import RagPipeline
from rag_pipeline.query_parser import QueryParser


@lru_cache(maxsize=1)
def get_rag_pipeline() -> RagPipeline:
    """환경변수 기반으로 RagPipeline 인스턴스를 반환한다.

    프로세스 생애주기 동안 최초 1회만 생성되며, 이후 동일 인스턴스를 재사용한다.
    """
    return RagPipeline.from_env()


@lru_cache(maxsize=1)
def get_query_parser() -> QueryParser:
    """환경변수 기반으로 QueryParser 인스턴스를 반환한다.

    프로세스 생애주기 동안 최초 1회만 생성되며, 이후 동일 인스턴스를 재사용한다.
    """
    return QueryParser.from_env()


def warmup_dependencies() -> None:
    """의존성 인스턴스를 선초기화한다.

    startup 단계에서 호출하면 환경변수 누락/설정 오류를 첫 요청 전에 조기 발견할 수 있다.
    """
    get_rag_pipeline()
    get_query_parser()


def reset_dependency_caches() -> None:
    """테스트/로컬 디버깅용 캐시 초기화 유틸리티."""
    get_rag_pipeline.cache_clear()
    get_query_parser.cache_clear()
