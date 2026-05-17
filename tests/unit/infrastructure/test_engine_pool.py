from __future__ import annotations

import pytest

from omniquery.infrastructure.db.engine_pool import AsyncEnginePool, normalise_url


class TestNormaliseUrl:
    @pytest.mark.parametrize(
        "input_url, expected",
        [
            # Bare short forms get an async driver suffix.
            ("postgres://u:p@h/d", "postgresql+asyncpg://u:p@h/d"),
            ("postgresql://u:p@h/d", "postgresql+asyncpg://u:p@h/d"),
            ("mysql://u:p@h/d", "mysql+aiomysql://u:p@h/d"),
            ("mariadb://u:p@h/d", "mariadb+aiomysql://u:p@h/d"),
            ("oracle://u:p@h:1521/svc", "oracle+oracledb://u:p@h:1521/svc"),
            ("sqlite:///path.db", "sqlite+aiosqlite:///path.db"),
            ("mssql://u:p@h/d", "mssql+aioodbc://u:p@h/d"),
            # Already explicit — left untouched.
            ("postgresql+asyncpg://u:p@h/d", "postgresql+asyncpg://u:p@h/d"),
            ("mysql+aiomysql://u:p@h/d", "mysql+aiomysql://u:p@h/d"),
            ("duckdb:///:memory:", "duckdb:///:memory:"),
            # Unknown / garbage schemes pass through unchanged so we never
            # mangle exotic URLs we don't recognise.
            ("not-a-url", "not-a-url"),
            ("snowflake://acct/db", "snowflake://acct/db"),
        ],
    )
    def test_normalises_common_short_forms(self, input_url: str, expected: str):
        assert normalise_url(input_url) == expected

    def test_normalisation_preserves_query_string(self):
        url = "postgres://u:p@h/d?sslmode=require"
        assert normalise_url(url) == "postgresql+asyncpg://u:p@h/d?sslmode=require"

    def test_normalisation_is_case_insensitive(self):
        assert (
            normalise_url("POSTGRES://u:p@h/d")
            == "postgresql+asyncpg://u:p@h/d"
        )


@pytest.mark.asyncio
async def test_pool_returns_same_engine_for_same_url():
    pool = AsyncEnginePool(max_size=4)
    e1 = await pool.get("postgresql+asyncpg://user:pwd@host/db_test1")
    e2 = await pool.get("postgresql+asyncpg://user:pwd@host/db_test1")
    assert e1 is e2
    await pool.dispose_all()


@pytest.mark.asyncio
async def test_pool_evicts_lru_when_over_capacity():
    pool = AsyncEnginePool(max_size=2)
    a = await pool.get("postgresql+asyncpg://user:pwd@host/db_a")
    b = await pool.get("postgresql+asyncpg://user:pwd@host/db_b")
    # Access 'a' so 'b' becomes LRU
    await pool.get("postgresql+asyncpg://user:pwd@host/db_a")
    c = await pool.get("postgresql+asyncpg://user:pwd@host/db_c")
    # 'b' should have been evicted
    assert await pool.get("postgresql+asyncpg://user:pwd@host/db_a") is a
    assert await pool.get("postgresql+asyncpg://user:pwd@host/db_c") is c
    # Re-asking for b creates a new engine
    b_again = await pool.get("postgresql+asyncpg://user:pwd@host/db_b")
    assert b_again is not b
    await pool.dispose_all()
