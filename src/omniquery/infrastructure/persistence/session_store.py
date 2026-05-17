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
        """Ensure the persistence schema exists.

        Strategy:
        - In environments where ``alembic.ini`` is present (the
          repository checkout, our Docker image) we run the Alembic
          migrations programmatically. This keeps schema evolution
          single-sourced through versioned scripts.
        - Otherwise (e.g. a wheel install without the project files)
          we fall back to ``Base.metadata.create_all`` so tests and
          tiny embedded usages still work.

        Idempotent: subsequent calls are no-ops once the schema is
        marked ready.
        """
        if self._schema_ready or not self._settings.enabled:
            return

        ini_path = Path("alembic.ini")
        if ini_path.exists():
            try:
                # Import lazily so the alembic dependency stays optional
                # for the runtime path that uses create_all().
                from alembic import command  # noqa: PLC0415
                from alembic.config import Config  # noqa: PLC0415

                # Run Alembic in a worker thread because its
                # ``command.upgrade`` is sync. asyncio.to_thread keeps
                # us inside the running event loop.
                cfg = Config(str(ini_path))
                # Hand the URL through env var so env.py picks it up
                # without us mutating the global ``alembic.ini``.
                import os  # noqa: PLC0415

                os.environ["ALEMBIC_DATABASE_URL"] = self._settings.database_url
                import asyncio  # noqa: PLC0415

                await asyncio.to_thread(command.upgrade, cfg, "head")
                self._schema_ready = True
                return
            except Exception:  # noqa: BLE001
                # Fall back to create_all on any Alembic failure so a
                # broken migration tree never bricks the application.
                logger.exception(
                    "alembic upgrade failed; falling back to create_all()"
                )

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
