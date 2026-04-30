# OmniQuery Explorer — Propuestas de Implementación Detallada

> Documento generado el 2026-04-30.
> Basado en: código fuente actual, `docs/plan_langgraph.md`, `docs/system_prompt.md`,
> **EMNLP 2020** — *Mention Extraction and Linking for SQL Query Generation* (Ma et al.),
> **arXiv 2410.01066** — *From Natural Language to SQL: Review of LLM-based Text-to-SQL Systems* (Mohammadjafari et al.),
> **Prompt Maestro Multi-DB EDA Agents** (documento interno).

---

## Estado actual

| Fase | Descripción | Estado |
|------|-------------|--------|
| F1–F4 | Entidades de dominio, adaptadores DB/LLM, `RunEdaUseCase`, CLI básico | ✅ Completo |
| F5–F9 | `TableProfile`, `ScoredTable`, `ProposedQuestion`, `SchemaGraphService`, `EdaSessionGraph`, CLI extendido | ✅ Completo |
| F10 | Web adapter FastAPI | ❌ Pendiente |
| F11 | Suite de tests | ❌ Pendiente |
| — | Graph RAG, schema linking semántico, RAG de metadatos, SQL validation AST | ❌ No planificado |

---

## Tracking de ramas de implementación

Cada propuesta se implementa en una rama independiente partiendo de `develop`.
El merge a `development` lo realiza el desarrollador manualmente.

| # | Propuesta | Rama | Estado | Commit |
|---|-----------|------|--------|--------|
| P4 | SQL AST Validator (`sqlglot`) | `feature/p4-sql-ast-validator` | ✅ Implementado | `c845af2` |
| P7 | Prompts multi-dialecto | `feature/p7-dialect-prompts` | ✅ Implementado | `607d881` |
| P6 | Suite de tests | `feature/p6-test-suite` | ✅ Implementado | `3d0661c` |
| P2 | Graph RAG (subgrafos FK) | `feature/p2-graph-rag` | ✅ Implementado | 642a907 |
| P8 | Nodo `visualize_er` | `feature/p8-visualize-er` | ✅ Implementado | bd54301 |
| P5 | FastAPI Web Adapter | `feature/p5-fastapi-web` | ✅ Implementado | 55eee3f |
| P1 | Schema Linking semántico | `feature/p1-schema-linking` | ✅ Implementado | 7f28b4d |
| P3 | RAG metadatos FAISS | `feature/p3-rag-faiss` | ⏳ Pendiente | — |

---

## Propuesta 1 — Schema Linking semántico con Extraction-Linking

### Motivación académica

El paper **EMNLP 2020** (*Ma et al.*) propone sustituir el enfoque slot-filling modular (un modelo por tipo de slot) por un pipeline unificado de **extracción de menciones + linking al schema**. En el enfoque actual de `OllamaAdapter.generate_sql()`, la selección de tablas es puramente LLM-free-text: se le da la lista de nombres y que elija. Esto produce selecciones incorrectas cuando los nombres de tabla no coinciden léxicamente con la pregunta del usuario.

### Descripción técnica

Añadir una **Fase A½** entre la selección de tablas y la generación de SQL:

1. **Extractor de menciones** (`MentionExtractor`): identifica entidades nombradas en la pregunta (sustantivos, conceptos de dominio) usando el LLM con un prompt estructurado.
2. **Linker semántico** (`SchemaLinker`): compara cada mención con los nombres y comentarios de tablas/columnas usando similitud de embedding (cosine similarity). Prioriza tablas cuyo nombre o comentario tenga alta similitud con las menciones extraídas.
3. **Verificación hard**: el resultado siempre se valida contra `schema.get_table()` antes de inyectar el DDL.

### Ficheros afectados

