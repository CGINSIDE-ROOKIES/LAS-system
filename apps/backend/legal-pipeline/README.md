# legal-pipeline README / 진행 현황 정리

국가법령정보 OPEN API 기반 dataset 생성 + 검색 적재 산출물 생성

- `law_article`: 현행 법령 조문 본문 + 부칙 + 별표 연계 정보
- `legal_case`: 판례/헌재결정례/법령해석례/행정심판례 본문
- `legal_relation`: 법령↔사례 관계 정보

## 1. 기능 목적
국가법령정보 Open API 수집을 유지하면서 dataset과 검색 적재 산출물을 생성한다.

1. `law_article`
   - 현행 법령 조문을 중심으로 저장한다.
   - 별표는 별도 collection이 아니라 `law_article` payload 및 appendix vector로 통합한다.
2. `legal_case`
   - `prec`, `detc`, `expc`, `decc`의 dedupe된 canonical case 본문을 저장한다.
3. `legal_relation`
   - 법령명, 관련 조문, 검색 hit, 일부 사건번호 참조(`cited_case`)까지 저장한다.

핵심 흐름은 다음과 같다.

- `01_current_law`: 현행 법령 family 수집
- `02_related_legal_docs`: 관련 ~례 후보 수집 + canonical case detail hydrate
- `03_expanded_related_docs`: 법령↔사례 relation 생성
- `dataset`: 최종 JSONL 생성
- `emb/handoff`: 현재 `law_article`, `legal_case` 임베딩 및 적재용 handoff 생성
- `legal_relation`: dataset/OpenSearch 레이어에는 유지하고 Qdrant 임베딩 대상에서는 제외
---

## 2. 실행

### 2-1. 요구사항

- Python `==3.13.*`
- Python `==3.13.*`
- `uv` 사용 권장
- `.env` 파일에 `LAW_OC=<국가법령정보 API 키>` 필요
- 임베딩 생성 시 `OPENAI_API_KEY` 필요
- 임베딩 생성 시 `OPENAI_API_KEY` 필요

### 2-2. 설치(프로젝트 루트 기준)

```bash
uv sync --project apps/backend/legal-pipeline
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

현재 정책:

- dataset는 계속 `law_article`, `legal_case`, `legal_relation` 3종을 생성
- Qdrant용 새 임베딩 생성은 현재 `law_article`, `legal_case`만 대상
- `legal_relation`은 현재 OpenSearch only 정책으로 유지
- `legal_relation`은 source/import JSONL은 계속 생성하지만 `.npy` 임베딩은 만들지 않는다
- 현재 기준 manifest는 OpenAI `text-embedding-3-large`, `1024`차원, `law_article 1982`, `legal_case 73690`이다

임베딩 backend는 OpenAI-compatible API만 사용한다.
임베딩 backend는 OpenAI-compatible API만 사용한다.

```bash
export EMBEDDING_MODEL="text-embedding-3-large"
export OPENAI_API_KEY="<YOUR_OPENAI_API_KEY>"
# 선택 사항: 기본 차원 대신 축소할 때만 지정
# export OPENAI_BASE_URL="https://api.openai.com/v1"
# export OPENAI_EMBEDDING_DIMENSIONS="1024"
# 선택 사항: 기본 차원 대신 축소할 때만 지정
# export OPENAI_BASE_URL="https://api.openai.com/v1"
# export OPENAI_EMBEDDING_DIMENSIONS="1024"
```

### 3-2. Qdrant 임베딩 실행

현재 full embedding 대상:

- `law_article`
- `legal_case`

`legal_relation`은 dataset/OpenSearch 산출물에는 남고, 현재는 OpenSearch only로 유지한다. Qdrant 새 임베딩 생성 대상에서는 제외한다.

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
  - 각 collection별 `*.meta.jsonl`, `*.manifest.json`
- `data/handoff/qdrant_3collections/source/`
  - source JSONL
- `data/handoff/qdrant_3collections/import/`
  - Qdrant 적재용 import JSONL
- `data/handoff/qdrant_3collections/qdrant_embedding_manifest.json`

참고:

<<<<<<< Updated upstream
- `legal_relation` 임베딩 파일(`.npy`, `*.meta.jsonl`, `*.manifest.json`)은 현재 정책상 생성하지 않는다.
- `legal_relation`은 현재 OpenSearch 적재 대상으로 유지한다.
- retrieval profile에는 `legal_relation` 항목이 남아 있을 수 있지만 현재 manifest 기준 `available=false`다.
=======
- 현재 스크립트는 `legal_relation` 임베딩을 만들지 않는다.
- `legal_relation`은 현재 OpenSearch 적재 대상으로 유지한다.
>>>>>>> Stashed changes

### 3-4. 현재 운영 기준 명령 순서


```bash
uv run --project apps/backend/legal-pipeline pytest apps/backend/legal-pipeline/tests -q
uv run --project apps/backend/legal-pipeline python apps/backend/legal-pipeline/scripts/rebuild_dataset_and_handoff.py --skip-embed
uv run --project apps/backend/legal-pipeline python apps/backend/legal-pipeline/scripts/embed_qdrant_3collections.py
uv run --project apps/backend/legal-pipeline python apps/backend/legal-pipeline/scripts/upload/indexing.py
uv run --project apps/backend/legal-pipeline python apps/backend/legal-pipeline/scripts/upload/load_qdrant.py
uv run --project apps/backend/legal-pipeline python apps/backend/legal-pipeline/scripts/upload/index_opensearch.py
uv run --project apps/backend/legal-pipeline python apps/backend/legal-pipeline/scripts/upload/load_opensearch.py
```

### 3-5. OpenSearch 인덱스 생성 / 전체 적재

로컬에서 Qdrant/OpenSearch를 같이 띄우려면:

```bash
docker compose \
  -f apps/backend/legal-pipeline/docker-compose.local-search.yml \
  up -d
