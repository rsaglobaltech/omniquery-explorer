# OmniQuery Explorer

**Agentic Exploratory Data Analysis (EDA) for relational databases using natural language.**

OmniQuery Explorer turns plain-language business questions into safe SQL, executes them on real databases, and returns interpretable analytical reports. It is designed for data analysts, engineers, and product teams who need faster exploration without sacrificing control, traceability, or architecture quality.

## What This Project Is About

Most NL-to-SQL tools stop at query generation. OmniQuery Explorer goes further with an end-to-end EDA pipeline:

- Understands the database structure automatically
- Profiles and ranks the most relevant tables
- Proposes high-value exploratory questions
- Generates and executes read-only SQL
- Recovers from SQL errors with an automated correction loop
- Produces structured analytical output for decision-making

## Core Features

- **Natural language to SQL** with schema-aware prompting
- **Strict read-only policy** (`SELECT` only)
- **Multi-database support**: PostgreSQL, MySQL/MariaDB, Oracle
- **Automatic schema introspection** (tables, columns, PKs, FKs)
- **Table profiling** (row counts, null ratios, cardinality, metric/date signals)
- **Graph-based table ranking** using foreign-key relationships
- **Automated SQL repair loop** on execution failures
- **Rich CLI UX** with progress, tabular output, markdown reports, and charts

## Agents Used in the Pipeline

The multi-agent orchestration is implemented as a LangGraph state graph. Each node acts as a specialized agent responsibility:

1. `introspect`
Extracts database schema metadata.
2. `profile`
Computes table-level statistical profiles.
3. `build_graph`
Builds FK graph and computes table importance ranking.
4. `propose_questions`
Generates exploratory questions aligned with discovered domain structure.
5. `generate_sql`
Produces SQL from the selected question and verified schema.
6. `execute_sql`
Runs SQL in read-only mode.
7. `fix_sql`
Repairs SQL when execution errors occur.
8. `generate_report`
Builds the final EDA narrative and findings.

For exploration-only mode, the graph can finish with a database summary flow after question proposal.

## Algorithms and Heuristics

### 1. Schema Graph Construction

- Directed graph where nodes are tables and edges are foreign keys (`child -> parent`)
- Captures relational topology for downstream importance scoring

### 2. Centrality Scoring (PageRank)

- Uses PageRank over FK graph to detect structurally central tables
- Falls back to normalized in-degree if PageRank cannot converge

### 3. Composite Table Importance Score

A weighted additive score ranks candidate tables for exploration:

- Row volume (normalized)
- Graph centrality
- Semantic table-name signal
- Presence of numeric metrics
- Data quality proxy (1 - null ratio)
- Presence of temporal columns

This produces interpretable prioritization for EDA focus.

### 4. Two-Phase SQL Generation

- Phase A: select relevant tables from the complete schema
- Phase B: generate SQL using only verified DDL fragments from selected tables

This reduces hallucinated joins and non-existent columns.

### 5. SQL Self-Healing Loop

When DB execution raises `ProgrammingError` or `OperationalError`, the pipeline sends the failing SQL + DB error back to the LLM to produce a corrected query, with bounded retries.

## Architecture

The project follows **Hexagonal Architecture (Ports & Adapters)** with clear DDD-style boundaries.

```text
Driving Adapter (CLI)
        |
        v
Application Layer
  - RunEdaUseCase
  - EdaSessionGraph (LangGraph)
        |
        v
Domain Ports
  - EdaUseCase (inbound)
  - DatabasePort / LlmPort / ProfilingPort (outbound)
        |
        v
Infrastructure Adapters
  - PostgreSQL/MySQL/Oracle adapters
  - SQL profiling adapter
  - Ollama adapter
  - Schema graph service
```

### Layer Responsibilities

- **Domain**: core entities and contracts, no infrastructure coupling
- **Application**: orchestration and use-case logic
- **Infrastructure**: concrete DB/LLM/profiling implementations
- **Adapters**: CLI interaction and presentation

## Tech Stack

- Python 3.12
- uv
- Typer + Rich
- SQLAlchemy async + asyncpg + aiomysql + oracledb
- LangGraph + LangChain Core
- Ollama
- NetworkX + Matplotlib

## Quickstart

### 1. Install

```bash
uv sync
```

### 2. Configure environment

```bash
export DATABASE_URL="postgresql+asyncpg://user:password@host:5432/dbname"
export OLLAMA_MODEL="llama3.2:latest"
export OLLAMA_BASE_URL="http://localhost:11434"
export OLLAMA_TIMEOUT="300"
```

Optional cache fix for restricted environments:

```bash
export MPLCONFIGDIR="$(pwd)/.tmp/mplconfig"
mkdir -p "$MPLCONFIGDIR"
```

### 3. Start Ollama

```bash
ollama pull llama3.2:latest
ollama serve
```

### 4. Run

```bash
uv run omniquery --help
uv run omniquery ask "What are the top 10 customers by total orders?"
uv run omniquery explore
```

## CLI Commands

- `omniquery ask "<question>"`
Run a single natural-language EDA query.
- `omniquery explore`
Run full multi-agent exploration.
- `omniquery suggest`
Generate suggested EDA questions.
- `omniquery profile --top <n>`
Show top-ranked tables and profiling metrics.
- `omniquery schema`
Print schema details (tables, columns, PKs, FKs).

## Safety and Reliability

- Enforced `SELECT`-only execution policy
- Automatic `LIMIT` insertion when missing
- Bounded retry loop for SQL repair
- Schema-verified prompts to reduce hallucinations
- Async orchestration with explicit layer boundaries

## Project Structure

```text
src/omniquery/
  adapters/cli/
  application/
    agents/
    use_cases/
  domain/
    entities/
    ports/
  infrastructure/
    db/
    graph/
    llm/
    container.py
scripts/aws_import/
dbs/
tests/
```

## What Is Still in Development

- Web API adapter (FastAPI) and browser-based UI
- Broader automated test coverage (unit + integration)
- More robust engine-specific profiling and SQL dialect hardening
- Expanded visualization workflows and interactive session controls
- Additional enterprise-grade observability and runtime diagnostics

## Current Maturity

The CLI and core orchestration are functional and architecturally solid for iterative EDA workflows. The platform is actively evolving toward full multi-interface delivery (CLI + Web) and stronger production hardening.