- `src/omniquery/infrastructure/llm/ollama_adapter.py` → método `generate_sql()`: insertar fase A½
- `src/omniquery/domain/ports/outbound/llm_port.py` → añadir método abstracto `extract_mentions(question: str) -> list[str]`
- **Nuevo**: `src/omniquery/infrastructure/llm/schema_linker.py` → clase `SchemaLinker`
- **Nuevo**: `src/omniquery/domain/ports/outbound/embedding_port.py` → puerto `EmbeddingPort`

### Interfaz propuesta

```python
# domain/ports/outbound/embedding_port.py
class EmbeddingPort(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

# infrastructure/llm/schema_linker.py
class SchemaLinker:
    def __init__(self, embedder: EmbeddingPort) -> None: ...

    async def link(
        self,
        mentions: list[str],
        schema: DatabaseSchema,
        top_k: int = 6,
    ) -> list[str]:
        """
        Returns table names ranked by semantic similarity to the mentions.
        Uses cosine similarity between mention embeddings and
        (table_name + ' ' + table.comment) embeddings.
        """
        ...
```

### Cambio en `OllamaAdapter.generate_sql()`

```python
# Fase A: extracción de menciones (nuevo)
mentions = await self.extract_mentions(query.question)

# Fase A½: linking semántico (nuevo)
linked_tables = await self._schema_linker.link(mentions, schema, top_k=6)

# Fase B: verificación + SQL generation (existente, alimentado por linked_tables)
valid_tables = [t for t in linked_tables if schema.get_table(t) is not None]
...
```

### Estimación de complejidad

**Alta**. Requiere implementar `EmbeddingPort` + adaptador Ollama Embeddings (`/api/embeddings`) + `SchemaLinker`. El beneficio es mayor precisión de tabla-selección, especialmente en schemas con >50 tablas.

---

## Propuesta 2 — Graph RAG para contextualización de schema

### Motivación académica

El survey **arXiv 2410.01066** identifica **Graph RAG** como la técnica de mayor impacto en SOTA para text-to-SQL, superando a RAG vectorial estándar en benchmarks Spider y WikiSQL. La idea: en lugar de recuperar tablas por similitud de embedding en el espacio vectorial, se usa el **grafo de FK** para recuperar el *vecindario* relevante de las tablas candidatas. Esto captura relaciones join implícitas que el embedding no detecta.

### Descripción técnica

Extender `SchemaGraphService` con un método `get_relevant_subgraph()`:

1. Dado un conjunto de tablas semilla (las seleccionadas por el linker o el LLM), expandir el grafo K hopas (K=1 o 2) en ambas direcciones (padres e hijos en el grafo FK).
2. El subgrafo resultante incluye las tablas semilla + sus vecinos directos + las aristas FK entre ellos.
3. El DDL inyectado en el prompt incluye **solo las tablas del subgrafo**, no el DDL completo. Esto reduce el contexto a lo relevante y evita que el LLM use tablas incorrectas.

### Ficheros afectados

- `src/omniquery/infrastructure/graph/schema_graph_service.py` → nuevo método `get_relevant_subgraph()`
- `src/omniquery/infrastructure/llm/ollama_adapter.py` → `generate_sql()` y `fix_sql()` usan el subgrafo
- `src/omniquery/application/agents/eda_session_graph.py` → pasar `schema_graph` al adaptador LLM en los nodos `generate_sql` y `fix_sql`

### Interfaz propuesta

```python
# infrastructure/graph/schema_graph_service.py (nuevo método)
def get_relevant_subgraph(
    self,
    graph: nx.DiGraph,
    seed_tables: list[str],
    hops: int = 1,
) -> nx.DiGraph:
    """
    BFS expansion from seed_tables up to `hops` steps in both directions.
    Returns a subgraph with seed nodes + their FK neighbors.
    """
    relevant_nodes: set[str] = set(seed_tables)
    for _ in range(hops):
        neighbors: set[str] = set()
        for node in list(relevant_nodes):
            neighbors.update(graph.predecessors(node))  # child tables
            neighbors.update(graph.successors(node))    # parent tables
        relevant_nodes.update(neighbors)
    return graph.subgraph(relevant_nodes).copy()

def subgraph_to_join_hints(self, subgraph: nx.DiGraph, schema: DatabaseSchema) -> str:
    """
    Serialize FK edges of the subgraph as JOIN hints for the LLM prompt.
    Example: "orders.customer_id → customers.id"
    """
    hints = []
    for src, dst, data in subgraph.edges(data=True):
        hints.append(f"{src}.{data.get('fk_col', '?')} → {dst}")
    return "\n".join(hints)
```

