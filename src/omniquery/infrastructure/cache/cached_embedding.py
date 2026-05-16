"""Decorator that wraps any EmbeddingPort with a per-text disk cache."""

from __future__ import annotations

import logging

from omniquery.config import CacheSettings
from omniquery.domain.ports.outbound.embedding_port import EmbeddingPort
from omniquery.infrastructure.cache.disk_cache import DiskCache, fingerprint

logger = logging.getLogger(__name__)


class CachedEmbeddingPort(EmbeddingPort):
    """Cache embeddings keyed by (model, text) to avoid recomputing them."""

    def __init__(
        self,
        inner: EmbeddingPort,
        settings: CacheSettings,
        model_id: str,
    ) -> None:
        self._inner = inner
        self._settings = settings
        self._model_id = model_id
        self._cache: DiskCache[list[float]] = DiskCache(settings.dir, "embeddings")

    def _key(self, text: str) -> str:
        return fingerprint("embed", self._model_id, text)

    async def embed(self, text: str) -> list[float]:
        if not self._settings.enabled:
            return await self._inner.embed(text)
        key = self._key(text)
        hit = self._cache.get(key, ttl_seconds=self._settings.embedding_ttl_seconds)
        if hit is not None:
            return hit
        vec = await self._inner.embed(text)
        self._cache.set(key, vec)
        return vec

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not self._settings.enabled or not texts:
            return await self._inner.embed_batch(texts)

        keys = [self._key(t) for t in texts]
        cached: list[list[float] | None] = [
            self._cache.get(k, ttl_seconds=self._settings.embedding_ttl_seconds)
            for k in keys
        ]
        missing_idx = [i for i, c in enumerate(cached) if c is None]
        if missing_idx:
            missing_texts = [texts[i] for i in missing_idx]
            fresh = await self._inner.embed_batch(missing_texts)
            for i, vec in zip(missing_idx, fresh):
                cached[i] = vec
                self._cache.set(keys[i], vec)
        return [c for c in cached if c is not None]
