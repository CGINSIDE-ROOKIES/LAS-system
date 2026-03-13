# retrieval-pipeline

임베딩된 JSONL을 Qdrant/OpenSearch에 적재하는 폴더.

## 환경변수 파일
`.env.example`를 복사해서 `.env`를 만들고 사용:
```bash
cp .env.example .env
set -a
source .env
set +a
```

## 현재 기준 사용 플로우
1. `data/dropbox/*.embedded.jsonl` 파일 준비
2. `scripts/index_embedded_jsonl.py` 실행
3. Qdrant/OpenSearch 인덱싱 결과 확인

## 주요 스크립트
- `scripts/index_embedded_jsonl.py`: 임베딩 완료 JSONL 바로 인덱싱 (현재 주 사용)
- `scripts/index_to_stores.py`: 임베딩 API 호출 + 인덱싱
- `scripts/bootstrap_ingest.py`: 원본 JSON/JSONL/TXT를 청킹해서 스테이징 파일 생성하는 초기 전처리용
- `scripts/query_qdrant_topk.py`: 사용자 질문 기반 Qdrant Top-K 검색 테스트
- `scripts/query_opensearch_bm25.py`: 사용자 질문 기반 OpenSearch BM25 Top-K 검색 테스트
- `scripts/query_hybrid_rrf.py`: Qdrant + OpenSearch 결과를 RRF로 병합한 Hybrid 검색

## 입력 포맷 (`*.embedded.jsonl`)
각 row 예시:
```json
{
  "point_id": "law::...",
  "vector": [0.01, -0.02, ...],
  "payload": {"doc_type": "law"},
  "text_for_embedding": "..."
}
```

## 필수 환경변수
```bash
export QDRANT_URL="http://localhost:6333"
export QDRANT_COLLECTION="las_legal_docs"
export OPENSEARCH_URL="http://localhost:9200"
export OPENSEARCH_INDEX="las_legal_docs"
```

## 인덱싱 실행 (임베딩 완료 파일)
```bash
cd /home/user/projects/LAS-system/apps/backend/retrieval-pipeline
python3 scripts/index_embedded_jsonl.py --batch-size 256
```
기본값으로 Qdrant 컬렉션이 없으면 첫 배치 벡터 차원으로 자동 생성한다.

OpenSearch 문서에 벡터 필드까지 저장하려면:
```bash
python3 scripts/index_embedded_jsonl.py --batch-size 256 --opensearch-vector-field embedding
```

업로드 없이 파일 파싱만 확인:
```bash
python3 scripts/index_embedded_jsonl.py --limit 1000 --dry-run
```

## 인증(선택)
```bash
export QDRANT_API_KEY="..."
export OPENSEARCH_API_KEY="..."      # 또는
export OPENSEARCH_USERNAME="..."
export OPENSEARCH_PASSWORD="..."
```

## Qdrant 검색 테스트
질문 1회 실행:
```bash
python3 scripts/query_qdrant_topk.py --question "건설업 등록 기준은?" --top-k 5
```

대화형:
```bash
python3 scripts/query_qdrant_topk.py --interactive --top-k 5
```

`sentence-transformers`가 없으면 설치:
```bash
uv add sentence-transformers
```

## OpenSearch 검색 테스트 (BM25)
질문 1회 실행:
```bash
python3 scripts/query_opensearch_bm25.py --question "건설업 등록 기준은?" --top-k 5
```

대화형:
```bash
python3 scripts/query_opensearch_bm25.py --interactive --top-k 5
```

## Hybrid 검색 테스트 (RRF)
질문 1회 실행:
```bash
uv run python scripts/query_hybrid_rrf.py --question "건설업 등록 기준은?" --top-k 5
```

대화형:
```bash
uv run python scripts/query_hybrid_rrf.py --interactive --top-k 5
```