### Cambio en el prompt de `generate_sql()`

```
VERIFIED SCHEMA — use ONLY these tables:
{subgraph_ddl}

FK JOIN HINTS (use these relationships):
{join_hints}

Question: {query.question}
```

### Estimación de complejidad

**Media**. `SchemaGraphService` ya existe y tiene el grafo construido. Solo se necesita el método BFS + adaptar los prompts. El `schema_graph` ya está en el estado `EdaSessionState` y se pasa en los nodos `_node_generate_sql` y `_node_fix_sql`.

---

## Propuesta 3 — RAG sobre metadatos del schema (embeddings + vector store)

### Motivación académica

**arXiv 2410.01066** dedica una sección completa a RAG para text-to-SQL. El hallazgo clave: inyectar el schema completo en el contexto no escala (>100 tablas supera la ventana de contexto y degrada la calidad). La solución es un **índice de embeddings sobre los metadatos del schema** (nombre de tabla, nombres de columna, comentarios) para recuperar solo los fragmentos DDL más relevantes.

### Descripción técnica

1. **Indexado**: al conectar a una base de datos, generar embeddings de cada tabla (texto = `table_name + ' ' + column_names_joined + ' ' + table_comment`) y almacenarlos en un vector store ligero (e.g., `faiss` o `chromadb`).
2. **Retrieval**: en `generate_sql()`, antes de construir el prompt, recuperar las K tablas con mayor similitud coseno al embedding de la pregunta del usuario.
3. **Caché**: el índice se cachea en disco por `(connection_url hash, schema_hash)` para no reindexar en cada query.

### Ficheros afectados / nuevos

- **Nuevo**: `src/omniquery/domain/ports/outbound/vector_store_port.py` → `VectorStorePort` ABC
- **Nuevo**: `src/omniquery/infrastructure/rag/faiss_schema_store.py` → implementación con `faiss-cpu`
- **Nuevo**: `src/omniquery/infrastructure/rag/schema_indexer.py` → `SchemaIndexer` (genera embeddings + upsert)
- `src/omniquery/infrastructure/container.py` → wirear `SchemaIndexer` + `FaissSchemaStore`
- `src/omniquery/infrastructure/llm/ollama_adapter.py` → inyectar store, usarlo en `generate_sql()`

### Interfaces propuestas

```python
# domain/ports/outbound/vector_store_port.py
class VectorStorePort(ABC):
    @abstractmethod
    async def upsert(self, doc_id: str, text: str, embedding: list[float]) -> None: ...

    @abstractmethod
    async def search(self, query_embedding: list[float], top_k: int) -> list[str]:
        """Returns doc_ids of the top_k most similar documents."""
        ...

# infrastructure/rag/schema_indexer.py
class SchemaIndexer:
    def __init__(self, embedder: EmbeddingPort, store: VectorStorePort) -> None: ...

    async def index_schema(self, schema: DatabaseSchema) -> None:
        """Embed each table's metadata and upsert into the vector store."""
        for table in schema.tables:
            text = f"{table.name} {' '.join(c.name for c in table.columns)} {table.comment or ''}"
            embedding = (await self._embedder.embed([text]))[0]
            await self._store.upsert(doc_id=table.name, text=text, embedding=embedding)

    async def retrieve_relevant_tables(
        self, question: str, top_k: int = 6
    ) -> list[str]:
        """Return table names most similar to the question."""
        q_emb = (await self._embedder.embed([question]))[0]
        return await self._store.search(q_emb, top_k=top_k)
```

