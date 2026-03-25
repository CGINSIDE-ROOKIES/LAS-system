# legal-pipeline README / 진행 현황 정리

국가법령정보 OPEN API 기반 3개 축의 데이터 생성

- `law_article`: 현행 법령 조문 본문 + 부칙 + 별표 연계 정보
- `legal_case`: 판례/헌재결정례/법령해석례/행정심판례 본문
- `legal_relation`: 법령↔사례 관계 정보

## 1. 기능 목적
국가법령정보 Open API 수집 유지하면서, 최종검색 대상을 3개의 Qdrant collection으로 정리

1. `law_article`
   - 법령 조문을 중심으로 저장
   - appendix(별표)는 별도 collection이 아니라 `law_article` payload 및 appendix vector로 통합
2. `legal_case`
   - `prec`, `detc`, `expc`, `decc`의 dedupe된 canonical case 본문을 저장
3. `legal_relation`
   - 법령명, 관련 조문, 검색 hit, 일부 사건번호 참조(`cited_case`)까지 저장

핵심 흐름은 다음과 같다.

- `01_current_law`: 현행 법령 family 수집
- `02_related_legal_docs`: 관련 ~례 후보 수집 + canonical case detail hydrate
- `03_expanded_related_docs`: 법령↔사례 relation 생성
- `dataset`: 최종 JSONL 생성
- `emb/handoff`: 3-collection 임베딩 및 적재용 handoff 생성
---

## 2. 실행

### 2-1. 요구사항

- Python `>= 3.12`
- `uv` 사용 권장
- `.env` 파일에 `LAW_OC=<국가법령정보 API 키>` 필요

### 2-2. 설치(프로젝트 루트 기준)

```bash
uv apps/backend/legal-pipeline/ sync
```

### 2-3. 전체 수집 + 전처리 + dataset 생성(프로젝트 루트 기준)

```bash
uv run apps/backend/legal-pipeline/main.py
```

이 명령은 아래를 순서대로 수행한다.

1. 설정 파일 로드 및 validation
2. `01_current_law` 수집
3. `02_related_legal_docs` 후보 수집
4. canonical case hydrate
5. `03_expanded_related_docs` relation 생성
6. `data/dataset/legal_corpus.jsonl`, `data/dataset/legal_relations.jsonl` 생성

### 2-4. current law만 먼저 실행하거나, 캐시된 결과로 dataset만 다시 만들고 싶을 때

```bash
uv run apps/backend/legal-pipeline/scripts/run_current_law_collection.py
```

기존 산출물만 사용해 dataset을 다시 만들려면:

```bash
uv run apps/backend/legal-pipeline/scripts/run_current_law_collection.py --rebuild-only
```

루트 법령 수를 줄여서 소량 테스트하려면:

```bash
uv run apps/backend/legal-pipeline/scripts/run_current_law_collection.py --max-roots 1
```

## 3. 임베딩

### 3-1. 전제 조건

반드시 아래 파일이 생성된 상태

- `apps/backend/legal-pipeline/data/dataset/legal_corpus.jsonl`
- `apps/backend/legal-pipeline/data/dataset/legal_relations.jsonl`

### 3-2. 3-collection 임베딩 실행

```bash
uv run apps/backend/legal-pipeline/scripts/embed_qdrant_3collections.py
```

옵션 예시:

```bash
uv run apps/backend/legal-pipeline/scripts/embed_qdrant_3collections.py \
  --dataset-dir data/dataset \
  --emb-dir apps/backend/legal-pipeline/data/emb/qdrant_3collections \
  --handoff-dir data/handoff/qdrant_3collections \
  --batch-size 32
```

### 3-3. 임베딩 결과

- `data/emb/qdrant_3collections/`
  - `law_article.body.npy`
  - `law_article.appendix.npy`
  - `legal_case.npy`
  - `legal_relation.npy`
  - 각 collection별 `*.meta.jsonl`, `*.manifest.json`
- `data/handoff/qdrant_3collections/source/`
  - source JSONL
- `data/handoff/qdrant_3collections/import/`
  - Qdrant 적재용 import JSONL
- `data/handoff/qdrant_3collections/qdrant_embedding_manifest.json`

### 3-4. OpenSearch 인덱스 생성 / 전체 적재

로컬에서 Qdrant/OpenSearch를 같이 띄우려면:

```bash
docker compose \
  -f apps/backend/legal-pipeline/docker-compose.local-search.yml \
  up -d
```

로컬 서버 사용 시 환경변수 예시:

```bash
export QDRANT_URL="http://localhost:6333"
export OPENSEARCH_URL="http://localhost:9200"
export OPENSEARCH_INDEX_LAW_ARTICLE="law_article"
export OPENSEARCH_INDEX_LEGAL_CASE="legal_case"
export OPENSEARCH_INDEX_LEGAL_RELATION="legal_relation"
```

`OPENSEARCH_ENABLE_NORI_POS_FILTER` 는 기본 비활성화다. 로컬이나 일부 OpenSearch 배포에서 `nori_part_of_speech` 필터를 지원하지 않을 수 있으므로, 별도 확인 전에는 비워 두는 것을 권장한다.

필요 환경변수 예시:

