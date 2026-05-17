"""Process-wide cache of SQLAlchemy AsyncEngines keyed by connection URL.

Replaces the previous behaviour of creating a brand-new engine for every
``get_schema`` / ``execute_query`` / profiling call. Engines own an
internal connection pool, so reusing them across calls keeps warm
connections and drastically reduces per-query overhead.

The pool is intentionally tiny: callers ask for an engine by URL, an
``LRU`` evicts the least-recently used engine when the cap is hit, and a
graceful ``dispose_all`` is exposed for lifespan teardown.

URLs are normalised before being looked up so common short forms users
type (``postgres://...``, ``mysql://...``) work out of the box even
though SQLAlchemy 2 requires an explicit async driver in the dialect
(``postgresql+asyncpg://...``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)


# Map of bare scheme → fully-qualified async driver URL prefix. Covers
# the popular short forms that PaaS dashboards or CLI examples tend to
# hand out. ``postgresql://`` is also re-routed because SQLAlchemy 2
# refuses it without an explicit ``+driver``.
_ASYNC_SCHEME_MAP = {
    "postgres": "postgresql+asyncpg",
    "postgresql": "postgresql+asyncpg",
    "mysql": "mysql+aiomysql",
    "mariadb": "mariadb+aiomysql",
    "oracle": "oracle+oracledb",
    "sqlite": "sqlite+aiosqlite",
    "mssql": "mssql+aioodbc",
}

# Matches the part before ``://``. We split on the literal '+' so URLs
# that already carry an explicit driver (``postgresql+asyncpg://``)
# are left untouched.
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9]*)://")


def normalise_url(url: str) -> str:
    """Return an async-driver SQLAlchemy URL for any supported short form.

    Examples:
        postgres://u:p@h/d           → postgresql+asyncpg://u:p@h/d
        postgresql://u:p@h/d         → postgresql+asyncpg://u:p@h/d
        mysql://u:p@h/d              → mysql+aiomysql://u:p@h/d
        postgresql+asyncpg://u:p@h/d → unchanged
        duckdb:///:memory:           → unchanged (already async-capable)
    """
    match = _SCHEME_RE.match(url)
    if not match:
        return url
    scheme = match.group(1).lower()
    if "+" in match.group(0):
        # Already carries an explicit driver, leave untouched.
        return url
    target = _ASYNC_SCHEME_MAP.get(scheme)
    if target is None:
        return url
    return target + "://" + url[match.end() :]


class AsyncEnginePool:
    """LRU cache of ``AsyncEngine`` keyed by SQLAlchemy URL."""

    def __init__(
        self,
        max_size: int = 8,
        pool_size: int = 5,
        max_overflow: int = 5,
        pool_recycle: int = 1800,
    ) -> None:
        self._max_size = max_size
        self._pool_size = pool_size
        self._max_overflow = max_overflow
        self._pool_recycle = pool_recycle
        self._engines: OrderedDict[str, AsyncEngine] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, connection_url: str) -> AsyncEngine:
        # Normalise BEFORE looking up so common short forms
        # (``postgres://``, ``mysql://``) share the same pooled engine
        # as their explicit async-driver equivalents.
        key = normalise_url(connection_url)
        async with self._lock:
            engine = self._engines.get(key)
            if engine is not None:
                self._engines.move_to_end(key)
                return engine

            engine = create_async_engine(
                key,
                echo=False,
                pool_pre_ping=True,
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_recycle=self._pool_recycle,
            )
            self._engines[key] = engine

            while len(self._engines) > self._max_size:
                _, evicted = self._engines.popitem(last=False)
                logger.debug("engine_pool: evicting LRU engine")
                await evicted.dispose()

            return engine

    async def dispose_all(self) -> None:
        async with self._lock:
            for engine in self._engines.values():
                await engine.dispose()
            self._engines.clear()


_default_pool: AsyncEnginePool | None = None


def get_default_pool() -> AsyncEnginePool:
    """Return the process-wide engine pool, lazily instantiated."""
    global _default_pool
    if _default_pool is None:
        _default_pool = AsyncEnginePool()
    return _default_pool