### Estimación de complejidad

**Alta**. Requiere nueva dependencia (`faiss-cpu` o `chromadb`), adaptador de embeddings Ollama, y gestión de caché. Impacto máximo en schemas con >80 tablas.

---

## Propuesta 4 — Validación AST de SQL antes de ejecutar (`sqlglot`)

### Motivación académica

**arXiv 2410.01066** describe *self-correction* como estrategia clave. El sistema actual intenta corregir SQL solo después de recibir un error de la DB (nodo `fix_sql`, máx. 2 intentos). El problema: errores de sintaxis básica (paréntesis mal cerrados, cláusulas inválidas) se podrían detectar **sin llegar a la DB**, acortando el ciclo de corrección.

### Descripción técnica

Añadir un **nodo `validate_sql`** en el grafo LangGraph, entre `generate_sql` y `execute_sql`:

1. Parsear el SQL generado con `sqlglot.parse_one(sql, dialect=engine_dialect)`.
2. Si hay error de parsing: categorizar (`SyntaxError`, `UnsupportedFeature`, etc.) y enrutar a `fix_sql` inmediatamente con el mensaje de error tipificado.
3. Si el parsing OK: extraer las tablas referenciadas (`sqlglot.exp.Table`) y verificar que existan en el schema → otro tipo de error temprano si no.
4. Solo si pasa ambas validaciones → `execute_sql`.

### Ficheros afectados / nuevos

- **Nuevo**: `src/omniquery/infrastructure/sql/sql_validator.py` → `SqlValidator`
- `src/omniquery/application/agents/eda_session_graph.py` → nuevo nodo `_node_validate_sql`, nuevos edges
- `pyproject.toml` → añadir `sqlglot = "^25"` como dependencia

### Interfaz propuesta

```python
# infrastructure/sql/sql_validator.py
from dataclasses import dataclass
import sqlglot

@dataclass
class ValidationResult:
    is_valid: bool
    error_type: str | None   # "syntax" | "unknown_table" | "non_select" | None
    error_message: str | None

class SqlValidator:
    _DIALECT_MAP = {"postgresql": "postgres", "mysql": "mysql", "oracle": "oracle"}

    def validate(self, sql: str, schema: DatabaseSchema) -> ValidationResult:
        dialect = self._DIALECT_MAP.get(schema.engine.value, "")
        try:
            parsed = sqlglot.parse_one(sql, dialect=dialect)
        except sqlglot.errors.ParseError as exc:
            return ValidationResult(False, "syntax", str(exc))

        # Check all referenced tables exist in schema
        for tbl in parsed.find_all(sqlglot.exp.Table):
            if schema.get_table(tbl.name) is None:
                return ValidationResult(
                    False, "unknown_table",
                    f"Table '{tbl.name}' not found in schema."
                )
        return ValidationResult(True, None, None)
```

### Cambio en `EdaSessionGraph._build()`

```python
sg.add_node("validate_sql", self._node_validate_sql)
# edges: generate_sql → validate_sql → execute_sql (o fix_sql si falla)
sg.add_edge("generate_sql", "validate_sql")
sg.add_conditional_edges(
    "validate_sql",
    self._route_after_validate,
    {"execute_sql": "execute_sql", "fix_sql": "fix_sql"},
)
```

### Estimación de complejidad

**Baja-Media**. `sqlglot` es una dependencia ligera y madura. El nodo es simple y no requiere llamada al LLM ni a la DB. Reduce el consumo de tokens al detectar errores localmente antes de reintentar.

---

## Propuesta 5 — FastAPI Web Adapter (Fase 10 del plan original)

### Descripción técnica

Implementar el adapter web pendiente descrito en `plan_langgraph.md`. Arquitectura: FastAPI + Uvicorn, streaming via **Server-Sent Events (SSE)**, mismo `Container` DI que la CLI.

