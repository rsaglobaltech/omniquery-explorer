<div align="center">

# 🔍 OmniQuery Explorer

### Agentic Exploratory Data Analysis for relational databases — in plain English.

**Ask your database questions in natural language. Get safe SQL, real rows, and a structured analytical report — automatically.**

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CI](https://img.shields.io/badge/CI-ruff%20%7C%20mypy%20%7C%20pytest%20%7C%20bandit-success.svg)](.github/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/docker-multi--arch-2496ED.svg)](Dockerfile)
[![Architecture](https://img.shields.io/badge/architecture-hexagonal%20%2B%20DDD-orange.svg)](#-architecture)

</div>

---

## 📖 Table of Contents

- [Why OmniQuery?](#-why-omniquery)
- [What it does](#-what-it-does)
- [Feature highlights](#-feature-highlights)
- [Architecture](#-architecture)
- [Quickstart](#-quickstart)
- [Usage](#-usage)
- [Configuration](#-configuration)
- [Security & Governance](#-security--governance)
- [Observability](#-observability)
- [Evaluation Harness](#-evaluation-harness)
- [Deployment](#-deployment)
- [Project Structure](#-project-structure)
- [Tech Stack](#-tech-stack)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## 💡 Why OmniQuery?

Most NL-to-SQL tools stop at *generating a query*. That's the easy half. The hard half is everything around it:

- ❌ The model invents column names that don't exist.
- ❌ It writes a `DELETE` masquerading as a `SELECT` inside a CTE.
- ❌ It nukes the warehouse with a 200M-row full scan.
- ❌ It leaks `email`, `ssn`, or `credit_card` into a prompt or report.
- ❌ It returns a CSV with no narrative, no chart, no follow-up.

**OmniQuery Explorer** is an end-to-end EDA platform that ships every guardrail you would otherwise have to build yourself: AST-based SQL hardening, cost gates, PII masking, query budgets, schema caching, automated SQL repair, structured reports, multi-LLM, multi-engine, observability, and a clean hexagonal architecture you can extend.

It's built for **data analysts**, **platform engineers**, and **product teams** who need fast exploration without sacrificing **control**, **traceability**, or **architecture quality**.

---

## 🧭 What it does

```
┌────────────────────┐    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Plain-English      │ →  │ Multi-agent      │ →  │ Verified, safe   │ →  │ Structured EDA   │
│ question           │    │ pipeline         │    │ SELECT execution │    │ report + chart   │
└────────────────────┘    └──────────────────┘    └──────────────────┘    └──────────────────┘
```

Under the hood, a **LangGraph state machine** runs eight specialised agents:

| Agent                  | Responsibility                                              |
|------------------------|-------------------------------------------------------------|
| `introspect`           | Extract schema metadata (tables, columns, PKs, FKs).        |
| `profile`              | Compute statistical profiles (rows, nulls, cardinality).    |
| `build_graph`          | Build FK graph, run PageRank, rank tables.                  |
| `propose_questions`    | Suggest exploratory questions aligned with the domain.      |
| `generate_sql`         | Two-phase generation: select tables → emit SQL.             |
| `execute_sql`          | Run the SELECT under guard, timeout, and EXPLAIN gate.      |
| `fix_sql`              | Self-heal on DB errors via bounded LLM repair loop.         |
| `generate_report`      | Produce the markdown EDA narrative.                         |

---

## ✨ Feature highlights

### 🛡️ Bullet-proof SQL pipeline

- **AST-based read-only guard** (sqlglot): rejects DML, DDL, CTE-wrapped DML, multiple statements, and a curated blocklist (`pg_sleep`, `dblink`, `xp_cmdshell`, `utl_file`, …).
- **Dialect-aware `LIMIT` / `FETCH FIRST`** rewriting via AST manipulation — never string concatenation.
- **Two-phase SQL generation**: the model picks tables from the full list *before* it ever sees a column, killing the "hallucinated join key" failure mode.
- **Self-healing retry loop**: on `ProgrammingError`/`OperationalError`, the verified DDL + the DB's own message are fed back to the LLM; bounded by configurable retries.
- **Per-statement timeout**: `SET LOCAL statement_timeout` (Postgres), `SET SESSION MAX_EXECUTION_TIME` (MySQL), `asyncio.wait_for` fallback (Oracle).

### 🌐 Multi-engine, multi-LLM, multilingual

- **Engines**: 🐘 PostgreSQL · 🐬 MySQL/MariaDB · 🟧 Oracle · 🪶 SQLite · 🦆 DuckDB.
- **LLMs**: 🦙 Ollama (fully local) · 🤖 OpenAI · 🧠 Anthropic · ☁️ AWS Bedrock · ☁️ Google Vertex AI. Switch with one env var; provider-specific retries via `tenacity`.
- **Languages**: 🇬🇧 English · 🇪🇸 Spanish, with `LLM_LANGUAGE=auto` to detect per question. The model answers questions, returns reports, and produces DB summaries in the same language the analyst asked in.
- **Pooled `AsyncEngine`**: process-wide LRU cache, `pool_pre_ping`, recycle every 30 min. No engine churn per query.

### 💰 Governance built-in

- **Cost guard**: `EXPLAIN (FORMAT JSON)` on Postgres and MySQL rejects queries above configurable plan cost or estimated rows — before they touch the data.
- **Budget tracker**: caps queries and LLM tokens per session in memory.
- **PII policy**: regex denylist redacts sensitive columns from the LLM prompt **and** masks values in returned rows. Default denylist covers `email`, `ssn`, `password`, `credit_card`, `iban`, `phone`, `address`, `dob`, `api_key`, `secret`, …

### 🚀 Two first-class interfaces

- **CLI** (`omniquery`) with `ask`, `explore`, `suggest`, `profile`, `schema`. Rich tables, charts, progress spinners.
- **HTTP API** (`omniquery-web` → `uvicorn`):
  - `POST /ask` — synchronous JSON.
  - `POST /ask/stream` — **Server-Sent Events** streaming agent-by-agent (`started`, `sql`, `rows`, `report`, `done`).
  - `POST /explore`, `POST /schema`, `GET /health`.
  - **API-key auth** (`X-API-Key`) and **token-bucket rate limiter** per identity (key or IP).

### 💾 Persistence + caching

- **Sessions, queries, reports** stored in SQLite by default (Postgres in prod) and managed with **Alembic** migrations applied at boot.
- **Disk-backed cache** for introspected schemas and embeddings — keyed by SHA-256 fingerprint, TTL-driven.

### 🔭 Observability

- **OpenTelemetry** spans on every LangGraph node (`agent.introspect`, `agent.generate_sql`, …) and every LLM call (`llm.call` tagged with provider, model, call name). Toggle with `OBS_OTEL_ENABLED`, export via OTLP/HTTP.
- **Structured JSON logging** with `session_id` / `agent` correlation throughout the pipeline.

### 🏗️ Production delivery

- **GitHub Actions CI**: `ruff` + `mypy` + `pytest` + `bandit` + `pip-audit`.
- **Multi-arch Docker image** (`linux/amd64` + `linux/arm64`) published to GHCR on tag push, with **SBOM** and **provenance** attestations.
- **`docker-compose.yml`** for the single-machine path; **Kubernetes manifests** under [`deploy/k8s/`](deploy/k8s/).
- **Typed configuration** via Pydantic Settings — every knob is type-checked and documented in [`src/omniquery/config.py`](src/omniquery/config.py).

---

## 🏛️ Architecture

OmniQuery follows **Hexagonal Architecture (Ports & Adapters)** with explicit DDD boundaries:

```
┌────────────────────────────────────────────────────────────────────┐
│                         Driving adapters                           │
│                                                                    │
│  ┌────────────────┐                       ┌────────────────────┐   │
│  │  CLI (Typer)   │                       │  Web (FastAPI+SSE) │   │
│  └────────┬───────┘                       └─────────┬──────────┘   │
└───────────┼─────────────────────────────────────────┼──────────────┘
            │                                         │
            ▼                                         ▼
┌────────────────────────────────────────────────────────────────────┐
│                          Application                               │
│                                                                    │
│  ┌─────────────────────────┐    ┌─────────────────────────────┐    │
│  │  RunEdaUseCase          │    │  EdaSessionGraph (LangGraph)│    │
│  └─────────────────────────┘    └─────────────────────────────┘    │
└────────────────────┬───────────────────────────────┬───────────────┘
                     │                               │
                     ▼                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                  Domain ports (interfaces only)                    │
│                                                                    │
│   DatabasePort · LlmPort · EmbeddingPort · ProfilingPort           │
└────────────────────┬───────────────────────────────┬───────────────┘
                     │                               │
                     ▼                               ▼
┌────────────────────────────────────────────────────────────────────┐
│                       Driven adapters                              │
│                                                                    │
│  db/        →  postgres · mysql · oracle · sqlite · duckdb         │
│  llm/       →  ollama · openai · anthropic                         │
│  graph/     →  schema_graph_service · schema_linker                │
│  cache/     →  disk_cache · cached_database · cached_embedding     │
│  governance/→  sql_guard · cost_guard · pii_policy                 │
│  observability/→  OpenTelemetry tracer                             │
│  persistence/→  SQLAlchemy ORM · Alembic                           │
│  logging/   →  structured JSON                                     │
└────────────────────────────────────────────────────────────────────┘
```

### Why this matters

- **The domain layer has zero infrastructure imports.** Swap PostgreSQL for DuckDB or Ollama for Anthropic by changing a single env var; the agents don't notice.
- **Every cross-cutting concern is a port.** PII, cost, observability, persistence — each lives in its own bounded module and is wired by the container at startup.
- **One container, many interfaces.** The CLI and the FastAPI app share the same singleton `Container` (LLM client, profiler, schema linker, caches), so warmth and quotas carry across.

---

## 🚀 Quickstart

### Option A — Run with Docker Compose (fastest)

```bash
git clone https://github.com/rsaglobaltech/omniquery-explorer.git
cd omniquery-explorer

docker compose up -d
docker compose exec ollama ollama pull llama3.2:latest

curl http://localhost:8000/health
# {"status":"ok","environment":"development","llm_provider":"ollama","llm_model":"llama3.2:latest"}
```

### Option B — Local install with `uv`

```bash
# 1. Install dependencies
uv sync

# 2. Configure the target database + LLM
export DATABASE_URL="postgresql+asyncpg://user:pwd@localhost:5432/db"
export LLM_PROVIDER=ollama
export LLM_MODEL=llama3.2:latest

# 3. Start the model server (local-first path)
ollama pull llama3.2:latest
ollama serve &

# 4. Ask a question
uv run omniquery ask "What are the top 10 customers by total orders?"
```

### Option C — Pull the published image

```bash
docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=openai \
  -e LLM_OPENAI_API_KEY=sk-... \
  -e DATABASE_URL='postgresql+asyncpg://user:pwd@host/db' \
  -e WEB_API_KEYS=secret-key \
  ghcr.io/rsaglobaltech/omniquery-explorer:0.1.0
```

---

## 🧪 Usage

### 🖥️ CLI

```bash
# Single natural-language EDA query
omniquery ask "Which customers spent the most last quarter?"

# Full exploration: schema → profile → propose questions → answer best one
omniquery explore

# Generate suggested EDA questions only
omniquery suggest

# Show statistical profile of the most important tables
omniquery profile --top 10

# Print the full schema (tables, columns, PKs, FKs)
omniquery schema
```

Override defaults with `--url`, `--max-rows`, or by exporting `DATABASE_URL`.

### 🌐 HTTP API

Synchronous JSON:

```bash
curl -X POST http://localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: secret-key' \
  -d '{
    "question": "Top 5 products by revenue this year",
    "connection_url": "postgresql+asyncpg://user:pwd@host/db",
    "max_rows": 100
  }'
```

Server-Sent Events (one event per pipeline stage):

```bash
curl -N -X POST http://localhost:8000/ask/stream \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: secret-key' \
  -d '{"question":"...","connection_url":"..."}'

# event: started
# data: {"question":"..."}
#
# event: sql
# data: {"sql":"SELECT ..."}
#
# event: rows
# data: {"count":5,"preview":[...]}
#
# event: report
# data: {"markdown":"# Top 5 Products..."}
#
# event: done
# data: {"row_count":5}
```

OpenAPI docs are served at `http://localhost:8000/docs`.

### 🐍 Python

The application layer is import-clean — you can drive it directly:

```python
import asyncio
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.infrastructure.container import get_container

async def main():
    container = get_container()
    use_case = container.eda_use_case("postgresql+asyncpg://user:pwd@host/db")
    result = await use_case.run_eda(
        EdaQuery(
            question="How many active subscriptions per plan?",
            connection_url="postgresql+asyncpg://user:pwd@host/db",
            max_rows=200,
        )
    )
    print(result.generated_sql)
    print(result.report)

asyncio.run(main())
```

---

## ⚙️ Configuration

Every knob is a typed Pydantic Setting. Source of truth: [`src/omniquery/config.py`](src/omniquery/config.py).

### 🔌 LLM provider

| Variable                  | Default              | Description                                  |
|---------------------------|----------------------|----------------------------------------------|
| `LLM_PROVIDER`            | `ollama`             | `ollama` · `openai` · `anthropic` · `bedrock` · `vertex`. |
| `LLM_MODEL`               | `llama3.2:latest`    | Provider-specific model identifier.          |
| `LLM_EMBEDDING_MODEL`     | `nomic-embed-text`   | Used by the semantic schema linker.          |
| `LLM_TIMEOUT`             | `300.0`              | HTTP timeout in seconds.                     |
| `LLM_MAX_RETRIES`         | `3`                  | Tenacity retry attempts on 5xx / 429.        |
| `LLM_LANGUAGE`            | `auto`               | `en` · `es` · `auto` (detect per question).  |
| `LLM_OLLAMA_BASE_URL`     | `http://localhost:11434` | Ollama HTTP endpoint.                    |
| `LLM_OPENAI_API_KEY`      | _unset_              | Required when `provider=openai`.             |
| `LLM_ANTHROPIC_API_KEY`   | _unset_              | Required when `provider=anthropic`.          |
| `LLM_BEDROCK_REGION`      | `us-east-1`          | AWS region for Bedrock (creds from boto3 chain). |
| `LLM_VERTEX_PROJECT`      | _unset_              | GCP project id for Vertex AI (ADC for creds). |
| `LLM_VERTEX_REGION`       | `us-east5`           | Vertex region.                               |

### 🗄️ Target database

| Variable                    | Default  | Description                                            |
|-----------------------------|----------|--------------------------------------------------------|
| `DATABASE_URL`              | _unset_  | Default connection URL for the CLI.                    |
| `DB_STATEMENT_TIMEOUT_MS`   | `30000`  | Per-statement timeout sent down to the engine.         |
| `DB_MAX_ROWS_DEFAULT`       | `500`    | Default cap on rows returned (overridable per call).   |

### 🌐 Web adapter

| Variable                     | Default | Description                                     |
|------------------------------|---------|-------------------------------------------------|
| `WEB_API_KEYS`               | _unset_ | Comma-separated allowlist; required in prod.    |
| `WEB_RATE_LIMIT_PER_MINUTE`  | `60`    | Token-bucket rate per identity. `0` disables.   |
| `WEB_CORS_ORIGINS`           | `*`     | Comma-separated CORS origins.                   |
| `WEB_HOST` / `WEB_PORT`      | `0.0.0.0` / `8000` | Bind address used by `omniquery-web`.|

### 💰 Cost guard

| Variable                       | Default      | Description                                   |
|--------------------------------|--------------|-----------------------------------------------|
| `COST_EXPLAIN_ENABLED`         | `false`      | Enable the `EXPLAIN` plan gate.               |
| `COST_MAX_PLAN_COST`           | `1_000_000`  | Engine planner units cap.                     |
| `COST_MAX_PLAN_ROWS`           | `50_000_000` | Rejects table scans above this estimate.      |
| `COST_MAX_QUERIES_PER_SESSION` | `100`        | In-memory per-session query cap.              |
| `COST_MAX_TOKENS_PER_SESSION`  | `1_000_000`  | In-memory per-session LLM token cap.          |

### 🔐 PII

| Variable                  | Default                          | Description                                |
|---------------------------|----------------------------------|--------------------------------------------|
| `PII_ENABLED`             | `true`                           | Master switch.                             |
| `PII_DENYLIST_PATTERNS`   | _(curated regex; see `config.py`)_| Case-insensitive regex for column names. |
| `PII_MASK_VALUE`          | `***`                            | Replacement token in returned rows.        |

### 💾 Persistence & cache

| Variable                            | Default                                       | Description                              |
|-------------------------------------|-----------------------------------------------|------------------------------------------|
| `PERSIST_DATABASE_URL`              | `sqlite+aiosqlite:///.tmp/omniquery.db`       | Move to Postgres in prod.                |
| `CACHE_ENABLED`                     | `true`                                        | Master cache toggle.                     |
| `CACHE_DIR`                         | `.tmp/cache`                                  | Local cache root.                        |
| `CACHE_SCHEMA_TTL_SECONDS`          | `3600`                                        | Schema cache TTL.                        |
| `CACHE_EMBEDDING_TTL_SECONDS`       | `86400`                                       | Embedding cache TTL.                     |

### 🔭 Observability

| Variable               | Default | Description                                              |
|------------------------|---------|----------------------------------------------------------|
| `OBS_OTEL_ENABLED`     | `false` | Enable OpenTelemetry export.                             |
| `OBS_OTEL_ENDPOINT`    | _unset_ | OTLP/HTTP collector URL (e.g. `http://otel:4318/v1/traces`). |
| `OBS_LOG_LEVEL`        | `INFO`  | Root log level.                                          |
| `OBS_LOG_PAYLOAD_LIMIT`| `2000`  | Truncation cap for logged prompts and SQL.               |

---

## 🛡️ Security & Governance

OmniQuery treats *generating safe SQL* as defence-in-depth, not the only barrier. Production deployments should still grant the app a **read-only DB role**. On top of that, the pipeline enforces:

1. **Single SELECT only**: every SQL string is parsed with sqlglot. Anything that isn't a pure `SELECT`/`UNION`/`WITH … SELECT` is rejected.
2. **No DML inside CTEs**: walks the AST to forbid `INSERT`/`UPDATE`/`DELETE`/`MERGE` anywhere in the tree.
3. **No DDL or admin commands**: `Create`, `Drop`, `Alter`, `TruncateTable`, `Command` nodes raise `SqlGuardError`.
4. **No dangerous functions**: `pg_sleep`, `pg_read_file`, `dblink`, `lo_import`, `xp_cmdshell`, `utl_file`, `dbms_lock`, … rejected by name.
5. **Per-statement timeout**: applied to the session *before* the query runs.
6. **EXPLAIN cost gate** (optional): Postgres `EXPLAIN (FORMAT JSON)` and MySQL `EXPLAIN FORMAT=JSON` veto queries whose planner estimate exceeds thresholds.
7. **Per-session quotas**: query count and LLM token count tracked in memory; surpassing the cap fails fast without touching DB or LLM.
8. **PII redaction**: sensitive columns are stripped from the schema the LLM sees, and replaced with `***` in the rows returned to the caller.
9. **API-key auth + rate limiter** on the HTTP adapter.
10. **CI security scans**: `bandit` (medium+) on every push; `pip-audit` for CVEs.

---

## 🔭 Observability

Every node in the LangGraph pipeline and every LLM call is wrapped in an **OpenTelemetry span**:

```
session
└── agent.introspect
└── agent.profile
└── agent.build_graph
└── agent.propose_questions
└── agent.generate_sql
    └── llm.call  (provider=ollama, call_name=table_selection)
    └── llm.call  (provider=ollama, call_name=generate_sql)
└── agent.execute_sql
└── agent.generate_report
    └── llm.call  (provider=ollama, call_name=generate_report)
```

Spans carry `session_id`, `agent`, and (for LLM calls) `provider`, `model`, `call_name`. Set `OBS_OTEL_ENABLED=true` and point `OBS_OTEL_ENDPOINT` at any OTLP/HTTP collector (Tempo, Jaeger, Honeycomb, Grafana Agent).

In parallel, **structured JSON logging** writes a record per agent transition with input/output snapshots and durations.

---

## 📏 Evaluation Harness

OmniQuery ships a pytest-driven text-to-SQL eval harness under [`tests/eval/`](tests/eval/). Each dataset is a YAML file pairing a fixture DB with NL questions and (optionally) ground-truth rows.

**Metrics tracked per dataset**:

- `execution_accuracy` — fraction of cases whose rows match the ground truth (or simply returned data when no ground truth is given).
- `fix_rate` — fraction of cases that needed the LLM repair loop.
- `latency_p50`, `latency_p95` — wall-clock latency percentiles per case.

**Run**:

```bash
# Sanity tests (no LLM, run in default CI)
uv run pytest tests/eval/test_harness_meta.py -q

# Full harness against the configured provider (requires Ollama/OpenAI/Anthropic)
uv run pytest tests/eval -m eval -q

# Produce a baseline JSON report
uv run python -m tests.eval.runner tests/eval/datasets/ecommerce.yaml > baseline.json
```

See [`tests/eval/README.md`](tests/eval/README.md) for the dataset schema and how to add new cases.

---

## 🚢 Deployment

Two topologies are supported out of the box:

1. **Single machine** — `docker compose up`. Fits most teams running ≤ 10 analysts.
2. **Kubernetes** — manifests under [`deploy/k8s/`](deploy/k8s/) (namespace, configmap, secret template, deployment, service, optional ingress).

The full deployment guide — env reference, production checklist, troubleshooting table, smoke-test snippets — lives in **[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)**.

### Production checklist

- ✅ Pin the image to a published tag (`ghcr.io/<org>/omniquery-explorer:vX.Y.Z`), never `:latest`.
- ✅ Use Postgres for persistence (`PERSIST_DATABASE_URL=postgresql+asyncpg://...`).
- ✅ Set `ENVIRONMENT=production` so `WEB_API_KEYS` is enforced.
- ✅ Mount the app under a **read-only DB role**.
- ✅ Enable `COST_EXPLAIN_ENABLED=true` against large warehouses.
- ✅ Wire `OBS_OTEL_ENABLED=true` + `OBS_OTEL_ENDPOINT` to your collector.
- ✅ Put a real gateway (Cloudflare, nginx, Envoy) in front for multi-pod rate limiting and TLS termination.

---

## 📂 Project Structure

```text
src/omniquery/
├── adapters/
│   ├── cli/                  # Typer + Rich CLI
│   └── web/                  # FastAPI + SSE + rate limiter + API-key auth
├── application/
│   ├── agents/               # LangGraph state machine (EdaSessionGraph)
│   └── use_cases/            # RunEdaUseCase
├── domain/
│   ├── entities/             # Table, Column, DatabaseSchema, ScoredTable, …
│   └── ports/
│       ├── inbound/          # EdaUseCase
│       └── outbound/         # DatabasePort, LlmPort, EmbeddingPort, ProfilingPort
├── infrastructure/
│   ├── db/                   # Postgres / MySQL / Oracle / SQLite / DuckDB
│   │                         # + engine_pool + sql_guard + statement_timeout
│   │                         # + sql_profiling_adapter
│   ├── llm/                  # Ollama / OpenAI / Anthropic + shared prompts
│   ├── graph/                # schema_graph_service + schema_linker
│   ├── cache/                # disk_cache + cached_database + cached_embedding
│   ├── governance/           # cost_guard + pii_policy
│   ├── observability/        # OpenTelemetry tracer
│   ├── persistence/          # SQLAlchemy ORM + Alembic migrations
│   └── logging/              # Structured JSON logging
└── config.py                 # Typed Pydantic Settings
deploy/k8s/                   # Production manifests
docs/DEPLOYMENT.md            # Deployment guide
tests/{unit,integration,e2e,eval}
```

---

## 🛠️ Tech Stack

- **Language**: Python 3.12 · [`uv`](https://github.com/astral-sh/uv) for dep management.
- **Agents**: LangGraph · LangChain Core.
- **LLMs**: Ollama · OpenAI · Anthropic · `tenacity` for retry/backoff.
- **DB drivers**: SQLAlchemy 2 async · asyncpg · aiomysql · oracledb · aiosqlite · duckdb_engine.
- **SQL hardening**: `sqlglot` AST parser.
- **HTTP**: FastAPI · uvicorn · `httpx` async.
- **CLI**: Typer · Rich.
- **Graph / ranking**: NetworkX · Matplotlib.
- **Config & validation**: Pydantic 2 · pydantic-settings.
- **Persistence & migrations**: SQLAlchemy ORM · Alembic.
- **Observability**: OpenTelemetry SDK + OTLP/HTTP exporter.
- **CI/CD**: GitHub Actions · ruff · mypy · pytest · bandit · pip-audit · Docker Buildx (multi-arch, SBOM, provenance).

---

## 🗺️ Roadmap

The full prioritised plan with status and commit references is in **[`IMPROVEMENTS.md`](IMPROVEMENTS.md)**. Highlights of what's next:

- 🧠 Semantic question cache (pgvector) for near-instant replies on similar prompts.
- 🖼️ Visualisation agent producing Vega-Lite specs.
- 🪜 Multi-hop join reasoning via Steiner trees over the FK graph.
- 🗣️ Conversational memory between turns (LangGraph `MemorySaver`).
- 🏢 Workspaces + RBAC for multi-tenant deployments.
- 📊 BigQuery / Snowflake / MSSQL adapters.
- 🌐 Web UI (Next.js).

---

## 🤝 Contributing

Contributions are welcome. The repo enforces a small but firm bar:

- **Tests first.** Every new public function ships with at least one unit test.
- **Type-safe by default.** Curated modules pass `mypy`; new modules should join the list.
- **Pass CI locally before pushing:**
  ```bash
  uv run ruff check src tests
  uv run mypy
  uv run pytest tests/unit tests/integration tests/eval/test_harness_meta.py -q
  uv run bandit -r src -c pyproject.toml -ll
  ```
- **Commit style**: conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `ci:`).
- Open a PR against `develop`. `main` only receives merges from `develop` at release time.

---

## 📄 License

MIT — see [`LICENSE`](LICENSE).

---

<div align="center">

Built with ❤️ for analysts who want answers, not boilerplate.

[Quickstart](#-quickstart) · [Architecture](#-architecture) · [Deployment](docs/DEPLOYMENT.md) · [Roadmap](IMPROVEMENTS.md)

</div>
