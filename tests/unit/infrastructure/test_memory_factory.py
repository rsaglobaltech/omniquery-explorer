from __future__ import annotations

import pytest

from omniquery.config import MemorySettings
from omniquery.infrastructure.llm.memory_factory import resolve_checkpointer


def test_disabled_returns_none():
    assert resolve_checkpointer(MemorySettings(enabled=False)) is None


def test_memory_backend_returns_in_memory_saver():
    saver = resolve_checkpointer(MemorySettings(enabled=True, backend="memory"))
    assert saver is not None
    # LangGraph renames the class across versions (MemorySaver →
    # InMemorySaver). Match on the class name suffix rather than identity.
    assert type(saver).__name__.endswith("MemorySaver") or type(
        saver
    ).__name__ == "InMemorySaver"


def test_sqlite_backend_without_package_raises(monkeypatch: pytest.MonkeyPatch):
    """If langgraph-checkpoint-sqlite is not installed, fail clearly."""
    import builtins

    real_import = builtins.__import__

    def _stub_import(name, *args, **kwargs):
        if name == "langgraph.checkpoint.sqlite":
            raise ImportError("module not found")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _stub_import)
    with pytest.raises(RuntimeError, match="langgraph-checkpoint-sqlite"):
        resolve_checkpointer(MemorySettings(enabled=True, backend="sqlite"))
