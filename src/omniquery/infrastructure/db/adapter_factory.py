from __future__ import annotations

from omniquery.domain.ports.outbound.database_port import DatabasePort
from omniquery.infrastructure.db.duckdb_adapter import DuckDBAdapter
from omniquery.infrastructure.db.mssql_adapter import MSSQLAdapter
from omniquery.infrastructure.db.mysql_adapter import MySQLAdapter
from omniquery.infrastructure.db.oracle_adapter import OracleAdapter
from omniquery.infrastructure.db.postgresql_adapter import PostgreSQLAdapter
from omniquery.infrastructure.db.sqlite_adapter import SQLiteAdapter

# Map of URL scheme → adapter singleton. The scheme is the part before
# the first '+' or '://' (e.g. "postgresql+asyncpg" → "postgresql").
_ENGINE_PREFIX_MAP: dict[str, DatabasePort] = {
    "postgresql": PostgreSQLAdapter(),
    "postgres": PostgreSQLAdapter(),
    "mysql": MySQLAdapter(),
    "mariadb": MySQLAdapter(),
    "oracle": OracleAdapter(),
    "sqlite": SQLiteAdapter(),
    "duckdb": DuckDBAdapter(),
    "mssql": MSSQLAdapter(),
}


def resolve_db_adapter(connection_url: str) -> DatabasePort:
    """
    Return the correct DatabasePort implementation by inspecting the
    URL scheme prefix (e.g. 'postgresql+asyncpg://...').

    Raises:
        ValueError: if the URL prefix is not supported.
    """
    scheme = connection_url.split("://")[0].split("+")[0].lower()
    adapter = _ENGINE_PREFIX_MAP.get(scheme)
    if adapter is None:
        supported = sorted({k for k in _ENGINE_PREFIX_MAP})
        raise ValueError(
            f"Unsupported DB scheme '{scheme}'. Supported: {supported}"
        )
    return adapter
