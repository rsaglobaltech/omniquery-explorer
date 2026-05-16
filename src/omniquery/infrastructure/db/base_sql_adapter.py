from __future__ import annotations

from abc import abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from omniquery.domain.entities.column import Column, ForeignKey
from omniquery.domain.entities.database_schema import DatabaseSchema, EngineType
from omniquery.domain.entities.table import Table
from omniquery.domain.ports.outbound.database_port import DatabasePort
from omniquery.infrastructure.db.sql_guard import (
    SqlGuardError,
    apply_limit,
    assert_read_only,
)


class BaseSQLAdapter(DatabasePort):
    """
    Shared logic for all SQLAlchemy-based DB adapters.

    Subclasses must implement:
        - engine_type  (property)
        - _introspect  (async, returns list[Table])
    """

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
        engine = create_async_engine(connection_url, echo=False)
        try:
            tables, db_name = await self._introspect(engine, connection_url)
        finally:
            await engine.dispose()

        return DatabaseSchema(
            engine=self.engine_type,
            tables=tables,
            db_name=db_name,
        )

    async def execute_query(
        self, connection_url: str, sql: str, max_rows: int = 500
    ) -> list[dict[str, Any]]:
        engine_type = self.engine_type
        try:
            assert_read_only(sql, engine_type)
            safe_sql = apply_limit(sql, max_rows, engine_type)
        except SqlGuardError as exc:
            raise ValueError(str(exc)) from exc

        engine = create_async_engine(connection_url, echo=False)
        try:
            async with engine.connect() as conn:
                from sqlalchemy import text

                result = await conn.execute(text(safe_sql))
                keys = list(result.keys())
                rows = result.fetchmany(max_rows)
                return [dict(zip(keys, row)) for row in rows]
        finally:
            await engine.dispose()

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
