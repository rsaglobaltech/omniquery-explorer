from __future__ import annotations

import importlib

import pytest


def _reload_settings():
    import omniquery.config as cfg

    importlib.reload(cfg)
    cfg.get_settings.cache_clear()
    return cfg.get_settings()


def test_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    s = _reload_settings()
    assert s.environment == "development"
    assert s.llm.provider == "ollama"
    assert s.llm.model == "llama3.2:latest"
    assert s.db.database_url is None
    assert s.cache.enabled is True


def test_llm_provider_overridable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_OPENAI_API_KEY", "sk-xxx")
    s = _reload_settings()
    assert s.llm.provider == "openai"
    assert s.llm.model == "gpt-4o-mini"
    assert s.llm.openai_api_key is not None
    assert s.llm.openai_api_key.get_secret_value() == "sk-xxx"


def test_database_url_loaded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://user:pwd@localhost/db"
    )
    s = _reload_settings()
    assert s.db.database_url is not None
    assert "user:pwd" in s.db.database_url.get_secret_value()
