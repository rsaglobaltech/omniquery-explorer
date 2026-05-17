# OmniQuery Explorer

**Agentic Exploratory Data Analysis (EDA) for relational databases using natural language.**

OmniQuery Explorer turns plain-language business questions into safe SQL, executes them on real databases, and returns interpretable analytical reports. CLI **and** HTTP API, multi-engine, multi-LLM, with built-in governance (cost guard, PII masking, SQL hardening, observability).

---

## What this project is

Most NL-to-SQL tools stop at query generation. OmniQuery Explorer runs an end-to-end EDA pipeline:

- Understands the database structure automatically
- Profiles and ranks the most relevant tables
- Proposes high-value exploratory questions
- Generates and executes read-only SQL
- Recovers from SQL errors with an automated correction loop
- Produces a structured analytical report

It is built as a clean hexagonal architecture so the same core powers the CLI, the FastAPI HTTP adapter, and (eventually) any other driving adapter.

---

## Core capabilities

### Pipeline

- **Natural language → SQL** with schema-aware prompting and two-phase generation.
- **AST-based SQL guard** (sqlglot): rejects DML, DDL, CTE-wrapped DML, multiple statements, and a blocklist of dangerous functions (`pg_sleep`, `dblink`, `xp_cmdshell`, …).
- **Dialect-aware `LIMIT` / `FETCH FIRST`** rewriting.
- **Automatic schema introspection** (tables, columns, PKs, FKs).
- **Table profiling** (row counts, null ratios, cardinality, metric/date signals).
- **Graph-based table ranking** using foreign-key topology (PageRank + composite score).
- **Automated SQL repair loop** on execution failures.

### Multi-engine

PostgreSQL · MySQL/MariaDB · Oracle · SQLite · DuckDB. Adapters share a pooled `AsyncEngine` (LRU, `pool_pre_ping`, recycle) and a dialect-aware statement timeout (`statement_timeout` / `MAX_EXECUTION_TIME` / `asyncio.wait_for`).

### Multi-LLM

Ollama (local) · OpenAI · Anthropic. Switch with `LLM_PROVIDER` and `LLM_MODEL`. All adapters share prompt builders, retry/back-off (`tenacity`), and OTel span instrumentation.

### Governance

- **Cost guard**: `EXPLAIN (FORMAT JSON)` (Postgres) / `EXPLAIN FORMAT=JSON` (MySQL) reject queries above configurable cost / row thresholds.
- **Budget tracker**: per-session caps on queries and LLM tokens.
- **PII policy**: regex denylist redacts sensitive columns from the prompt **and** masks the values in returned rows.

### Interfaces

- **CLI** (`omniquery`) with `ask`, `explore`, `suggest`, `profile`, `schema`.
- **HTTP API** (`omniquery-web` → `uvicorn`) with `/ask`, `/ask/stream` (SSE), `/explore`, `/schema`, `/health`. API-key auth + token-bucket rate limiter.

### Operability

- **Pydantic Settings** typed config (envs / `.env` / nested `Settings` blocks).
- **Persistence** of sessions, queries, reports (SQLite default, Postgres in prod) with **Alembic** migrations applied at boot.
- **Disk-backed cache** for introspected schemas and embeddings.
- **OpenTelemetry** spans on every LangGraph node and every LLM HTTP call (toggle with `OBS_OTEL_ENABLED`).
- **Structured JSON logging** with session + agent correlation.

### Delivery

- **GitHub Actions CI**: ruff + mypy + pytest + bandit + pip-audit.
- **Multi-arch Docker image** (`linux/amd64` + `linux/arm64`) built via Buildx in `release.yml`, published to GHCR with SBOM + provenance attestations on tag push.
- **`docker-compose.yml`** for the single-machine path (Ollama + API + persistence volume).
- **Kubernetes manifests** under `deploy/k8s/`.

---

## Architecture

Hexagonal (ports & adapters) with explicit DDD boundaries:

```text
Driving adapters
  ├── adapters/cli         (Typer + Rich)
  └── adapters/web         (FastAPI + SSE, API key auth, rate limiter)

Application
  ├── use_cases/RunEdaUseCase
  └── agents/EdaSessionGraph        (LangGraph state graph)

Domain
  ├── entities (Table, Column, DatabaseSchema, ScoredTable, …)
  └── ports
        ├── inbound  (EdaUseCase)
        └── outbound (DatabasePort, LlmPort, EmbeddingPort, ProfilingPort)

Infrastructure
  ├── db                (postgres / mysql / oracle / sqlite / duckdb adapters
  │                     + engine_pool + sql_guard + statement_timeout
  │                     + sql_profiling_adapter)
  ├── llm               (ollama / openai / anthropic + shared prompt builders)
  ├── graph             (schema_graph_service + schema_linker)
  ├── cache             (disk_cache + cached_database + cached_embedding)
  ├── governance        (cost_guard, pii_policy)
  ├── observability     (OpenTelemetry tracer)
  ├── persistence       (SQLAlchemy ORM + Alembic + PersistenceStore)
  └── logging
```

---

## Quickstart

### Local install (uv)

