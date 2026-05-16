# OmniQuery Explorer — Plan de Mejora a Herramienta de Uso Real

Documento que describe las brechas detectadas entre el estado actual del proyecto y un producto utilizable en entornos reales (equipos de datos, analistas, ingeniería), junto con un plan de mejora priorizado por impacto y esfuerzo.

> Estado actual (resumen): CLI funcional, arquitectura hexagonal limpia, pipeline LangGraph con 8 agentes, soporte multi-engine (PostgreSQL/MySQL/Oracle), profiling estadístico y SQL self-healing. Cobertura de tests muy limitada (sólo `schema_linker`), sin Web API, sin auth, sin multi-LLM, sin persistencia, sin observabilidad distribuida, sin CI/CD ni imagen Docker propia.

---

## 1. Tabla resumen — Priorización

| # | Iniciativa | Impacto | Esfuerzo | Prioridad |
|---|---|---|---|---|
| 1 | Hardening SQL (sqlglot AST + role read-only + timeouts) | Alto | M | P0 |
| 2 | Multi-LLM provider (OpenAI / Anthropic / Bedrock / Ollama) | Alto | M | P0 |
| 3 | FastAPI Web Adapter + SSE streaming | Alto | M | P0 |
| 4 | Persistencia (sesiones, historial, query log) | Alto | M | P0 |
| 5 | Cache de schema, profile y embeddings | Alto | S | P0 |
| 6 | Configuración tipada (Pydantic Settings) + gestión de secretos | Alto | S | P0 |
| 7 | Cobertura de tests >70% + harness de evaluación text-to-SQL | Alto | L | P1 |
| 8 | Observabilidad: OpenTelemetry + Langfuse | Medio | M | P1 |
| 9 | Auth/RBAC + multi-tenant + workspace por usuario | Alto | L | P1 |
| 10 | Cost-guard para LLM y DB (EXPLAIN gate + budget) | Alto | M | P1 |
| 11 | PII masking + column allowlist / denylist por rol | Alto | M | P1 |
| 12 | Dialect-aware SQL emission (LIMIT vs FETCH FIRST, quoting) | Medio | S | P1 |
| 13 | Connection pool reutilizable + cancelación de queries | Medio | S | P1 |
| 14 | UI Web (Next.js o Streamlit) | Alto | L | P2 |
| 15 | Cache semántico de preguntas similares | Medio | M | P2 |
| 16 | Agente de visualización inteligente (Vega-Lite) | Medio | M | P2 |
| 17 | Librería de consultas guardadas + colaboración | Medio | M | P2 |
| 18 | CI/CD (GitHub Actions) + Docker image multi-stage | Alto | S | P2 |
| 19 | Soporte BigQuery, Snowflake, DuckDB, SQLite | Alto | M | P2 |
| 20 | Soporte de joins multi-hop con razonamiento de path | Medio | L | P3 |

Leyenda esfuerzo: S = 1-3 días · M = 1-2 semanas · L = ≥1 sprint.

---

## 2. Bloque P0 — Lo mínimo para "uso real"

### 2.1 Hardening de SQL

Hoy `BaseSQLAdapter._assert_read_only` y `OllamaAdapter._assert_select_only` validan por regex. Esto se puede burlar con CTEs `WITH x AS (DELETE …) SELECT …`, comentarios anidados, statements múltiples, `pg_sleep`, funciones que escriben, etc.

Acciones:
- Reemplazar el regex por parseo AST con **sqlglot**. Verificar: una sola sentencia, sólo nodo raíz `Select`/`Union`, sin CTEs con DML, sin llamadas a funciones en lista negra (`pg_sleep`, `dblink`, `lo_import`, `xp_cmdshell`, etc.).
- Aplicar `LIMIT` reescribiendo el AST (no concatenando string). Soporta `FETCH FIRST N ROWS ONLY` para Oracle.
- Imponer `statement_timeout` (Postgres) / `MAX_EXECUTION_TIME` (MySQL) / `OCI_ATTR_CALL_TIMEOUT` (Oracle) a nivel de sesión antes de ejecutar.
- Documentar y forzar uso de un rol DB **read-only** dedicado (privilegio SELECT estrictamente). El nivel de aplicación es defensa-en-profundidad, no la única barrera.
- Validar tabla y columnas referenciadas contra `schema.table_names` y `schema.get_table().column_names` ANTES de ejecutar; rechazar si el modelo invent ó.

Archivos: `src/omniquery/infrastructure/db/base_sql_adapter.py`, nuevo módulo `infrastructure/db/sql_guard.py`.

### 2.2 Multi-LLM Provider

