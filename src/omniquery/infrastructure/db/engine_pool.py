"""Process-wide cache of SQLAlchemy AsyncEngines keyed by connection URL.

Replaces the previous behaviour of creating a brand-new engine for every
``get_schema`` / ``execute_query`` / profiling call. Engines own an
internal connection pool, so reusing them across calls keeps warm
connections and drastically reduces per-query overhead.

The pool is intentionally tiny: callers ask for an engine by URL, an
``LRU`` evicts the least-recently used engine when the cap is hit, and a
graceful ``dispose_all`` is exposed for lifespan teardown.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)


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
        async with self._lock:
            engine = self._engines.get(connection_url)
            if engine is not None:
                self._engines.move_to_end(connection_url)
                return engine

            engine = create_async_engine(
                connection_url,
                echo=False,
                pool_pre_ping=True,
                pool_size=self._pool_size,
                max_overflow=self._max_overflow,
                pool_recycle=self._pool_recycle,
            )
            self._engines[connection_url] = engine

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
