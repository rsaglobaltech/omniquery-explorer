"""SQLite adapter.

SQLite has no information_schema, so introspection goes through
SQLAlchemy's reflection API (which under the hood reads from
``sqlite_master`` / ``PRAGMA``).

Connection URL: ``sqlite+aiosqlite:////absolute/path.db`` (note the four
slashes for absolute paths) or ``sqlite+aiosqlite:///:memory:``.
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
    """Best-effort extraction of a human-readable DB name from a SQLite URL."""
    parsed = urlparse(connection_url)
    # urlparse strips the scheme; SQLite uses an empty netloc so the
    # path holds the actual file location with a leading '/'.
    path = parsed.path.lstrip("/")
    if not path or path == ":memory:":
        return path or None
    return Path(path).stem


class SQLiteAdapter(BaseSQLAdapter):
    """Driven adapter for SQLite using the aiosqlite driver."""

    @property
    def engine_type(self) -> EngineType:
        return EngineType.SQLITE

    async def _introspect(
        self, engine: AsyncEngine, connection_url: str
    ) -> tuple[list[Table], str | None]:
        # Run SQLAlchemy's sync inspector inside the async engine via
        # run_sync — the inspector itself is not async-aware.
        async with engine.connect() as conn:

            def _do_introspect(sync_conn) -> list[Table]:
                inspector = sa_inspect(sync_conn)
                tables: list[Table] = []
                for tname in inspector.get_table_names():
                    columns = []
                    pk_cols = set(
                        inspector.get_pk_constraint(tname).get("constrained_columns", [])
                    )
                    fk_map: dict[str, tuple[str, str]] = {}
                    for fk in inspector.get_foreign_keys(tname):
                        for local, ref in zip(
                            fk.get("constrained_columns", []),
                            fk.get("referred_columns", []),
                            strict=False,
                        ):
                            fk_map[local] = (fk.get("referred_table", ""), ref)
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
