# retrieval-pipeline

임시 적재 준비용 작업 폴더.

## 데이터 복붙 위치
- `data/dropbox/`
- 지원 포맷: `.json`, `.jsonl`, `.txt`

## 임시 실행
```bash
cd /home/user/projects/LAS-system/apps/backend/retrieval-pipeline
python3 scripts/bootstrap_ingest.py
```

## 산출물
- `data/staging/chunks.jsonl`
- `data/staging/qdrant_points.jsonl` (임베딩 벡터는 빈 배열 placeholder)
- `data/staging/opensearch_bulk.ndjson`

## 다음 단계
- 임베딩 API 연결 후 `qdrant_points.jsonl`의 `vector` 채우기
- Qdrant/OpenSearch 업로드 스크립트 추가
