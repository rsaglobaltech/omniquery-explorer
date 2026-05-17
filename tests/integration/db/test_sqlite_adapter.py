from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from omniquery.infrastructure.db.engine_pool import get_default_pool
from omniquery.infrastructure.db.sqlite_adapter import SQLiteAdapter


@pytest.fixture()
async def sqlite_url(tmp_path: Path) -> str:
    """Create a tiny SQLite file with a customer/order pair for tests."""
    db = tmp_path / "fixture.db"
    url = f"sqlite+aiosqlite:///{db}"
    pool = get_default_pool()
    engine = await pool.get(url)
    async with engine.begin() as conn:
        # We exercise PK + FK reflection deliberately so the adapter has
        # something non-trivial to extract.
        await conn.execute(
            text(
                "CREATE TABLE customers ("
                " id INTEGER PRIMARY KEY,"
                " name TEXT NOT NULL"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE orders ("
                " id INTEGER PRIMARY KEY,"
                " customer_id INTEGER REFERENCES customers(id),"
                " total REAL"
                ")"
            )
        )
        await conn.execute(text("INSERT INTO customers (name) VALUES ('Ana'), ('Luis')"))
        await conn.execute(
            text("INSERT INTO orders (customer_id, total) VALUES (1, 9.99), (2, 14.50)")
        )
    return url


@pytest.mark.asyncio
async def test_get_schema_reflects_tables_and_fks(sqlite_url: str):
    adapter = SQLiteAdapter()
    schema = await adapter.get_schema(sqlite_url)
    names = sorted(t.name for t in schema.tables)
    assert names == ["customers", "orders"]

    orders = schema.get_table("orders")
    assert orders is not None
    fk = orders.get_column("customer_id").foreign_key
    assert fk is not None
    assert fk.referred_table == "customers"
    assert fk.referred_column == "id"


@pytest.mark.asyncio
async def test_execute_query_select(sqlite_url: str):
    adapter = SQLiteAdapter()
    rows = await adapter.execute_query(
        sqlite_url, "SELECT name FROM customers ORDER BY id", max_rows=10
    )
    assert [r["name"] for r in rows] == ["Ana", "Luis"]


@pytest.mark.asyncio
async def test_execute_query_rejects_dml(sqlite_url: str):
    adapter = SQLiteAdapter()
    with pytest.raises(ValueError):
        await adapter.execute_query(sqlite_url, "DELETE FROM customers", 10)
