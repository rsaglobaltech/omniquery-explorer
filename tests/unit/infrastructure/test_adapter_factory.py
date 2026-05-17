from __future__ import annotations

import pytest

from omniquery.infrastructure.db.adapter_factory import resolve_db_adapter
from omniquery.infrastructure.db.duckdb_adapter import DuckDBAdapter
from omniquery.infrastructure.db.mysql_adapter import MySQLAdapter
from omniquery.infrastructure.db.oracle_adapter import OracleAdapter
from omniquery.infrastructure.db.postgresql_adapter import PostgreSQLAdapter
from omniquery.infrastructure.db.sqlite_adapter import SQLiteAdapter


@pytest.mark.parametrize(
    "url, expected",
    [
        ("postgresql+asyncpg://u:p@h/d", PostgreSQLAdapter),
        ("postgres://u:p@h/d", PostgreSQLAdapter),
        ("mysql+aiomysql://u:p@h/d", MySQLAdapter),
        ("mariadb+aiomysql://u:p@h/d", MySQLAdapter),
        ("oracle+oracledb://u:p@h/d", OracleAdapter),
        ("sqlite+aiosqlite:///x.db", SQLiteAdapter),
        ("duckdb:///:memory:", DuckDBAdapter),
    ],
)
def test_resolves_by_url_prefix(url: str, expected: type) -> None:
    assert isinstance(resolve_db_adapter(url), expected)


def test_unknown_scheme_raises() -> None:
    with pytest.raises(ValueError):
        resolve_db_adapter("snowflake://acct/db")
