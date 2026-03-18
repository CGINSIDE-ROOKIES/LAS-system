# rag

임시 적재 준비용 작업 폴더.

## 데이터 복붙 위치
- `data/dropbox/`
- 지원 포맷: `.json`, `.jsonl`, `.txt`

## 임시 실행
```bash
cd /home/user/projects/LAS-system/apps/backend/rag
uv run python cli/index_embedded_jsonl.py --dry-run --limit 100
```

## 산출물
- `data/staging/chunks.jsonl`
- `data/staging/qdrant_points.jsonl` (임베딩 벡터는 빈 배열 placeholder)
- `data/staging/opensearch_bulk.ndjson`

## 다음 단계
- 임베딩 API 연결 후 `qdrant_points.jsonl`의 `vector` 채우기
- Qdrant/OpenSearch 업로드는 `cli/index_embedded_jsonl.py` 사용
