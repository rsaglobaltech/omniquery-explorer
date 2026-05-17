"""Alembic env for the persistence DB.

Runs in **online** mode against the URL configured by Settings
(``PERSIST_DATABASE_URL``). Async-friendly: we use
``run_sync`` so SQLAlchemy 2's async engine can drive Alembic without
needing a parallel sync engine.

This env is invoked by:
- ``alembic -c alembic.ini upgrade head`` from the repo root, and
- the ``PersistenceStore.run_migrations()`` helper at process start.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from omniquery.config import get_settings
from omniquery.infrastructure.persistence.models import Base

# Alembic Config object — provides access to .ini values.
config = context.config

# Configure Python logging if alembic.ini specifies a [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata drives autogenerate; we wire the ORM Base here.
target_metadata = Base.metadata


def _resolve_url() -> str:
    """Pick the migration URL.

    Priority:
    1. ALEMBIC_DATABASE_URL env var (override for ops / CI).
    2. Settings.persistence.database_url (the live app config).
    """
    override = os.getenv("ALEMBIC_DATABASE_URL")
    if override:
        return override
    return get_settings().persistence.database_url


def _do_migrations(connection: Connection) -> None:
    """Synchronous body — runs inside run_sync()."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Render BATCH operations so SQLite (which doesn't fully support
        # ALTER) can still apply destructive changes safely.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Drive the migrations via an AsyncEngine."""
    engine = create_async_engine(_resolve_url(), poolclass=None, future=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_do_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Entry point Alembic looks for in this module."""
    asyncio.run(run_async_migrations())


# Alembic always calls one of run_migrations_online() / *_offline().
# Offline mode (generating SQL without a DB) is not supported here —
# we never need to ship migration scripts to a DBA — so we always
# route through the online path.
run_migrations_online()