### Endpoints planificados

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/eda/ask` | Pipeline completo para una pregunta. Body: `{url, question, max_rows}`. Response: `AnalysisResult` JSON. |
| `GET` | `/eda/explore` | Exploración automática (sin pregunta). Query param: `url`. Response: `{questions, scored_tables, summary}`. |
| `GET` | `/schema/tables` | Introspección de schema. Query param: `url`. Response: lista de tablas con columnas. |
| `GET` | `/schema/profile` | Profiling de top-N tablas. Query params: `url`, `top_n`. |
| `GET` | `/schema/er-diagram` | Devuelve PNG del diagrama ER. |
| `GET` | `/eda/questions` | Propone preguntas EDA. Query param: `url`. |
| `GET` | `/health` | Health check. |

### SSE Streaming

Para el endpoint `/eda/ask`, emitir eventos SSE con el progreso de cada nodo del grafo LangGraph:

```python
# Eventos SSE emitidos durante el pipeline:
# data: {"event": "introspect", "status": "done", "tables": 42}
# data: {"event": "profile", "status": "done", "tables_profiled": 30}
# data: {"event": "generate_sql", "status": "done", "sql": "SELECT ..."}
# data: {"event": "execute_sql", "status": "done", "rows": 500}
# data: {"event": "report", "status": "done", "report": "### 🧠 ..."}
```

### Ficheros nuevos

```
src/omniquery/adapters/web/
    __init__.py
    main.py          # FastAPI app, lifespan, CORS
    routers/
        eda.py       # /eda/*
        schema.py    # /schema/*
    schemas/         # Pydantic request/response models
        eda_request.py
        eda_response.py
        schema_response.py
    streaming.py     # SSE event generator helpers
```

### Estimación de complejidad

**Media**. FastAPI y Uvicorn ya están en `pyproject.toml`. La lógica de negocio ya existe en `EdaSessionGraph` y `Container`. El esfuerzo principal es el routing, los schemas Pydantic y el generador SSE.

---

## Propuesta 6 — Suite de Tests (unit + integration)

### Estado actual

Los directorios `tests/unit/` y `tests/integration/` existen pero están **completamente vacíos**.

### Estrategia

#### Tests unitarios (sin I/O real)

Usar `pytest-mock` para mockear `DatabasePort` y `LlmPort`.

| Test | Fichero | Qué verifica |
|------|---------|-------------|
| `test_eda_session_graph_happy_path` | `tests/unit/test_eda_session_graph.py` | El grafo completa todos los nodos y devuelve `AnalysisResult` con `report != ""` |
| `test_fix_sql_retries` | `tests/unit/test_eda_session_graph.py` | Tras 2 errores DB consecutivos, el grafo enruta a `end_error` |
| `test_schema_graph_service_pagerank` | `tests/unit/test_schema_graph_service.py` | PageRank devuelve scores en [0,1] para un schema FK sintético |
| `test_score_tables_ordering` | `tests/unit/test_schema_graph_service.py` | La tabla con más FK referencias puntúa más alto |
| `test_ollama_adapter_rejects_non_select` | `tests/unit/test_ollama_adapter.py` | `_assert_select_only` lanza `ValueError` en INSERT/DELETE |
| `test_parse_proposed_questions` | `tests/unit/test_eda_session_graph.py` | `_parse_proposed_questions()` extrae difficulty, category y tables correctamente |
| `test_sql_validator_syntax_error` | `tests/unit/test_sql_validator.py` | `SqlValidator` detecta SQL malformado sin llamar a la DB |
| `test_sql_validator_unknown_table` | `tests/unit/test_sql_validator.py` | `SqlValidator` detecta tablas no presentes en el schema |

#### Tests de integración (con DB real o contenedor Docker)

| Test | DB | Qué verifica |
|------|----|-------------|
| `test_postgresql_adapter_introspect` | PostgreSQL (Docker) | `get_schema()` devuelve tablas con columnas y FK correctas |
| `test_mysql_adapter_introspect` | MySQL (Docker) | Igual para MySQL |
| `test_sql_profiling_adapter` | PostgreSQL (Docker) | `profile_table()` devuelve `row_count > 0` y `sample_rows` |
| `test_full_pipeline_postgres` | PostgreSQL (Docker) | Pipeline end-to-end desde `EdaSessionGraph.run()` con LLM mock |

### Fixtures propuestas

```python
# tests/conftest.py
@pytest.fixture
def mock_db() -> MagicMock:
    """DatabasePort mock con schema sintético de 5 tablas con FKs."""
    ...

