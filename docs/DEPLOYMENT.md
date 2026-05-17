# Deployment Guide

This document covers two supported deployment topologies:

1. **Single machine** — `docker compose up` against the bundled
   compose file. Fits most teams running ≤10 analysts.
2. **Kubernetes** — manifests under `deploy/k8s/` for production
   clusters; assumes an existing OTLP collector and an external
   Postgres for the persistence DB.

For the development loop see `README.md` instead.

---

## 1. Single machine (Docker Compose)

### Prerequisites

- Docker Engine ≥ 24 and Compose v2.
- 8 GB RAM and 4 cores recommended (Ollama models account for most).
- A target relational database reachable from the host (PostgreSQL,
  MySQL/MariaDB, Oracle, SQLite, or DuckDB).

### Bring-up

```bash
git clone <repo> && cd omniquery-explorer

# Start the API + Ollama
docker compose up -d

# Pull the LLM model into the Ollama container (first time only)
docker compose exec ollama ollama pull llama3.2:latest

# Probe the API
curl http://localhost:8000/health
```

The compose file mounts two named volumes:

- `ollama_models` — model cache so subsequent restarts skip the download.
- `omniquery_data` — SQLite persistence DB (sessions, queries, reports).

### Configuration

Compose passes every relevant variable via the `environment:` block.
The complete reference lives in `Settings` (`src/omniquery/config.py`);
the most common overrides:

| Variable                       | Default                                     | Effect                                              |
|--------------------------------|---------------------------------------------|-----------------------------------------------------|
| `ENVIRONMENT`                  | `development`                               | `production` enforces `WEB_API_KEYS`.               |
| `DATABASE_URL`                 | _unset_                                     | Default target DB when `--url` is omitted.          |
| `LLM_PROVIDER`                 | `ollama`                                    | `ollama` / `openai` / `anthropic`.                  |
| `LLM_MODEL`                    | `llama3.2:latest`                           | Provider-specific model name.                       |
| `LLM_OLLAMA_BASE_URL`          | `http://ollama:11434`                       | Internal compose hostname.                          |
| `LLM_OPENAI_API_KEY`           | _unset_                                     | Required when `LLM_PROVIDER=openai`.                |
| `LLM_ANTHROPIC_API_KEY`        | _unset_                                     | Required when `LLM_PROVIDER=anthropic`.             |
| `WEB_API_KEYS`                 | _unset_                                     | Comma-separated allowlist (required in production). |
| `WEB_RATE_LIMIT_PER_MINUTE`    | `60`                                        | 0 disables the limiter.                             |
| `DB_STATEMENT_TIMEOUT_MS`      | `30000`                                     | Per-query timeout sent to the analysed DB.          |
| `COST_EXPLAIN_ENABLED`         | `false`                                     | Turn on the EXPLAIN cost gate.                      |
| `COST_MAX_PLAN_COST`           | `1000000`                                   | Reject queries above this planner cost.             |
| `COST_MAX_PLAN_ROWS`           | `50000000`                                  | Reject queries scanning more rows.                  |
| `PII_DENYLIST_PATTERNS`        | _(see `config.py`)_                         | Regex for redacted columns.                         |
| `PERSIST_DATABASE_URL`         | `sqlite+aiosqlite:////data/omniquery.db`    | Move to Postgres in prod.                           |
| `OBS_OTEL_ENABLED`             | `false`                                     | Enable OTLP/HTTP tracing.                           |
| `OBS_OTEL_ENDPOINT`            | _unset_                                     | Collector URL (e.g. `http://otel:4318/v1/traces`).  |

### Smoke test

```bash
# JSON
curl -X POST http://localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "How many customers are there?",
    "connection_url": "sqlite+aiosqlite:////data/eval_ecommerce.db",
    "max_rows": 50
  }'

# SSE
curl -N -X POST http://localhost:8000/ask/stream \
  -H 'Content-Type: application/json' \
  -d '{"question": "...", "connection_url": "..."}'
```

### Upgrading

```bash
docker compose pull
docker compose up -d
# Persistence migrations are applied automatically on container start.
```

---

## 2. Kubernetes

The manifests in `deploy/k8s/` are intentionally minimal and provider-
agnostic. They assume:

- An ingress controller (or a `LoadBalancer` Service) that fronts the
  cluster.
- A Postgres instance reachable in-cluster (the `PERSIST_DATABASE_URL`
  Secret points at it).
- An OTLP collector (Tempo, Jaeger, Honeycomb agent) if tracing is on.
- A Secret named `omniquery-llm` holding the LLM provider key.

### Files

```
deploy/k8s/
├── namespace.yaml
├── configmap.yaml         # non-secret env vars
├── secret.example.yaml    # template; never commit real secrets
├── deployment.yaml        # API workload with HPA-friendly limits
├── service.yaml           # ClusterIP for the API
└── ingress.example.yaml   # optional, ingress-nginx
```

### Apply

```bash
kubectl apply -f deploy/k8s/namespace.yaml
# Edit secret.example.yaml → save as secret.yaml (out of git).
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/service.yaml
kubectl apply -f deploy/k8s/ingress.example.yaml   # optional
```

### Production checklist

- [ ] Pin the image to a published tag (`ghcr.io/<org>/omniquery-explorer:v0.1.0`),
      never `:latest`.
- [ ] Use Postgres for persistence (`PERSIST_DATABASE_URL=postgresql+asyncpg://...`).
- [ ] Set `ENVIRONMENT=production` so `WEB_API_KEYS` is enforced.
- [ ] Run at least two replicas; rate-limiter buckets are per-pod, so
      put a real gateway (Cloudflare, nginx) in front for multi-pod
      quotas.
- [ ] Mount a read-only DB role: app-level guard is defence-in-depth.
- [ ] Enable `COST_EXPLAIN_ENABLED=true` against large warehouses.
- [ ] Wire `OBS_OTEL_ENABLED=true` + `OBS_OTEL_ENDPOINT` to the OTLP
      collector; verify `agent.*` and `llm.call` spans appear.

### Resources

Default container limits in `deployment.yaml`:

```yaml
resources:
  requests: { cpu: "200m", memory: "512Mi" }
  limits:   { cpu: "1000m", memory: "1Gi" }
```

Tune the memory limit if the analysed DBs return very large rowsets,
the report prompt grows with row count.

---

## Troubleshooting

| Symptom                                  | Likely cause                                       | Fix                                                              |
|------------------------------------------|----------------------------------------------------|------------------------------------------------------------------|
| `WEB_API_KEYS must be configured`        | `ENVIRONMENT=production` without keys              | Set `WEB_API_KEYS=key1,key2`.                                    |
| 429 with `Retry-After`                   | Per-identity rate limit hit                        | Raise `WEB_RATE_LIMIT_PER_MINUTE` or back off.                   |
| `Query rejected: estimated plan cost …`  | EXPLAIN gate caught a wide scan                    | Add filters, raise `COST_MAX_PLAN_COST`.                         |
| Empty results + report mentions PII cols | Default denylist hid them                          | Tune `PII_DENYLIST_PATTERNS` (regex).                            |
| `alembic upgrade failed`                 | Read-only persistence volume                       | Ensure `omniquery_data` PVC is writable, then `init_schema` retries on next boot. |
