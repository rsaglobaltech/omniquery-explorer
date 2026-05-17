"""Disk-backed semantic cache for natural-language questions.

Each successful EDA run is stored as ``(embedding, question, sql,
connection_fingerprint, created_at, hits)``. Subsequent questions are
embedded and matched by cosine similarity against the same connection
fingerprint; an entry above ``threshold`` short-circuits the LLM
``generate_sql`` step and returns the cached SQL.

Notes on scope:

- The cache is *per connection fingerprint* — SQL that works on DB A
  is almost never the right answer for DB B even if the questions are
  identical, so we partition strictly.
- Linear cosine search is fine up to a few thousand entries; beyond
  that swap the store for pgvector / sqlite-vec / FAISS without
  changing the public API.
- Persistence is pickle through ``DiskCache`` so the format is
  contained to this module — callers see only the ``CachedQuery``
  value type.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from dataclasses import dataclass, field

from omniquery.config import SemanticCacheSettings
from omniquery.domain.ports.outbound.embedding_port import EmbeddingPort
from omniquery.infrastructure.cache.disk_cache import DiskCache

logger = logging.getLogger(__name__)


@dataclass
class CachedQuery:
    """A single (question, SQL) pair plus telemetry for eviction/sorting."""

    # Embedding of ``question`` produced by the configured embedder.
    embedding: list[float]
    question: str
    generated_sql: str
    # SHA-256 prefix of the connection URL — keeps the cache scoped
    # to the database the SQL was authored against.
    connection_fingerprint: str
    created_at: float = field(default_factory=time.time)
    hits: int = 0


def _connection_fingerprint(connection_url: str) -> str:
    """Stable short fingerprint for a connection URL."""
    return hashlib.sha256(connection_url.encode("utf-8")).hexdigest()[:16]


def _cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity. Returns 0.0 on degenerate inputs."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


# We persist the whole entry list under a single cache key. That keeps
# I/O simple (one read at startup, one write on store) and removes any
# need to manage individual entry files.
_STORE_KEY = "entries"


class SemanticQueryCache:
    """Async-friendly wrapper around an in-memory list of CachedQuery."""

    def __init__(
        self,
        settings: SemanticCacheSettings,
        embedder: EmbeddingPort,
        disk: DiskCache[list[CachedQuery]],
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._disk = disk
        # Load once at startup — subsequent operations mutate the list
        # in place and flush back on every write.
        loaded = self._disk.get(_STORE_KEY, ttl_seconds=0) or []
        self._entries: list[CachedQuery] = list(loaded)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    async def lookup(
        self, question: str, connection_url: str
    ) -> CachedQuery | None:
        """Return the best-matching entry above the threshold, or None."""
        if not self._settings.enabled or not self._entries:
            return None
        target = await self._embedder.embed(question)
        fp = _connection_fingerprint(connection_url)
        best: tuple[float, CachedQuery] | None = None
        for entry in self._entries:
            # Per-DB partitioning: never serve SQL authored against a
            # different database, however similar the question reads.
            if entry.connection_fingerprint != fp:
                continue
            score = _cosine(target, entry.embedding)
            if best is None or score > best[0]:
                best = (score, entry)
        if best is None or best[0] < self._settings.threshold:
            return None
        score, entry = best
        # Bump the hit counter and persist so eviction can favour
        # hot entries on the next prune. Flushing the whole list on a
        # hit is acceptable given the in-memory list is tiny.
        entry.hits += 1
        self._flush()
        logger.info(
            "semantic_cache: HIT score=%.3f question=%r", score, question[:80]
        )
        return entry

    async def store(
        self, question: str, generated_sql: str, connection_url: str
    ) -> None:
        """Append a new entry, evict oldest if over max_entries."""
        if not self._settings.enabled:
            return
        embedding = await self._embedder.embed(question)
        entry = CachedQuery(
            embedding=embedding,
            question=question,
            generated_sql=generated_sql,
            connection_fingerprint=_connection_fingerprint(connection_url),
        )
        self._entries.append(entry)
        self._evict_if_needed()
        self._flush()

    def invalidate(self, connection_url: str) -> int:
        """Drop every entry tied to a connection. Returns count removed."""
        fp = _connection_fingerprint(connection_url)
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.connection_fingerprint != fp]
        removed = before - len(self._entries)
        if removed:
            self._flush()
        return removed

    def snapshot(self) -> list[CachedQuery]:
        """Return a copy of the current entries (for diagnostics/tests)."""
        return list(self._entries)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict_if_needed(self) -> None:
        # Evict oldest by ``created_at`` to keep cosine search bounded.
        if len(self._entries) <= self._settings.max_entries:
            return
        # Sort newest-first then keep the head; uses created_at as the
        # primary key with hits as a secondary tie-breaker so popular
        # entries survive longer when timestamps collide.
        self._entries.sort(key=lambda e: (e.created_at, e.hits), reverse=True)
        del self._entries[self._settings.max_entries :]

    def _flush(self) -> None:
        self._disk.set(_STORE_KEY, self._entries)
