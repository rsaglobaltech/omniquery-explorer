from __future__ import annotations

from omniquery.application.agents.eda_session_graph import _parse_proposed_questions


def test_parses_well_formed_lines():
    raw = (
        "[difficulty:easy] [category:count] ¿Cuántos clientes hay? | tables: customers\n"
        "[difficulty:medium] [category:distribution] ¿Distribución de pedidos por mes? | tables: orders\n"
    )
    out = _parse_proposed_questions(raw)
    assert len(out) == 2
    assert out[0].difficulty == "easy"
    assert out[0].category == "count"
    assert out[0].relevant_tables == ["customers"]
    assert "Cuántos clientes" in out[0].question
    assert out[1].relevant_tables == ["orders"]


def test_skips_lines_without_difficulty_tag():
    raw = "garbage line\n[difficulty:hard] [category:join] ¿Top productos? | tables: products,order_items"
    out = _parse_proposed_questions(raw)
    assert len(out) == 1
    assert out[0].difficulty == "hard"
    assert out[0].relevant_tables == ["products", "order_items"]


def test_defaults_to_other_when_category_missing():
    raw = "[difficulty:medium] ¿Algo? | tables: t1"
    out = _parse_proposed_questions(raw)
    assert len(out) == 1
    assert out[0].category == "other"


def test_strips_markdown_heading_markers():
    raw = "[difficulty:easy] [category:count] ## ¿Cuántos? | tables: t1"
    out = _parse_proposed_questions(raw)
    assert out[0].question.startswith("¿")
