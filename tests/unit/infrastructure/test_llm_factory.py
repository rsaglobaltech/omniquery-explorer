"""Routing tests for resolve_llm_adapter.

Bedrock and Vertex import their underlying SDK lazily so we can prove
routing decisions without actually installing boto3 or
``anthropic[vertex]`` in CI.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from omniquery.config import LlmSettings
from omniquery.infrastructure.llm.llm_factory import resolve_llm_adapter
from omniquery.infrastructure.llm.ollama_adapter import OllamaAdapter


def test_ollama_default():
    adapter = resolve_llm_adapter(LlmSettings(provider="ollama"))
    assert isinstance(adapter, OllamaAdapter)


def test_openai_requires_api_key():
    with pytest.raises(ValueError, match="LLM_OPENAI_API_KEY"):
        resolve_llm_adapter(LlmSettings(provider="openai"))


def test_anthropic_requires_api_key():
    with pytest.raises(ValueError, match="LLM_ANTHROPIC_API_KEY"):
        resolve_llm_adapter(LlmSettings(provider="anthropic"))


def test_vertex_requires_project():
    """Vertex must fail fast without LLM_VERTEX_PROJECT regardless of SDK install."""
    with pytest.raises(ValueError, match="LLM_VERTEX_PROJECT"):
        resolve_llm_adapter(LlmSettings(provider="vertex"))


def test_bedrock_without_boto3_raises_runtime_error(monkeypatch: pytest.MonkeyPatch):
    """If boto3 is not installed, the adapter must explain the extra."""
    # Hide boto3 from the import system so the lazy import inside the
    # adapter fails the way it would on a base install.
    monkeypatch.setitem(sys.modules, "boto3", None)
    # Force re-import of the adapter module since it may have been
    # imported by another test in the same session.
    sys.modules.pop("omniquery.infrastructure.llm.bedrock_adapter", None)
    importlib.invalidate_caches()
    with pytest.raises(RuntimeError, match="boto3"):
        resolve_llm_adapter(LlmSettings(provider="bedrock"))


def test_vertex_without_anthropic_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """If anthropic[vertex] is missing, the adapter must explain the extra."""
    monkeypatch.setitem(sys.modules, "anthropic", None)
    sys.modules.pop("omniquery.infrastructure.llm.vertex_adapter", None)
    importlib.invalidate_caches()
    with pytest.raises(RuntimeError, match="anthropic"):
        resolve_llm_adapter(
            LlmSettings(provider="vertex", vertex_project="demo")
        )