```

OpenSearch Dashboards 확인:

```text
http://localhost:5601
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

### 3-6. 증분 업데이트 + OpenSearch 반영

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
│       ├── *.meta.jsonl
│       └── *.manifest.json
├── handoff/
│   ├── qdrant_3collections/
│   │   ├── source/
│   │   │   ├── law_article.jsonl
│   │   │   ├── legal_case.jsonl
│   │   ├── import/
│   │   │   ├── law_article_for_import.jsonl
│   │   │   ├── legal_case_for_import.jsonl
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
```

## 5. Neo4j 일반 배포 준비

현재 `legal-pipeline` 안에서 지원하는 Neo4j 경로는 full graph export + full reseed 기준이다.

- export source: `data/dataset/legal_corpus.jsonl`, `data/dataset/legal_relations.jsonl`
- current graph scope:
  - `Law`
  - `Article`
  - `HAS_ARTICLE`
  - `HAS_CHILD_LAW`
  - `DELEGATES_TO_LAW`
  - `REFERS_TO_LAW`
  - `REFERS_TO_ARTICLE`
- incremental Neo4j patching은 아직 지원하지 않는다.

### 5-1. 환경변수

운영 기준 환경변수는 아래 4개를 필수로 본다.

```env
NEO4J_URI=bolt://<host>:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<strong-password>
NEO4J_DATABASE=neo4j
```

예시 파일은 `apps/backend/legal-pipeline/.env.neo4j.example` 를 사용한다.

### 5-2. 로컬 검증용 Neo4j 실행

로컬에서 빠르게 검증할 때는 기존 local compose를 사용한다.

```bash
docker compose \
  -f apps/backend/legal-pipeline/docker-compose.local-neo4j.yml \
  up -d
```

기본 접속 예시:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=testtest12
NEO4J_DATABASE=neo4j
```

브라우저:

```text
http://localhost:7474
```

### 5-3. VM + Docker 운영 배포 기준

운영 VM에서는 `apps/backend/legal-pipeline/docker-compose.neo4j.yml` 기준으로 배포한다.

권장 절차:

1. VM에 Docker / Docker Compose plugin 설치
2. `apps/backend/legal-pipeline/.env.neo4j.example`를 복사해 실제 값으로 채움
3. compose로 Neo4j 기동
4. dataset 최신화 후 graph export 실행
5. seed 스크립트로 full reseed 수행

기동 예시:

```bash
docker compose \
  --env-file apps/backend/legal-pipeline/.env.neo4j.example \
  -f apps/backend/legal-pipeline/docker-compose.neo4j.yml \
  up -d
```

주의:

- 운영에서는 local compose의 고정 비밀번호를 사용하지 않는다.
- `neo4j_data`, `neo4j_logs` volume은 유지형으로 본다.
- 1차 운영은 full reseed 기준이므로 재적재 시점을 명시적으로 잡아야 한다.

### 5-4. Graph export

dataset가 준비된 뒤 graph export를 수행한다.

```bash
uv run --project apps/backend/legal-pipeline \
  python apps/backend/legal-pipeline/scripts/export_law_graph.py \
  --output-dir apps/backend/legal-pipeline/data/handoff/law_graph_v1
```

기본 산출물:

- `graph_law_nodes.jsonl`
- `graph_article_nodes.jsonl`
- `graph_edges_has_article.jsonl`
- `graph_edges_has_child_law.jsonl`
- `graph_edges_delegates_to_law.jsonl`
- `graph_edges_refers_to_law.jsonl`
- `graph_edges_refers_to_article.jsonl`
- `graph_manifest.json`

### 5-5. Neo4j seed

export 결과를 기준으로 full seed를 수행한다.

```bash
uv run --project apps/backend/legal-pipeline \
  python apps/backend/legal-pipeline/scripts/seed_law_graph_neo4j.py \
  --graph-dir apps/backend/legal-pipeline/data/handoff/law_graph_v1
```

dry-run으로 row count만 먼저 확인하려면:

```bash
uv run --project apps/backend/legal-pipeline \
  python apps/backend/legal-pipeline/scripts/seed_law_graph_neo4j.py \
  --graph-dir apps/backend/legal-pipeline/data/handoff/law_graph_v1 \
  --dry-run
```

### 5-6. 운영 순서

현재 권장 운영 순서는 아래다.

1. `pytest`
2. dataset rebuild
3. graph export
4. Neo4j full reseed

예시:

```bash
uv run --project apps/backend/legal-pipeline pytest apps/backend/legal-pipeline/tests -q
uv run --project apps/backend/legal-pipeline python apps/backend/legal-pipeline/scripts/rebuild_dataset_and_handoff.py --skip-embed
uv run --project apps/backend/legal-pipeline python apps/backend/legal-pipeline/scripts/export_law_graph.py --output-dir apps/backend/legal-pipeline/data/handoff/law_graph_v1
uv run --project apps/backend/legal-pipeline python apps/backend/legal-pipeline/scripts/seed_law_graph_neo4j.py --graph-dir apps/backend/legal-pipeline/data/handoff/law_graph_v1
```
