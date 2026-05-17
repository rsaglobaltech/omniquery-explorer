"""Unit tests for the semantic question cache.

We use a tiny deterministic embedder so cosine scores are predictable
and the test is independent of any model rollout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from omniquery.config import SemanticCacheSettings
from omniquery.domain.ports.outbound.embedding_port import EmbeddingPort
from omniquery.infrastructure.cache.disk_cache import DiskCache
from omniquery.infrastructure.cache.semantic_cache import (
    SemanticQueryCache,
    _cosine,
)


class _DummyEmbedder(EmbeddingPort):
    """Maps a question's leading word to one of two fixed unit vectors.

    Anything containing 'top' (case-insensitive) becomes the X axis;
    everything else becomes the Y axis. That keeps the test free of
    floating-point fuzz while still exercising cosine-based matching.
    """

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0] if "top" in text.lower() else [0.0, 1.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


@pytest.fixture()
def cache(tmp_path: Path) -> SemanticQueryCache:
    settings = SemanticCacheSettings(enabled=True, threshold=0.9, max_entries=3)
    disk: DiskCache = DiskCache(tmp_path, "semantic_test")
    return SemanticQueryCache(settings, _DummyEmbedder(), disk)


# ---------------------------------------------------------------------------
# Cosine helper
# ---------------------------------------------------------------------------


def test_cosine_identical_vectors():
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_vectors():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_zero_vector_safe():
    # Degenerate input must NOT raise; the cache treats it as no match.
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_mismatched_lengths_safe():
    assert _cosine([1.0], [1.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# Lookup & store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_miss_on_empty_cache(cache: SemanticQueryCache):
    assert await cache.lookup("top customers", "postgres://x") is None


@pytest.mark.asyncio
async def test_store_then_lookup_hits(cache: SemanticQueryCache):
    await cache.store("top customers", "SELECT * FROM customers", "postgres://x")
    hit = await cache.lookup("top customers", "postgres://x")
    assert hit is not None
    assert hit.generated_sql == "SELECT * FROM customers"
    # First match also bumps the hit counter so eviction can favour
    # frequently-used entries.
    assert hit.hits == 1


@pytest.mark.asyncio
async def test_orthogonal_question_misses(cache: SemanticQueryCache):
    """Cosine ≈ 0 between the X-axis and the Y-axis: must not hit."""
    await cache.store("top customers", "SELECT 1", "postgres://x")
    assert await cache.lookup("bottom customers", "postgres://x") is None


@pytest.mark.asyncio
async def test_cross_db_lookup_is_partitioned(cache: SemanticQueryCache):
    """Same question against a different DB URL must NOT hit."""
    await cache.store("top customers", "SELECT 1", "postgres://x")
    assert await cache.lookup("top customers", "mysql://other") is None


@pytest.mark.asyncio
async def test_disabled_cache_skips_lookup_and_store():
    disabled = SemanticQueryCache(
        SemanticCacheSettings(enabled=False),
        _DummyEmbedder(),
        DiskCache(Path("/tmp"), "noop"),
    )
    await disabled.store("q", "SELECT 1", "postgres://x")
    assert disabled.snapshot() == []
    assert await disabled.lookup("q", "postgres://x") is None


@pytest.mark.asyncio
async def test_max_entries_evicts_oldest(cache: SemanticQueryCache):
    """``max_entries=3`` must cap the in-memory store."""
    for i in range(5):
        # The embedder maps everything without 'top' to the Y axis, so
        # all five entries land in the same bucket — still fine to test
        # eviction by count.
        await cache.store(f"q{i}", f"SELECT {i}", "postgres://x")
    assert len(cache.snapshot()) == 3


@pytest.mark.asyncio
async def test_invalidate_drops_partition(cache: SemanticQueryCache):
    await cache.store("top customers", "SELECT 1", "postgres://x")
    await cache.store("orders", "SELECT 2", "mysql://y")
    removed = cache.invalidate("postgres://x")
    assert removed == 1
    assert len(cache.snapshot()) == 1