`OllamaAdapter` está hardcoded en `Container`. El puerto `LlmPort` ya existe — falta:
- `OpenAIAdapter`, `AnthropicAdapter`, `BedrockAdapter`, `VertexAdapter` (LangChain unifica esto pero conviene un adapter delgado por consistencia con la capa hexagonal).
- Factory `resolve_llm_adapter(settings)` paralela a `resolve_db_adapter`.
- Retry exponencial con `tenacity` para 5xx y rate-limits.
- Reuso de `httpx.AsyncClient` a nivel adapter (hoy se crea por llamada).
- Eliminar el acceso a método "privado" `self._llm._chat(prompt)` desde `eda_session_graph.py` (líneas 353, 385) — exponer un método público `chat(prompt)` en `LlmPort` o crear `LlmPort.propose_questions(...)`/`summarize_db(...)` para no romper la abstracción.

### 2.3 FastAPI Web Adapter

Dep ya instalada (`fastapi`, `uvicorn`). Añadir:
- `src/omniquery/adapters/web/` con rutas:
  - `POST /sessions` → crea `connection_url` por sesión (cifrado en server-side).
  - `POST /sessions/{id}/ask` → SSE streaming de eventos LangGraph (un evento por nodo del grafo, payload con `agent`, `status`, `delta`).
  - `GET /sessions/{id}/schema`, `/profile`, `/suggest`.
- Reutilizar `Container.eda_session_graph()` (ya pensado como singleton compartible).
- Servir CORS limitado y rate-limit por IP/API key.
- Manejo de cancelación con `asyncio.CancelledError` para liberar conexiones DB cuando el cliente cierra el SSE.

### 2.4 Persistencia

Hoy no hay nada persistido. Para uso real necesitamos:
- Tabla `sessions(id, user_id, connection_url_ref, created_at, …)`.
- Tabla `queries(id, session_id, question, generated_sql, status, error, duration_ms, row_count, llm_tokens, …)`.
- Tabla `reports(query_id, markdown, charts_paths)`.
- `cached_profiles(connection_fingerprint, table_name, profile_json, ttl)`.
- `cached_schemas(connection_fingerprint, schema_json, ttl)`.
- Implementación con SQLAlchemy async sobre un Postgres "interno" (separado del DB analizado). Alembic para migraciones.

### 2.5 Cache

`get_schema` y `profile_all` se ejecutan en cada invocación CLI. En un esquema con cientos de tablas, el profiling es costoso (`COUNT(*)`, `COUNT(DISTINCT)` por columna). Acciones:
- `SchemaCache` con clave `sha256(connection_url + db_name)` y TTL.
- `ProfileCache` con la misma clave + nombre de tabla; invalidación manual o por TTL configurable.
- `EmbeddingCache` para `SchemaLinker` (hoy embebe cada columna en cada `rank_tables`). Persistir embeddings serializados (sqlite + numpy `.npz` o pgvector).

### 2.6 Configuración y secretos

Hoy: `os.getenv` desperdigado en `container.py` y `cli/main.py`. Mejorar:
- `src/omniquery/config.py` con `Settings(BaseSettings)` de Pydantic v2 — fuentes: env, `.env`, `secrets/`.
- Soporte para resolver `DATABASE_URL` desde AWS Secrets Manager / Vault / `pass` mediante un proveedor pluggable (`SecretProvider`).
- Validar al arranque que la URL no incluye credenciales en texto plano si `ENV=production`.

---

## 3. Bloque P1 — Robustez de producto

### 3.1 Tests + Evaluación

Coverage actual: sólo `schema_linker` y `schema_graph_service`. Falta:
- Unit tests para `BaseSQLAdapter._apply_limit`, `_assert_read_only`, `OllamaAdapter._extract_sql`, parser de `_parse_proposed_questions`, scoring en `SchemaGraphService.score_tables`.
- Integration tests con `pytest-postgresql` o `testcontainers` (Postgres + MySQL + Oracle XE).
- Harness de evaluación text-to-SQL: dataset propio (~50 preguntas) o porting de **Spider/Bird** subset; métricas: execution accuracy, exact match, ratio de queries que requirieron `fix_sql`, latencia p50/p95 por modelo.
- Smoke test E2E que ejecute `ask` contra `dbs/` muestreado.

### 3.2 Observabilidad

Hoy hay logging JSON estructurado (bien). Faltan:
- Tracing distribuido con **OpenTelemetry** — un span por nodo del grafo, atributos `session_id`, `agent`, `tokens`, `db_engine`. Export a Jaeger/Tempo.
- Métricas Prometheus: histograma de latencia por agente, contador de fallos de SQL, gauge de cache hit ratio, tokens totales por modelo.
- Integración con **Langfuse** o **Phoenix** para traza específica de LLM (prompts, respuestas, costo estimado).
- Dashboards Grafana embebidos en `docs/grafana/`.

