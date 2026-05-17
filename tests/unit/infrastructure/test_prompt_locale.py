"""Verify the prompt builders flip language based on settings + question."""

from __future__ import annotations

import importlib

import pytest

from omniquery.domain.entities.database_schema import DatabaseSchema
from omniquery.domain.entities.eda_query import EdaQuery


def _reload_settings(monkeypatch: pytest.MonkeyPatch, language: str):
    monkeypatch.setenv("LLM_LANGUAGE", language)
    import omniquery.config as cfg

    importlib.reload(cfg)
    cfg.get_settings.cache_clear()
    # llm_prompts imports get_settings; reload it too so its module-level
    # bindings pick up the refreshed cache.
    import omniquery.infrastructure.llm.llm_prompts as p

    importlib.reload(p)
    return p


@pytest.mark.parametrize(
    "language,question,expected_marker",
    [
        ("en", "How many customers?", "Question:"),
        ("es", "¿Cuántos clientes?", "Pregunta:"),
        # auto + Spanish question → Spanish prompt
        ("auto", "¿Cuál es el ingreso medio?", "Pregunta:"),
        # auto + English question → English prompt
        ("auto", "What is the average revenue?", "Question:"),
    ],
)
def test_generate_sql_prompt_localises(
    monkeypatch: pytest.MonkeyPatch,
    simple_schema: DatabaseSchema,
    language: str,
    question: str,
    expected_marker: str,
):
    prompts = _reload_settings(monkeypatch, language)
    query = EdaQuery(question=question, connection_url="x", max_rows=10)
    rendered = prompts.build_generate_sql_prompt(simple_schema, query, "TABLE foo();")
    assert expected_marker in rendered


def test_report_prompt_requests_target_language(
    monkeypatch: pytest.MonkeyPatch, simple_schema: DatabaseSchema
):
    prompts = _reload_settings(monkeypatch, "es")
    query = EdaQuery(question="¿Resumen?", connection_url="x", max_rows=10)
    rendered = prompts.build_report_prompt(simple_schema, query, [{"a": 1}])
    assert "en español" in rendered.lower()
