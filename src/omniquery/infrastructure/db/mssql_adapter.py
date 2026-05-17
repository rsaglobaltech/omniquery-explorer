"""SQL Server adapter via SQLAlchemy + aioodbc.

Connection URL examples:
- ``mssql+aioodbc:///?odbc_connect=DRIVER=ODBC+Driver+17+for+SQL+Server;SERVER=...;DATABASE=...;UID=...;PWD=...``
- Or the simpler ``mssql+aioodbc://user:pwd@host:1433/db?driver=ODBC+Driver+17+for+SQL+Server``

Introspection follows the same ``run_sync(sa_inspect)`` pattern used by
the SQLite and DuckDB adapters; reflection works against any database
the ODBC user can read. We do not enforce a particular driver — pick
the one your image carries (msodbcsql, FreeTDS, …).
"""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from omniquery.domain.entities.database_schema import EngineType
from omniquery.domain.entities.table import Table
from omniquery.infrastructure.db.base_sql_adapter import BaseSQLAdapter


def _db_name_from_url(connection_url: str) -> str | None:
    """Pull the database name out of an mssql URL, honouring odbc_connect."""
    parsed = urlparse(connection_url)
    # Standard form: mssql+aioodbc://user:pwd@host/db
    if parsed.path and parsed.path != "/":
        return parsed.path.lstrip("/")
    # Verbose form: mssql+aioodbc:///?odbc_connect=...DATABASE=foo;...
    query = parsed.query or ""
    for chunk in query.split("&"):
        if chunk.lower().startswith("odbc_connect="):
            for kv in chunk[len("odbc_connect="):].replace("+", " ").split(";"):
                if "=" in kv:
                    key, value = kv.split("=", 1)
                    if key.strip().upper() == "DATABASE":
                        return value.strip()
    return None


class MSSQLAdapter(BaseSQLAdapter):
    """Driven adapter for Microsoft SQL Server."""

    @property
    def engine_type(self) -> EngineType:
        return EngineType.MSSQL

    async def _introspect(
        self, engine: AsyncEngine, connection_url: str
    ) -> tuple[list[Table], str | None]:
        # SQLAlchemy's mssql dialect ships a sync inspector; wrap it in
        # run_sync so the call stays inside the asyncio event loop.
        async with engine.connect() as conn:

            def _do_introspect(sync_conn) -> list[Table]:
                inspector = sa_inspect(sync_conn)
                tables: list[Table] = []
                # Default schema in mssql is 'dbo'; the inspector picks
                # it up automatically when the user's default schema is
                # configured. We do not hard-code it so callers using
                # contained DBs or per-user schemas still work.
                for tname in inspector.get_table_names():
                    pk_cols = set(
                        inspector.get_pk_constraint(tname).get(
                            "constrained_columns", []
                        )
                    )
                    fk_map: dict[str, tuple[str, str]] = {}
                    try:
                        for fk in inspector.get_foreign_keys(tname):
                            for local, ref in zip(
                                fk.get("constrained_columns", []),
                                fk.get("referred_columns", []),
                                strict=False,
                            ):
                                fk_map[local] = (
                                    fk.get("referred_table", ""),
                                    ref,
                                )
                    except Exception:
                        # Some restricted users cannot read FK metadata.
                        # We continue with an empty FK map rather than
                        # failing the whole introspection.
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