@pytest.fixture
def mock_llm() -> MagicMock:
    """LlmPort mock que devuelve SQL válido y un report stub."""
    ...

@pytest.fixture
def sample_schema() -> DatabaseSchema:
    """Schema PostgreSQL sintético: orders, customers, products, order_items, categories."""
    ...
```

### Estimación de complejidad

**Media**. Los tests unitarios son los más urgentes y de menor coste. Los de integración requieren `docker-compose` en CI.

---

## Propuesta 7 — Prompt Engineering Multi-DB diferenciado por dialecto

### Motivación

El **Prompt Maestro Multi-DB EDA Agents** documenta la necesidad de prompts especializados por motor de base de datos. Actualmente `system_prompt.md` es un único prompt genérico. El LLM genera ocasionalmente sintaxis PostgreSQL cuando está conectado a Oracle (e.g., usa `LIMIT` en lugar de `FETCH FIRST N ROWS ONLY`, o `::` cast en lugar de `CAST()`).

### Descripción técnica

1. **System prompts por dialecto**: crear `docs/system_prompt_postgresql.md`, `docs/system_prompt_mysql.md`, `docs/system_prompt_oracle.md`, cada uno con:
   - Sintaxis LIMIT/paginación correcta para el dialecto.
   - Funciones de fecha/hora nativas (`DATE_TRUNC` vs `DATE_FORMAT` vs `TRUNC`).
   - Cast syntax nativo.
   - Ejemplos few-shot de 3 queries representativas.

2. **Selección dinámica**: `OllamaAdapter` recibe el `engine` en la llamada y carga el prompt correspondiente.

3. **Few-shot dinámico**: el prompt incluye 2-3 ejemplos de SQL generados a partir de tablas reales del schema conectado (generados en el nodo `propose_questions` y cacheados en el estado).

### Ficheros afectados

- `docs/` → 3 nuevos ficheros de system prompt por dialecto
- `src/omniquery/infrastructure/llm/ollama_adapter.py` → lógica de selección de prompt en `__init__` o en `generate_sql()` según el engine del schema
- `src/omniquery/domain/ports/outbound/llm_port.py` → pasar `engine` o `DatabaseSchema` completo a `generate_sql()` (ya lo recibe, solo hay que usarlo para selección de prompt)

### Estructura de prompt por dialecto (ejemplo Oracle)

```markdown
# Role and Persona
[identico al genérico]

# Dialect: Oracle SQL
- Use `FETCH FIRST N ROWS ONLY` (not LIMIT) for row limiting.
- Use `TRUNC(date_col, 'MM')` for date truncation.
- Use `CAST(col AS VARCHAR2(255))` for string casting.
- Use `NVL(col, default)` for null coalescing (not COALESCE when possible).
- System tables: ALL_TABLES, ALL_COLUMNS, ALL_CONSTRAINTS.
- Date literals: DATE '2024-01-01' or TO_DATE('2024-01-01', 'YYYY-MM-DD').

# Few-shot Examples
Question: How many rows are in the flights table?
SQL:
SELECT COUNT(*) AS total_flights FROM flights FETCH FIRST 1 ROWS ONLY;