### 3.3 Auth + multi-tenant

- API Key + JWT (Auth0/Cognito/Keycloak/casdoor — adapter pluggable).
- `User`, `Workspace`, `Membership` en la BD interna.
- Por workspace: conjunto de conexiones DB autorizadas, modelo LLM por defecto, budget mensual.
- Cifrado at-rest de connection URLs (Fernet con clave en KMS).

### 3.4 Cost-guard

- Antes de ejecutar SQL, lanzar `EXPLAIN (FORMAT JSON)` y rechazar si `total_cost` > umbral o si la query toca tablas por encima de N filas sin filtros.
- Budget por usuario/workspace: tokens LLM por día, queries por hora. Devolver `429` con `Retry-After`.
- Telemetría de coste estimado por proveedor (precio por 1k tokens hardcoded en config).

### 3.5 PII / governance

- Política de columnas por nombre y/o por tag DB:
  - Denylist (`email`, `ssn`, `password`, `card_number`, ...): excluidas del DDL pasado al LLM y enmascaradas en resultados (`hash`/`***`).
  - Allowlist por workspace.
- Auditoría: cada `execute_query` queda registrado con `user_id`, `question`, `sql`, `rows_returned`.
- Soporte para etiquetas semánticas (column comments tipo `@pii` o tabla `column_metadata`).

### 3.6 Dialect-aware SQL

`_apply_limit` añade `LIMIT N` siempre — falla en Oracle (`FETCH FIRST n ROWS ONLY`) y SQL Server (`TOP n`). Acciones:
- Reescribir vía `sqlglot.transpile(sql, read="postgres", write=engine.value)`.
- Generar prompts conscientes del dialecto (`schema.engine.value` ya disponible).
- Tests por dialecto.

### 3.7 Pool reutilizable

`BaseSQLAdapter` crea y descarta `AsyncEngine` por llamada (`get_schema`, `execute_query`, `_row_count`, `_column_info` en `sql_profiling_adapter` …). Reutilizar un pool por `connection_url` en el adapter, con cierre coordinado al apagar el container. Permite además cancelar queries en curso vía `connection.invalidate()`.

---

## 4. Bloque P2 — Diferenciación

### 4.1 UI Web

- **Opción A (rápida)**: Streamlit/Gradio para prototipo interno.
- **Opción B (producto)**: Next.js + shadcn/ui — chat, vista de schema (D3 force graph), tabla resultados, editor SQL con diff cuando el `fix_sql` modifica la query, descarga CSV/Parquet.
- Replicar UX de Hex/Mode/Metabase Ask AI: panel izquierdo schema explorer, derecha conversación.

### 4.2 Cache semántico

Embeber cada pregunta y guardar `(question_embed, sql, success)`. En la siguiente pregunta, hacer cosine search >= 0.92 → reutilizar SQL con confirmación. Implementar con pgvector o `chromadb`.

### 4.3 Agente de visualización

Hoy `chart_query_results` decide chart por heurística. Sustituir por un agente que, dado el shape del DataFrame, produzca un spec **Vega-Lite** JSON y lo renderice (browser) o use Altair (CLI). Habilita scatter, heatmap, small multiples.

### 4.4 Librería de consultas guardadas

- "Pinear" preguntas con su SQL aprobado.
- Compartir entre usuarios del workspace.
- Re-ejecutar como reporte programado (cron).

### 4.5 CI/CD + Docker

- `.github/workflows/ci.yml`: lint (ruff), typecheck (mypy/pyright), tests, security scan (bandit, pip-audit).
- `.github/workflows/release.yml`: build wheel + Docker image (multi-arch buildx), publish a GHCR.
- `Dockerfile` multi-stage: builder con `uv`, runtime slim, non-root user.
- `docker-compose.yml` que orqueste app + Postgres interno + Ollama opcional.

### 4.6 Más motores

- **DuckDB / SQLite**: trivial (`sqlalchemy` + `aiosqlite`); muy útil para análisis local sobre Parquet/CSV.
- **BigQuery**: adapter con `sqlalchemy-bigquery` + cuotas.
- **Snowflake**: `snowflake-sqlalchemy` + soporte de roles/warehouse.
- **Redshift**: vía postgresql adapter con tweaks de dialecto.
- **MS SQL Server**: `aioodbc`.

---

## 5. Bloque P3 — Inteligencia avanzada

### 5.1 Joins multi-hop con razonamiento

`SchemaGraphService` ya tiene el grafo FK. Aprovecharlo:
- Para una pregunta, computar el **Steiner tree** mínimo entre tablas relevantes (NetworkX) y proponerlo como hint al LLM.
- Resolver join paths ambiguos preguntando al usuario (`disambiguate` agent).

