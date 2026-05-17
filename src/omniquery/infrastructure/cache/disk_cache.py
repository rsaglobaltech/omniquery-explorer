"""Simple disk-backed cache for schemas, profiles, and embeddings.

Keys are hashed with SHA-256 from a tuple of strings; values are pickled.
Each entry stores a `created_at` timestamp so callers can enforce TTL.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheEntry(Generic[T]):
    value: T
    created_at: float

    def is_fresh(self, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            return True
        return (time.time() - self.created_at) < ttl_seconds


def fingerprint(*parts: str) -> str:
    """Stable hex fingerprint for the given parts."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:32]


class DiskCache(Generic[T]):
    """Pickle-backed disk cache scoped under a namespace directory."""

    def __init__(self, root: Path, namespace: str) -> None:
        self._dir = Path(root) / namespace
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.pkl"

    def get(self, key: str, ttl_seconds: int = 0) -> T | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with path.open("rb") as fh:
                # The cache directory is writable only by this process,
                # so the payload is trusted. We still guard against
                # corrupted files via the broad except below.
                entry: CacheEntry[T] = pickle.load(fh)  # nosec B301
        except (pickle.PickleError, EOFError, AttributeError) as exc:
            logger.warning("cache: unreadable entry %s (%s); deleting", path, exc)
            path.unlink(missing_ok=True)
            return None
        if not entry.is_fresh(ttl_seconds):
            return None
        return entry.value

    def set(self, key: str, value: T) -> None:
        path = self._path(key)
        entry: CacheEntry[Any] = CacheEntry(value=value, created_at=time.time())
        tmp = path.with_suffix(".pkl.tmp")
        with tmp.open("wb") as fh:
            pickle.dump(entry, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)

    def invalidate(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def clear(self) -> None:
        for f in self._dir.glob("*.pkl"):
            f.unlink(missing_ok=True)
