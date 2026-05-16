from __future__ import annotations

import pytest

from omniquery.infrastructure.db.engine_pool import AsyncEnginePool


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
