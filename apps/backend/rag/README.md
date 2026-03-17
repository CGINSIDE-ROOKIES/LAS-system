# rag

임베딩된 JSONL을 Qdrant/OpenSearch에 적재하고 retrieval 테스트를 수행하는 폴더.

## 현재 상태
- 인덱싱 파이프라인은 임시 운영 상태다.
- 현재는 사전 임베딩된 파일(`data/dropbox/*.embedded.jsonl`)을 바로 적재해 테스트한다.
- 데이터 품질 개선 전까지 retrieval 평가는 참고 지표로 사용한다.

## 운영 체크리스트 (짧은 순서)
1. 작업 디렉토리 이동
```bash
cd /home/user/projects/LAS-system/apps/backend/rag
```
2. Docker 스토어 실행 (Qdrant/OpenSearch)
```bash
docker compose up -d
docker compose ps
```
3. 환경변수 로드
```bash
cp .env.example .env   # 최초 1회
set -a && source .env && set +a
```
4. (임시) 인덱싱 실행
```bash
uv run python cli/index_embedded_jsonl.py --batch-size 256
```
5. 검색 실행 (원하는 스크립트 1개)
```bash
uv run python cli/query_qdrant_topk.py --question "연장근로 최대 시간은 몇 시간인가요?" --top-k 5
uv run python cli/query_opensearch_bm25.py --question "연장근로 최대 시간은 몇 시간인가요?" --top-k 5
uv run python cli/query_hybrid_rrf.py --question "연장근로 최대 시간은 몇 시간인가요?" --top-k 5
uv run python cli/query_all_retrieval.py --question "연장근로 최대 시간은 몇 시간인가요?" --top-k 5 --llm-context-json
```

## 재실행 가이드 (혼선 방지)
- 질문만 바꿔 재검색할 때: 5번만 다시 실행
- `.env`를 바꿨을 때: 3번부터 다시
- 데이터 파일(`*.embedded.jsonl`)이 바뀌었을 때: 4번부터 다시
- OpenSearch 매핑/인덱스 구조를 바꿨을 때: `docker compose down -v` 후 2번부터 다시

## Docker 운영 명령
상태/로그:
```bash
docker compose ps
docker compose logs -f qdrant
docker compose logs -f opensearch
```
중지:
```bash
docker compose down
```
볼륨까지 초기화(데이터 삭제):
```bash
docker compose down -v
```

## 인덱싱 (임시 운영)
사전 임베딩 JSONL을 바로 적재:
```bash
uv run python cli/index_embedded_jsonl.py --batch-size 256
```
파싱만 확인:
```bash
uv run python cli/index_embedded_jsonl.py --dry-run --limit 1000
```
OpenSearch에 벡터 필드 저장:
```bash
uv run python cli/index_embedded_jsonl.py --batch-size 256 --opensearch-vector-field embedding
```

## 검색 실행
Qdrant:
```bash
uv run python cli/query_qdrant_topk.py --question "건설업 등록 기준은?" --top-k 5
```
BM25:
```bash
uv run python cli/query_opensearch_bm25.py --question "건설업 등록 기준은?" --top-k 5
```
Hybrid RRF:
```bash
uv run python cli/query_hybrid_rrf.py --question "건설업 등록 기준은?" --top-k 5
```
통합(LLM 컨텍스트 출력 포함):
```bash
uv run python cli/query_all_retrieval.py --question "건설업 등록 기준은?" --top-k 5 --llm-context-text
```

LLM Generator 단독 호출:
```bash
uv run python cli/generator.py --prompt "안녕"
```

Retrieval + Generator 통합 호출:
```bash
uv run python cli/generate_answer.py --question "연장근로 최대 시간은?" --top-k 5
```

### Hybrid 결과의 source_id 필드 기준
- `source_id`: 호환용 기본 식별자(정규화 기준, `__dupN` 제거 반영)
- `source_id_raw`: 원본 source id
- `source_id_normalized`: 중복 제거/병합 기준으로 사용한 정규화 source id
- 운영/표시 권장: `source_id`(= normalized 우선), 디버깅 시 raw 함께 확인

## 평가셋 기반 점검
```bash
uv run python cli/evaluate_retrieval_gold.py --top-k 5
uv run python cli/evaluate_retrieval_gold.py --top-k 5 --out-csv cli/retrieval_eval_result.csv
```

## 주요 스크립트
- `cli/index_embedded_jsonl.py`: 사전 임베딩 JSONL 적재 (현재 주 사용, 임시 운영)
- `cli/query_qdrant_topk.py`: Qdrant Top-K 테스트
- `cli/query_opensearch_bm25.py`: OpenSearch BM25 Top-K 테스트
- `cli/query_hybrid_rrf.py`: Qdrant + BM25 RRF 병합
- `cli/query_all_retrieval.py`: Qdrant/BM25/RRF 통합 실행 + LLM 컨텍스트 출력
- `cli/generator.py`: `generate_answer(prompt)` 기반 LLM 호출 유틸
- `cli/generate_answer.py`: retrieval 결과를 바탕으로 generator까지 한 번에 실행
- `cli/evaluate_retrieval_gold.py`: 골드셋 기반 Hit@k 평가