Question: What is the distribution of airline codes?
SQL:
SELECT airline_code, COUNT(*) AS cnt
FROM flights
GROUP BY airline_code
ORDER BY cnt DESC
FETCH FIRST 20 ROWS ONLY;
```

### Estimación de complejidad

**Baja**. Principalmente trabajo de redacción de prompts. El cambio en `OllamaAdapter` es mínimo (tabla de dispatch por `engine.value`).

---

## Propuesta 8 — Nodo `visualize_er` en el grafo LangGraph

### Descripción técnica

El `plan_langgraph.md` incluye un nodo `visualize_er` que no se implementó. Completarlo:

1. Usar `matplotlib` (ya dependencia) + `networkx` para dibujar el grafo FK.
2. Color-coding: tablas con score alto = verde, tablas intermedias = amarillo, periféricas = gris.
3. Nodos con tamaño proporcional a `log(row_count)`.
4. Aristas etiquetadas con el nombre de la FK column.
5. Guardar como PNG temporal y abrir con `open` (macOS) / `xdg-open` (Linux) — patrón ya usado en `cli/charts.py`.

### Ficheros afectados

- `src/omniquery/adapters/cli/charts.py` → nueva función `plot_er_diagram(schema, scored_tables, schema_graph)`
- `src/omniquery/application/agents/eda_session_graph.py` → nuevo nodo `_node_visualize_er`, añadido al grafo completo después de `generate_report`
- `src/omniquery/adapters/cli/main.py` → exponer como comando `omniquery graph`

### Estimación de complejidad

**Baja-Media**. `matplotlib` y `networkx` ya están. El patrón de guardar + abrir PNG existe en `charts.py`. La complejidad está en el layout del grafo (usar `nx.spring_layout` o `nx.kamada_kawai_layout` para schemas grandes).

---

## Resumen de priorización

| # | Propuesta | Impacto | Esfuerzo | Prioridad |
|---|-----------|---------|----------|-----------|
| 4 | Validación AST con `sqlglot` | Alto (menos retries, menos tokens) | Bajo | 🔴 P0 |
| 7 | Prompts multi-dialecto | Alto (calidad SQL por motor) | Bajo | 🔴 P0 |
| 6 | Suite de tests | Crítico (deuda técnica) | Medio | 🔴 P0 |
| 2 | Graph RAG (subgrafos FK) | Alto (precisión joins) | Medio | 🟠 P1 |
| 8 | Nodo `visualize_er` | Medio (UX) | Bajo-Medio | 🟠 P1 |
| 5 | FastAPI Web Adapter | Alto (nuevo canal) | Medio | 🟠 P1 |
| 1 | Schema linking semántico | Muy alto (precisión tablas) | Alto | 🟡 P2 |
| 3 | RAG de metadatos (FAISS) | Muy alto (escalabilidad) | Alto | 🟡 P2 |

---

## Dependencias nuevas a añadir en `pyproject.toml`

```toml
# P0
sqlglot = "^25"                    # Propuesta 4: validación AST SQL

# P1
# (ninguna nueva — matplotlib y networkx ya están)

# P2
faiss-cpu = "^1.8"                 # Propuesta 3: vector store
# O alternativa: chromadb = "^0.5"

# Para embeddings (P1/P2):
# Ollama ya soporta /api/embeddings — sin dependencia extra
```

---

## Referencias bibliográficas

1. **Ma, J., Yan, Z., Pang, S., Zhang, Y., & Shen, J.** (2020). *Mention Extraction and Linking for SQL Query Generation*. Proceedings of EMNLP 2020, pp. 6936–6942. ACL Anthology ID: 2020.emnlp-main.563.

2. **Mohammadjafari, A., Maida, A. S., & Gottumukkala, R.** (2024). *From Natural Language to SQL: Review of LLM-based Text-to-SQL Systems*. arXiv:2410.01066 [cs.CL].

3. **Brin, S. & Page, L.** (1998). *The Anatomy of a Large-Scale Hypertextual Web Search Engine*. WWW 1998. *(Citado en `schema_graph_service.py` como base del PageRank implementado.)*
