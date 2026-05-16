"""Dialect-aware statement-timeout helpers.

Each engine ships its own knob for limiting a query's wall-clock cost:

- PostgreSQL → ``SET LOCAL statement_timeout = '<ms>'`` (session-local).
- MySQL/MariaDB → ``SET SESSION MAX_EXECUTION_TIME = <ms>`` (5.7.8+).
- Oracle → no portable in-session setting; we approximate with
  ``asyncio.wait_for`` at the caller side.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from omniquery.domain.entities.database_schema import EngineType


async def apply_statement_timeout(
    conn: AsyncConnection,
    engine_type: EngineType,
    timeout_ms: int,
) -> None:
    """Best-effort: set a per-statement timeout on the open connection.

    Silently no-ops for engines where the directive does not apply.
    """
    if timeout_ms <= 0:
        return
    if engine_type == EngineType.POSTGRESQL:
        await conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
    elif engine_type == EngineType.MYSQL:
        await conn.execute(
            text(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_ms)}")
        )
    # Oracle: rely on asyncio.wait_for in the caller; no in-session knob
    # that works across drivers.
