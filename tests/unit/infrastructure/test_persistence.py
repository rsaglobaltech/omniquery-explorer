from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from omniquery.config import PersistenceSettings
from omniquery.domain.entities.eda_query import EdaQuery
from omniquery.infrastructure.persistence.session_store import PersistenceStore


@pytest.fixture()
def store_settings(tmp_path: Path) -> PersistenceSettings:
    db_file = tmp_path / "test.db"
    return PersistenceSettings(
        enabled=True,
        database_url=f"sqlite+aiosqlite:///{db_file}",
    )


@pytest.mark.asyncio
async def test_start_session_and_record_query(store_settings: PersistenceSettings):
    store = PersistenceStore(store_settings)
    sid = await store.start_session("postgresql+asyncpg://u:p@h/db", "postgresql")
    assert sid

    qid = await store.record_query(
        session_id=sid,
        query=EdaQuery(question="¿cuántos clientes?", connection_url="x", max_rows=10),
        generated_sql="SELECT COUNT(*) FROM customers",
        status="ok",
        error="",
        row_count=1,
        duration_ms=12,
        report_markdown="# Report",
    )
    assert qid

    engine = create_async_engine(store_settings.database_url)
    async with engine.connect() as conn:
        r = await conn.execute(text("SELECT COUNT(*) FROM sessions"))
        assert r.scalar() == 1
        r = await conn.execute(text("SELECT COUNT(*) FROM queries"))
        assert r.scalar() == 1
        r = await conn.execute(text("SELECT COUNT(*) FROM reports"))
        assert r.scalar() == 1
    await engine.dispose()
    await store.aclose()


@pytest.mark.asyncio
async def test_disabled_store_is_noop(tmp_path: Path):
    store = PersistenceStore(
        PersistenceSettings(
            enabled=False,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'x.db'}",
        )
    )
    sid = await store.start_session("u", "postgresql")
    assert sid == ""
    qid = await store.record_query(
        session_id="",
        query=EdaQuery(question="q", connection_url="x", max_rows=1),
        generated_sql="",
        status="ok",
        error="",
        row_count=0,
        duration_ms=0,
    )
    assert qid == ""
    await store.aclose()
