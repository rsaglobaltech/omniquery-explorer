"""FastAPI driving adapter exposing the EDA pipeline over HTTP + SSE.

Run with:
    uv run uvicorn omniquery.adapters.web.app:app --host 0.0.0.0 --port 8000

Endpoints
---------
- GET  /health             — liveness + config snapshot
- POST /ask                — single EDA query (JSON response)
- POST /ask/stream         — same as /ask, streamed as Server-Sent Events
- POST /explore            — schema + profiling + proposed questions
- POST /schema             — schema introspection

All write paths require ``X-API-Key`` when ``ENVIRONMENT=production``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from omniquery.adapters.web.rate_limit import TokenBucketRateLimiter, identity_for
from omniquery.adapters.web.schemas import (
    AskRequest,
    AskResponse,
    ExploreRequest,
    HealthResponse,
    SchemaRequest,
)
from omniquery.adapters.web.security import ApiKeyDep
from omniquery.config import get_settings
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.infrastructure.container import get_container
from omniquery.infrastructure.db.adapter_factory import resolve_db_adapter
from omniquery.infrastructure.logging.agent_observability import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    # Eagerly initialise the container so config errors surface at startup.
    get_container()
    logger.info("OmniQuery Web API started")
    yield


app = FastAPI(
    title="OmniQuery Explorer API",
    version="0.1.0",
    description="Agentic EDA pipeline exposed over HTTP.",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# Single shared limiter instance — created at module load so every
# request handler sees the same in-memory bucket store. The Container
# is intentionally not used here to keep the middleware decoupled.
_LIMITER = TokenBucketRateLimiter(get_settings().web)


@app.middleware("http")
async def _rate_limit_middleware(request: Request, call_next):
    """Apply the token-bucket gate to every HTTP request.

    /health is whitelisted so liveness probes never trip the limiter
    (they typically run with no API key from kube/orchestrator IPs).
    """
    if request.url.path != "/health" and _LIMITER.enabled:
        try:
            await _LIMITER.check(identity_for(request))
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers or {},
            )
    return await call_next(request)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        environment=s.environment,
        llm_provider=s.llm.provider,
        llm_model=s.llm.model,
    )


@app.post("/ask", response_model=AskResponse, dependencies=[ApiKeyDep])
async def ask(req: AskRequest) -> AskResponse:
    container = get_container()
    url = req.connection_url.get_secret_value()
    use_case = container.eda_use_case(url)
    result = await use_case.run_eda(
        EdaQuery(question=req.question, connection_url=url, max_rows=req.max_rows)
    )
    if result.error:
        raise HTTPException(status_code=400, detail=result.error)
    return AskResponse(
        question=result.question,
        generated_sql=result.generated_sql or "",
        row_count=result.row_count,
        rows=result.raw_data,
        report=result.report or "",
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post("/ask/stream", dependencies=[ApiKeyDep])
async def ask_stream(req: AskRequest) -> StreamingResponse:
    container = get_container()
    url = req.connection_url.get_secret_value()
    graph = container.eda_session_graph(url)

    async def _producer() -> AsyncGenerator[str, None]:
        yield _sse("started", {"question": req.question})
        try:
            result = await graph.run(
                connection_url=url, question=req.question, max_rows=req.max_rows
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("ask_stream failed")
            yield _sse("error", {"message": str(exc)})
            return

        if result.error:
            yield _sse("error", {"message": result.error})
            return

        yield _sse("sql", {"sql": result.generated_sql})
        yield _sse(
            "rows",
            {"count": result.row_count, "preview": result.raw_data[:50]},
        )
        yield _sse("report", {"markdown": result.report})
        yield _sse("done", {"row_count": result.row_count})

    return StreamingResponse(_producer(), media_type="text/event-stream")


@app.post("/explore", dependencies=[ApiKeyDep])
async def explore(req: ExploreRequest) -> dict:
    container = get_container()
    url = req.connection_url.get_secret_value()
    graph = container.eda_session_graph(url)
    questions, scored, summary = await graph.run_explore(url, req.max_rows)
    return {
        "db_summary": summary,
        "scored_tables": [
            {
                "table_name": s.table_name,
                "score": s.score,
                "row_count": s.row_count,
                "centrality": s.centrality,
                "reasons": s.reasons,
            }
            for s in scored
        ],
        "proposed_questions": [
            {
                "question": q.question,
                "tables": q.relevant_tables,
                "difficulty": q.difficulty,
                "category": q.category,
            }
            for q in questions
        ],
    }


@app.post("/schema", dependencies=[ApiKeyDep])
async def schema(req: SchemaRequest) -> dict:
    url = req.connection_url.get_secret_value()
    adapter = resolve_db_adapter(url)
    db_schema = await adapter.get_schema(url)
    return {
        "engine": db_schema.engine.value,
        "db_name": db_schema.db_name,
        "tables": [
            {
                "name": t.name,
                "comment": t.comment,
                "columns": [
                    {
                        "name": c.name,
                        "sql_type": c.sql_type,
                        "nullable": c.nullable,
                        "is_primary_key": c.is_primary_key,
                        "foreign_key": (
                            {
                                "referred_table": c.foreign_key.referred_table,
                                "referred_column": c.foreign_key.referred_column,
                            }
                            if c.foreign_key
                            else None
                        ),
                    }
                    for c in t.columns
                ],
            }
            for t in db_schema.tables
        ],
    }
