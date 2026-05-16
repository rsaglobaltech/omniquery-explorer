"""High-level repository for the persistence layer.

The store auto-creates the schema on first use (good for SQLite default);
production deployments should use Alembic migrations against Postgres.
"""

from __future__ import annotations

import hashlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from omniquery.config import PersistenceSettings
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.infrastructure.persistence.models import (
    Base,
    QueryRecord,
    ReportRecord,
    SessionRecord,
)

logger = logging.getLogger(__name__)


def _fingerprint_url(connection_url: str) -> str:
    return hashlib.sha256(connection_url.encode("utf-8")).hexdigest()[:16]


class PersistenceStore:
    """SQLAlchemy-backed store for sessions, queries, and reports."""

    def __init__(self, settings: PersistenceSettings) -> None:
        self._settings = settings
        url = settings.database_url
        if url.startswith("sqlite+aiosqlite:///") and not url.endswith(":memory:"):
            target = url.split("sqlite+aiosqlite:///", 1)[1]
            Path(target).parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_async_engine(url, echo=False, future=True)
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False
        )
        self._schema_ready = False

    async def init_schema(self) -> None:
        if self._schema_ready or not self._settings.enabled:
            return
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._schema_ready = True

    async def aclose(self) -> None:
        await self._engine.dispose()

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        await self.init_schema()
        async with self._sessionmaker() as session:
            yield session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_session(self, connection_url: str, db_engine: str) -> str:
        if not self._settings.enabled:
            return ""
        async with self._session() as s:
            row = SessionRecord(
                connection_fingerprint=_fingerprint_url(connection_url),
                db_engine=db_engine,
            )
            s.add(row)
            await s.commit()
            return row.id

    async def record_query(
        self,
        *,
        session_id: str,
        query: EdaQuery,
        generated_sql: str,
        status: str,
        error: str,
        row_count: int,
        duration_ms: int,
        report_markdown: str = "",
    ) -> str:
        if not self._settings.enabled or not session_id:
            return ""
        async with self._session() as s:
            q = QueryRecord(
                session_id=session_id,
                question=query.question,
                generated_sql=generated_sql,
                status=status,
                error=error,
                row_count=row_count,
                duration_ms=duration_ms,
            )
            s.add(q)
            await s.flush()
            if report_markdown:
                s.add(ReportRecord(query_id=q.id, markdown=report_markdown))
            await s.commit()
            return q.id


@asynccontextmanager
async def timing() -> AsyncIterator[dict[str, float]]:
    """Convenience timer yielding a dict with ``ms`` at the end."""
    container: dict[str, float] = {"ms": 0.0}
    start = time.perf_counter()
    try:
        yield container
    finally:
        container["ms"] = round((time.perf_counter() - start) * 1000, 2)