```bash
export OPENSEARCH_URL="http://cg-rookies.ragdoll-ule.ts.net:9200"
export OPENSEARCH_INDEX_LAW_ARTICLE="law_article"
export OPENSEARCH_INDEX_LEGAL_CASE="legal_case"
export OPENSEARCH_INDEX_LEGAL_RELATION="legal_relation"
```

인덱스 생성:

```bash
uv run apps/backend/legal-pipeline/scripts/upload/index_opensearch.py
```

전체 적재:

```bash
uv run apps/backend/legal-pipeline/scripts/upload/load_opensearch.py
```

dry-run 시 bulk NDJSON만 생성:

```bash
uv run apps/backend/legal-pipeline/scripts/upload/load_opensearch.py --dry-run
```

### 3-5. 증분 업데이트 + OpenSearch 반영

증분 patch 기준 OpenSearch 반영:

```bash
uv run apps/backend/legal-pipeline/scripts/upload/load_opensearch_incremental.py \
  --dataset-patch-dir data/dataset/patches/<REG_DT>
```

메인 증분 워크플로우에서 OpenSearch까지 함께 실행:

```bash
uv run apps/backend/legal-pipeline/scripts/run_incremental_law_update.py \
  --reg-dt <REG_DT>
```

OpenSearch 반영 없이 증분 데이터만 만들려면:

```bash
uv run apps/backend/legal-pipeline/scripts/run_incremental_law_update.py \
  --reg-dt <REG_DT> \
  --skip-opensearch-upload
```

OpenSearch payload만 검증하려면:

```bash
uv run apps/backend/legal-pipeline/scripts/run_incremental_law_update.py \
  --reg-dt <REG_DT> \
  --opensearch-dry-run
```

## 4. 최종 실행 시 생성되는 `data/` 폴더 구조

아래는 **full run + embedding 이후** 기준 권장 구조다.

```text
data/
├── raw/
│   ├── 01_current_law/
│   │   └── <root_law>/
│   ├── 01_current_law_body/
│   │   └── <root_law>/
│   ├── 01_current_sub_article/
│   │   └── <root_law>/
│   ├── 01_current_law_appendix_assets/         # optional
│   └── 02_related_legal_docs/
│       └── <root_law>/
│           ├── candidate_hits.jsonl
│           ├── canonical_cases.jsonl
│           ├── canonical/
│           │   └── <target>/
│           │       └── <case>__detail.json
│           ├── <target>/<law_name>/...list.json
│           ├── <root_law>__related_docs_manifest.json
│           └── <root_law>__canonical_cases_manifest.json
├── normalized/
│   ├── 01_current_law/
│   │   └── <root_law>/
│   ├── 01_current_law_appendix/
│   │   └── <root_law>/
│   └── 01_current_law_appendix_assets/         # optional
├── expanded/
│   └── 03_expanded_related_docs/
│       └── <root_law>/
│           ├── relation_records.jsonl
│           ├── <target>/
│           │   └── <case>__<law_uid>__expanded.json
│           └── <root_law>__expanded_manifest.json
├── dataset/
│   ├── legal_corpus.jsonl
│   ├── legal_relations.jsonl
│   ├── dataset_manifest.json
│   ├── article_appendix_links.jsonl
│   ├── appendix_bundle_records.jsonl
│   ├── unresolved_appendix_records.jsonl
│   ├── article_appendix_manifest.json
│   ├── legal_appendix_raw.jsonl                # optional legacy
│   ├── legal_appendix_clean.jsonl              # optional legacy
│   ├── legal_appendix_table.jsonl              # optional legacy
│   └── appendix_dataset_manifest.json          # optional legacy
├── emb/
│   └── qdrant_3collections/
│       ├── law_article.body.npy
│       ├── law_article.appendix.npy
│       ├── legal_case.npy
│       ├── legal_relation.npy
│       ├── *.meta.jsonl
│       └── *.manifest.json
├── handoff/
│   ├── qdrant_3collections/
│   │   ├── source/
│   │   │   ├── law_article.jsonl
│   │   │   ├── legal_case.jsonl
│   │   │   └── legal_relation.jsonl
│   │   ├── import/
│   │   │   ├── law_article_for_import.jsonl
│   │   │   ├── legal_case_for_import.jsonl
│   │   │   └── legal_relation_for_import.jsonl
│   │   └── qdrant_embedding_manifest.json
│   ├── opensearch_bulk/
│   │   ├── law_article.bulk.ndjson
│   │   ├── legal_case.bulk.ndjson
│   │   ├── legal_relation.bulk.ndjson
│   │   └── opensearch_bulk_manifest.json
│   └── opensearch_incremental/
│       └── <REG_DT>/
│           ├── law_article.upsert.ndjson
│           ├── law_article.delete.ndjson
│           ├── legal_case.upsert.ndjson
│           ├── legal_case.delete.ndjson
│           ├── legal_relation.upsert.ndjson
│           ├── legal_relation.delete.ndjson
│           └── opensearch_incremental_manifest.json
└── manifest/
    ├── full_collection_summary.json
    ├── current_law_collection_summary.json
    ├── appendix_validation_summary.json
    └── appendix_asset_pipeline_summary.json    # optional
