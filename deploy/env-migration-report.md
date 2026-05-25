# 환경변수 마이그레이션 리포트

이 문서는 이전 환경변수 이름을 현재 이름으로 바꾸는 기준을 정리한다. 현재 코드는 legacy 이름을 fallback으로 읽지 않는다. 배포 환경에서는 `deploy/.env.example`, 로컬 backend에서는 `apps/backend/.env.example`, 로컬 frontend에서는 `apps/frontend/.env.example`만 기준으로 사용한다.

## 메인 LLM

| 기존 이름 | 현재 이름 | 비고 |
| --- | --- | --- |
| `GEMINI_MODEL` | `LLM_MODEL` | `LLM_PROVIDER=gemini`와 같이 사용 |
| `GEMINI_API_KEY` | `LLM_API_KEY` | Gemini 호출 키 |
| `GEMINI_API_URL` | `LLM_URL` | Gemini endpoint를 직접 지정할 때만 사용 |
| `LLM_CHAT_COMPLETIONS_URL` | `LLM_URL` | OpenAI-compatible full `/v1/chat/completions` endpoint |
| `OPENAI_API_KEY` | `LLM_API_KEY` 또는 `EMBEDDING_API_KEY` | chat LLM 키면 `LLM_API_KEY`, embedding 키면 `EMBEDDING_API_KEY` |
| `OPENAI_BASE_URL` | `LLM_BASE_URL` 또는 `EMBEDDING_BASE_URL` | chat LLM base URL이면 `LLM_BASE_URL`, embedding base URL이면 `EMBEDDING_BASE_URL` |

Provider 옵션:

- `LLM_PROVIDER=gemini`
- `LLM_PROVIDER=openai_compat`

OpenAI-compatible provider는 `LLM_URL` 또는 `LLM_BASE_URL` 중 하나가 필요하다.

## Query Parser

| 기존 이름 | 현재 이름 |
| --- | --- |
| `QUERY_PARSER_MODEL` | `QUERY_PARSER_LLM_MODEL` |
| `QUERY_PARSER_TIMEOUT` | `QUERY_PARSER_LLM_TIMEOUT` |
| `QUERY_PARSER_STRICT` | `QUERY_PARSER_LLM_STRICT` |

`QUERY_PARSER_LLM_STRICT` 옵션:

- `false`
- `true`

## Graph Planner

Graph planner는 현재 아래 이름만 사용한다.

```env
GRAPH_QUERY_MODE=llm_free
GRAPH_LLM_PROVIDER=gemini
GRAPH_LLM_MODEL=gemini-2.5-flash-lite
GRAPH_LLM_URL=
GRAPH_LLM_API_KEY=
GRAPH_LLM_TIMEOUT=15
GRAPH_LLM_MAX_TOKENS=2048
GRAPH_LLM_TEMPERATURE=0
```

`GRAPH_QUERY_MODE` 옵션:

- `template`
- `llm_free`
- `llm_free_with_template_fallback`

## Embedding

| 기존 이름 | 현재 이름 |
| --- | --- |
| `OPENAI_API_KEY` | `EMBEDDING_API_KEY` |
| `OPENAI_BASE_URL` | `EMBEDDING_BASE_URL` |
| `OPENAI_EMBEDDING_DIMENSIONS` | `EMBEDDING_DIMENSIONS` |
| `OPENAI_MAX_INPUT_TOKENS` | `EMBEDDING_MAX_INPUT_TOKENS` |
| `OPENAI_MAX_BATCH_TOKENS` | `EMBEDDING_MAX_BATCH_TOKENS` |
| `OPENAI_MAX_RETRIES` | `EMBEDDING_MAX_RETRIES` |
| `OPENAI_RETRY_BASE_DELAY_SEC` | `EMBEDDING_RETRY_BASE_DELAY_SEC` |

현재 embedding provider 옵션은 `openai_compat`만 지원한다.

## Law Updater

law-updater 전용 `LAW_UPDATER_OPENAI_*` / `LAW_UPDATER_EMBEDDING_*` override는 제거했다. law-updater도 shared `EMBEDDING_*` 값을 사용한다.

## Doc Processor LLM

`DOC_PROCESSOR_LLM_*`는 doc_processor 전용 이름으로 유지한다. full chat completions endpoint는 `DOC_PROCESSOR_LLM_URL`, base URL은 `DOC_PROCESSOR_LLM_BASE_URL`에 둔다.

Provider 옵션:

- `openai`
- `openai_compat`
- `gemini`

Structured output 옵션:

- `json_mode`
- `json_schema`

## Neo4j

| 기존 이름 | 현재 이름 |
| --- | --- |
| `NEO4J_USERNAME` | `NEO4J_USER` |

## 제거된 항목

`MIDM_LLM_URL`은 현재 코드와 compose에서 사용하는 경로가 없어 제거 대상이다.

## 예시: Spark OpenAI-compatible 설정

기존:

```env
LLM_PROVIDER=openai_compat
LLM_CHAT_COMPLETIONS_URL=http://spark.cg-rookies.net/v1/chat/completions
LLM_MODEL=nvidia/Gemma-4-26B-A4B-NVFP4
LLM_API_KEY=sk-...
QUERY_PARSER_MODEL=nvidia/Gemma-4-26B-A4B-NVFP4
QUERY_PARSER_TIMEOUT=10
QUERY_PARSER_STRICT=false
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_EMBEDDING_DIMENSIONS=1024
```

현재:

```env
LLM_PROVIDER=openai_compat
LLM_MODEL=nvidia/Gemma-4-26B-A4B-NVFP4
LLM_URL=http://spark.cg-rookies.net/v1/chat/completions
LLM_BASE_URL=
LLM_API_KEY=sk-...

QUERY_PARSER_LLM_PROVIDER=openai_compat
QUERY_PARSER_LLM_MODEL=nvidia/Gemma-4-26B-A4B-NVFP4
QUERY_PARSER_LLM_URL=http://spark.cg-rookies.net/v1/chat/completions
QUERY_PARSER_LLM_API_KEY=sk-...
QUERY_PARSER_LLM_TIMEOUT=10
QUERY_PARSER_LLM_STRICT=false

EMBEDDING_PROVIDER=openai_compat
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-...
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_DIMENSIONS=1024
```

## 검증

```bash
docker compose --project-directory . --env-file deploy/.env.example -f deploy/docker-compose.yml config
```