### 5.2 Value lookups

Para "ventas en España", muestrear `country` distinct y mapear "España" → `ES`. Hoy el modelo adivina. Añadir nodo `value_resolver` que ejecuta `SELECT DISTINCT col WHERE col ILIKE 'esp%' LIMIT 20` y enriquece el prompt.

### 5.3 Auto-eval del reporte

Tras `generate_report`, un agente crítico evalúa coherencia entre `raw_data` y conclusiones; si baja confianza, re-ejecuta con prompt corregido.

### 5.4 Modo conversacional con memoria

Hoy cada `ask` es stateless. Añadir memoria de turno con resumen de queries previas (LangGraph checkpoints — `MemorySaver`/`SqliteSaver`).

---

## 6. Deuda técnica concreta detectada

| Archivo:línea | Issue | Fix |
|---|---|---|
| `eda_session_graph.py:353,385` | Llama `self._llm._chat()` (método "privado") | Añadir método público al `LlmPort` |
| `eda_session_graph.py:305` | `re.match(r"^xref_p\d+", ...)` hardcoded — específico de RNAcentral | Extraer a config / blacklist de prefijos por workspace |
| `eda_session_graph.py:334` | Prompt en español dentro del código | Mover a `prompts/*.md` con plantillas Jinja2; soportar locale |
| `ollama_adapter.py:243` | Nuevo `httpx.AsyncClient` por llamada | Cliente compartido como atributo, cerrado al teardown del container |
| `ollama_adapter.py:29` | `_SYSTEM_PROMPT_PATH = Path(__file__).parents[4]` — frágil ante reubicaciones | Resolver vía `importlib.resources` o variable de config |
| `base_sql_adapter.py:97` | `_apply_limit` no es dialect-aware | sqlglot transpile |
| `base_sql_adapter.py:15` | Regex DML check | sqlglot AST |
| `container.py:73` | `@lru_cache` sin invalidación | Lifespan explícito (init/shutdown) para Web adapter |
| `sql_profiling_adapter.py:44` | Crea engine por tabla — N llamadas crean N engines | Pasar engine inyectado o cachear por `connection_url` |
| `sql_profiling_adapter.py:64-66` | Quoting con `"` no funciona en MySQL (usa backticks) | Usar `sqlalchemy.sql.quoted_name` o reflexión |
| `pyproject.toml` | Falta `ruff`, `mypy`, `bandit`, `pip-audit` en dev deps | Añadir |
| Repo root | Sin `.github/workflows`, sin `Dockerfile`, sin `pre-commit` | Añadir |
| `scripts/aws_import` | Sin documentar, sin tests | Documentar o mover a `examples/` |

---

## 7. Hoja de ruta sugerida (8 semanas)

**Sprint 1 (semana 1-2) — Foundation hardening**
- 2.1 SQL hardening (sqlglot) · 2.6 config tipada · 2.5 cache mínima (schema) · tests + CI básico (ruff + pytest en GH Actions).

**Sprint 2 (semana 3-4) — Multi-LLM y persistencia**
- 2.2 multi-LLM (OpenAI + Anthropic + Ollama) · 2.4 persistencia con Alembic · cache de profile y embeddings.

**Sprint 3 (semana 5-6) — Web API**
- 2.3 FastAPI + SSE · auth con API key simple · cost-guard · dialect-aware SQL · pool reutilizable.

**Sprint 4 (semana 7-8) — Observabilidad y release**
- 3.2 OTel + Langfuse · Dockerfile + release pipeline · harness de eval text-to-SQL · documentación de despliegue (`docs/deploy.md`).

A partir de aquí: UI Web, multi-tenant completo, soporte BigQuery/Snowflake, cache semántico, agente de visualización.

---

## 8. Definición de "listo para uso real"

Checklist mínimo de release v1.0:

- [ ] Tests con cobertura ≥70% en `application/` y `infrastructure/`
- [ ] Pipeline CI verde (lint + typecheck + tests + security scan)
- [ ] Imagen Docker publicada en registry
- [ ] Web API documentada con OpenAPI y desplegable con `docker compose up`
- [ ] Autenticación por API key activa por defecto
- [ ] SQL guard basado en AST + uso forzado de rol DB read-only documentado
- [ ] Persistencia de sesiones y query log activa
- [ ] Soporte de al menos 2 proveedores LLM además de Ollama
- [ ] Trazas OpenTelemetry exportables
- [ ] Documentación de despliegue para una máquina y para Kubernetes
- [ ] Harness de evaluación text-to-SQL con baseline publicado en README
