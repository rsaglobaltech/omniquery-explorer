from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from omniquery.config import get_settings
from omniquery.domain.entities.column import Column, ForeignKey
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.domain.ports.outbound.database_port import DatabasePort
from omniquery.infrastructure.db.engine_pool import AsyncEnginePool, get_default_pool
from omniquery.infrastructure.db.sql_guard import (
    SqlGuardError,
    apply_limit,
    assert_read_only,
)
from omniquery.infrastructure.db.statement_timeout import apply_statement_timeout
from omniquery.infrastructure.governance.cost_guard import (
    CostGuardError,
    explain_and_check,
)


class BaseSQLAdapter(DatabasePort):
    """
    Shared logic for all SQLAlchemy-based DB adapters.

    Subclasses must implement:
        - engine_type  (property)
        - _introspect  (async, returns list[Table])

    Engines are obtained from a process-wide pool keyed by connection URL,
    so multiple ``get_schema`` / ``execute_query`` calls against the same
    target reuse the same warm connection pool.
    """

    def __init__(self, pool: AsyncEnginePool | None = None) -> None:
        self._pool = pool or get_default_pool()

    # ------------------------------------------------------------------
    # Abstract interface for subclasses
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def engine_type(self) -> EngineType: ...

    @abstractmethod
    async def _introspect(
        self, engine: AsyncEngine, connection_url: str
    ) -> tuple[list[Table], str | None]:
        """
        Returns (tables, db_name).
        Subclasses use SQLAlchemy inspect or raw information_schema queries.
        """

    # ------------------------------------------------------------------
    # DatabasePort implementation
    # ------------------------------------------------------------------

    async def get_schema(self, connection_url: str) -> DatabaseSchema:
        engine = await self._pool.get(connection_url)
        tables, db_name = await self._introspect(engine, connection_url)
        return DatabaseSchema(
            engine=self.engine_type,
            tables=tables,
            db_name=db_name,
        )

    async def execute_query(
        self, connection_url: str, sql: str, max_rows: int = 500
    ) -> list[dict[str, Any]]:
        engine_type = self.engine_type
        # SqlGuardError already subclasses ValueError, so re-raise it
        # unchanged. Surfacing the precise exception lets the use-case
        # tell parse/safety failures apart from generic ValueErrors and
        # route them through the LLM repair loop.
        assert_read_only(sql, engine_type)
        safe_sql = apply_limit(sql, max_rows, engine_type)

        settings = get_settings()
        timeout_ms = settings.db.statement_timeout_ms
        engine = await self._pool.get(connection_url)

        async def _run() -> list[dict[str, Any]]:
            async with engine.connect() as conn:
                from sqlalchemy import text

                # Apply per-statement timeout BEFORE running anything heavy
                # so even the EXPLAIN itself is bounded.
                await apply_statement_timeout(conn, engine_type, timeout_ms)
                # Cost-guard: ask the planner if this query is reasonable.
                # No-op when explain_enabled is false or engine is Oracle.
                try:
                    await explain_and_check(
                        conn, engine_type, safe_sql, settings.cost
                    )
                except CostGuardError as exc:
                    # Surface as ValueError so the use-case retry loop
                    # treats it as a non-retryable validation failure.
                    raise ValueError(str(exc)) from exc

                result = await conn.execute(text(safe_sql))
                keys = list(result.keys())
                rows = result.fetchmany(max_rows)
                return [dict(zip(keys, row, strict=False)) for row in rows]

        if engine_type == EngineType.ORACLE and timeout_ms > 0:
            return await asyncio.wait_for(_run(), timeout=timeout_ms / 1000)
        return await _run()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_read_only(sql: str, engine: EngineType | None = None) -> None:
        """Back-compat wrapper around the AST guard."""
        try:
            assert_read_only(sql, engine)
        except SqlGuardError as exc:
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _apply_limit(
        sql: str, max_rows: int, engine: EngineType | None = None
    ) -> str:
        """Back-compat wrapper around the AST-based limit rewriter."""
        return apply_limit(sql, max_rows, engine)

    @staticmethod
    def _build_column(
        name: str,
        sql_type: str,
        nullable: bool,
        is_pk: bool,
        fk_table: str | None = None,
        fk_col: str | None = None,
        comment: str | None = None,
    ) -> Column:
        fk = ForeignKey(fk_table, fk_col) if fk_table and fk_col else None
        return Column(
            name=name,
            sql_type=sql_type,
            nullable=nullable,
            is_primary_key=is_pk,
            foreign_key=fk,
            comment=comment,
        )
