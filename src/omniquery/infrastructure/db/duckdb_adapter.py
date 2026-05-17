"""DuckDB adapter.

DuckDB ships an in-process columnar engine that natively reads Parquet
and CSV. We use the synchronous DuckDB SQLAlchemy dialect via
``duckdb_engine``; async wrapping happens through SQLAlchemy's async
shim (``create_async_engine`` with a sync dialect runs in a thread
pool).

Connection URL examples:
- ``duckdb:///:memory:``           (ephemeral)
- ``duckdb:////path/to/local.duckdb``

The pool builds the engine, but DuckDB itself is single-writer; that
limit is irrelevant for read-only EDA.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from omniquery.domain.entities.database_schema import EngineType
from omniquery.domain.entities.table import Table
from omniquery.infrastructure.db.base_sql_adapter import BaseSQLAdapter


def _db_name_from_url(connection_url: str) -> str | None:
    parsed = urlparse(connection_url)
    path = parsed.path.lstrip("/")
    if not path or path == ":memory:":
        return path or None
    return Path(path).stem


class DuckDBAdapter(BaseSQLAdapter):
    """Driven adapter for DuckDB via duckdb_engine."""

    @property
    def engine_type(self) -> EngineType:
        return EngineType.DUCKDB

    async def _introspect(
        self, engine: AsyncEngine, connection_url: str
    ) -> tuple[list[Table], str | None]:
        # DuckDB's dialect is sync-only; run inspection inside run_sync.
        async with engine.connect() as conn:

            def _do_introspect(sync_conn) -> list[Table]:
                inspector = sa_inspect(sync_conn)
                tables: list[Table] = []
                for tname in inspector.get_table_names():
                    pk_cols = set(
                        inspector.get_pk_constraint(tname).get("constrained_columns", [])
                    )
                    fk_map: dict[str, tuple[str, str]] = {}
                    # DuckDB may not always return FKs depending on
                    # version; iterate defensively.
                    try:
                        for fk in inspector.get_foreign_keys(tname):
                            for local, ref in zip(
                                fk.get("constrained_columns", []),
                                fk.get("referred_columns", []),
                                strict=False,
                            ):
                                fk_map[local] = (fk.get("referred_table", ""), ref)
                    except Exception:
                        pass
                    columns = []
                    for col in inspector.get_columns(tname):
                        name = col["name"]
                        fk = fk_map.get(name, (None, None))
                        columns.append(
                            self._build_column(
                                name=name,
                                sql_type=str(col["type"]),
                                nullable=bool(col.get("nullable", True)),
                                is_pk=name in pk_cols,
                                fk_table=fk[0],
                                fk_col=fk[1],
                                comment=col.get("comment"),
                            )
                        )
                    tables.append(Table(name=tname, columns=columns))
                return tables

            tables = await conn.run_sync(_do_introspect)

        return tables, _db_name_from_url(connection_url)
