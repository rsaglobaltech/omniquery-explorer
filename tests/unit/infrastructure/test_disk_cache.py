from __future__ import annotations

import time
from pathlib import Path

import pytest

from omniquery.infrastructure.cache.disk_cache import DiskCache, fingerprint


@pytest.fixture()
def tmp_cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "cache"


def test_fingerprint_is_stable_and_distinct():
    assert fingerprint("a", "b") == fingerprint("a", "b")
    assert fingerprint("a", "b") != fingerprint("b", "a")


def test_set_then_get_round_trips(tmp_cache_dir: Path):
    c: DiskCache[dict] = DiskCache(tmp_cache_dir, "test")
    c.set("k", {"hello": "world"})
    assert c.get("k", ttl_seconds=60) == {"hello": "world"}


def test_get_missing_returns_none(tmp_cache_dir: Path):
    c: DiskCache[dict] = DiskCache(tmp_cache_dir, "test")
    assert c.get("missing", ttl_seconds=60) is None


def test_ttl_expires(tmp_cache_dir: Path):
    c: DiskCache[int] = DiskCache(tmp_cache_dir, "test")
    c.set("k", 42)
    # ttl 0 means no expiry policy applied (treated as fresh)
    assert c.get("k", ttl_seconds=0) == 42
    # negative wait simulated by ttl=1 with sleep
    time.sleep(1.1)
    assert c.get("k", ttl_seconds=1) is None


def test_invalidate_removes_entry(tmp_cache_dir: Path):
    c: DiskCache[str] = DiskCache(tmp_cache_dir, "test")
    c.set("k", "v")
    c.invalidate("k")
    assert c.get("k", ttl_seconds=60) is None


def test_clear_wipes_namespace(tmp_cache_dir: Path):
    c: DiskCache[str] = DiskCache(tmp_cache_dir, "test")
    c.set("a", "1")
    c.set("b", "2")
    c.clear()
    assert c.get("a", ttl_seconds=60) is None
    assert c.get("b", ttl_seconds=60) is None
