"""Decorator that wraps any DatabasePort with a disk-backed schema cache."""

from __future__ import annotations

import logging
from typing import Any

from omniquery.config import CacheSettings
from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.ports.outbound.database_port import DatabasePort
from omniquery.infrastructure.cache.disk_cache import DiskCache, fingerprint

logger = logging.getLogger(__name__)


class CachedDatabasePort(DatabasePort):
    """Wrap a DatabasePort and memoise `get_schema` to disk.

    ``execute_query`` is always delegated unchanged — query results are
    never cached at this layer to avoid stale data.
    """

    def __init__(self, inner: DatabasePort, settings: CacheSettings) -> None:
        self._inner = inner
        self._settings = settings
        self._cache: DiskCache[DatabaseSchema] = DiskCache(settings.dir, "schemas")

    async def get_schema(self, connection_url: str) -> DatabaseSchema:
        if not self._settings.enabled:
            return await self._inner.get_schema(connection_url)
        key = fingerprint("schema", connection_url)
        hit = self._cache.get(key, ttl_seconds=self._settings.schema_ttl_seconds)
        if hit is not None:
            logger.debug("schema cache hit for %s", key)
            return hit
        schema = await self._inner.get_schema(connection_url)
        self._cache.set(key, schema)
        return schema

    async def execute_query(
        self, connection_url: str, sql: str, max_rows: int = 500
    ) -> list[dict[str, Any]]:
        return await self._inner.execute_query(connection_url, sql, max_rows)