```bash
uv sync
ollama pull llama3.2:latest
ollama serve &

export DATABASE_URL="postgresql+asyncpg://user:pwd@localhost:5432/db"
uv run omniquery ask "What are the top 10 customers by total orders?"
```

### HTTP API

```bash
uv run omniquery-web        # serves on :8000 (override via WEB_HOST/PORT)
curl http://localhost:8000/health
```

### Single-machine Docker

```bash
docker compose up -d
docker compose exec ollama ollama pull llama3.2:latest
curl http://localhost:8000/health
```

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for the production path (Kubernetes, env reference, prod checklist, troubleshooting).

---

## CLI commands

- `omniquery ask "<question>"` — single NL EDA query.
- `omniquery explore` — full multi-agent exploration.
- `omniquery suggest` — generate suggested EDA questions.
- `omniquery profile --top N` — top-ranked tables and profiling metrics.
- `omniquery schema` — print schema details (tables, columns, PKs, FKs).

## HTTP endpoints

- `GET  /health` — liveness + config snapshot.
- `POST /ask` — synchronous EDA query (JSON).
- `POST /ask/stream` — same flow as SSE.
- `POST /explore` — schema + profiling + proposed questions.
- `POST /schema` — schema introspection.

All write endpoints require `X-API-Key` when `ENVIRONMENT=production`. All endpoints are rate-limited per identity (API key or IP) via a token bucket (`WEB_RATE_LIMIT_PER_MINUTE`, default 60).

---

## Configuration

Every knob is a typed Pydantic Setting; see `src/omniquery/config.py` for the source of truth. Highlights:

| Group          | Variable                                  | Default                                | Notes                                              |
|----------------|-------------------------------------------|----------------------------------------|----------------------------------------------------|
| LLM            | `LLM_PROVIDER`                            | `ollama`                               | `ollama` / `openai` / `anthropic`                  |
| LLM            | `LLM_MODEL`                               | `llama3.2:latest`                      |                                                    |
| DB             | `DATABASE_URL`                            | _unset_                                | Default analysed DB                                |
| DB             | `DB_STATEMENT_TIMEOUT_MS`                 | `30000`                                |                                                    |
| Web            | `WEB_API_KEYS`                            | _unset_                                | Comma-separated; required in production            |
| Web            | `WEB_RATE_LIMIT_PER_MINUTE`               | `60`                                   | 0 disables                                         |
| Cost guard     | `COST_EXPLAIN_ENABLED`                    | `false`                                | Turn on the EXPLAIN cost gate                      |
| Cost guard     | `COST_MAX_PLAN_COST` / `COST_MAX_PLAN_ROWS` | 1e6 / 5e7                            | Engine planner units                               |
| Cost guard     | `COST_MAX_QUERIES_PER_SESSION` / `…TOKENS` | 100 / 1e6                             | Per-session caps                                   |
| PII            | `PII_DENYLIST_PATTERNS`                   | _(curated regex)_                      | Override to fit your schema                        |
| Cache          | `CACHE_SCHEMA_TTL_SECONDS`                | `3600`                                 | Embedding TTL configurable separately              |
| Persistence    | `PERSIST_DATABASE_URL`                    | `sqlite+aiosqlite:///.tmp/omniquery.db`| Move to Postgres in prod                           |
| Observability  | `OBS_OTEL_ENABLED` / `OBS_OTEL_ENDPOINT`  | `false` / _unset_                      | OTLP/HTTP exporter                                 |

---

## Evaluation harness

A pytest-driven text-to-SQL evaluation harness lives under `tests/eval/`.
Each dataset is a YAML file pairing a fixture DB with NL questions and
(optionally) ground-truth rows.

Metrics tracked per dataset:

- `execution_accuracy` (correct rows or non-empty result vs total)
- `fix_rate` (cases that needed the LLM repair loop)
- `latency_p50`, `latency_p95` (ms)

Run:

```bash
# Sanity tests (no LLM, run in default CI)
uv run pytest tests/eval/test_harness_meta.py -q

# Full harness against the configured provider (requires Ollama/OpenAI/Anthropic)
uv run pytest tests/eval -m eval -q
```

Producing a baseline report is a one-liner:

```bash
uv run python -m tests.eval.runner tests/eval/datasets/ecommerce.yaml > baseline.json
```

See `tests/eval/README.md` for the dataset schema and adding cases.

---

## Tech stack

Python 3.12 · uv · Typer + Rich · FastAPI + uvicorn · SQLAlchemy 2 async + asyncpg / aiomysql / oracledb / aiosqlite / duckdb_engine · LangGraph + LangChain Core · Ollama / OpenAI / Anthropic · sqlglot · NetworkX + Matplotlib · OpenTelemetry · Pydantic Settings · Alembic.

## Project structure

```text
src/omniquery/
  adapters/{cli,web}
  application/{agents,use_cases}
  domain/{entities,ports/{inbound,outbound}}
  infrastructure/{db,llm,graph,cache,governance,observability,persistence,logging}
deploy/k8s/
docs/DEPLOYMENT.md
tests/{unit,integration,e2e,eval}
```

## Roadmap

See [`IMPROVEMENTS.md`](IMPROVEMENTS.md) for the full P0-P3 plan with per-iniciativa status and commit references.
