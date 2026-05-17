from __future__ import annotations

import pytest

from omniquery.infrastructure.llm.i18n import (
    GENERATE_SQL,
    PROPOSE_QUESTIONS,
    REPORT,
    detect_locale,
    resolve_locale,
)


class TestDetectLocale:
    @pytest.mark.parametrize(
        "text",
        [
            "How many customers are registered?",
            "Show the top 5 products by revenue",
            "Average order value by country last year",
        ],
    )
    def test_english_questions_detected(self, text: str):
        assert detect_locale(text) == "en"

    @pytest.mark.parametrize(
        "text",
        [
            "¿Cuántos clientes hay registrados?",
            "Muestra los 5 productos top por ingresos",
            "Valor medio de pedido por país el último año",
        ],
    )
    def test_spanish_questions_detected(self, text: str):
        assert detect_locale(text) == "es"

    def test_diacritics_force_spanish(self):
        # Mixed-language text with a single Spanish diacritic should
        # still resolve to ES (typical "Spanglish" question).
        assert detect_locale("How many clientes ¿son activos?") == "es"

    def test_empty_text_defaults_to_english(self):
        assert detect_locale("") == "en"

    def test_non_word_text_defaults_to_english(self):
        assert detect_locale("12345 !!!") == "en"


class TestResolveLocale:
    def test_explicit_setting_overrides_detection(self):
        # Even with Spanish text, an explicit setting=en wins.
        assert resolve_locale("en", "¿Cuántos clientes?") == "en"
        assert resolve_locale("es", "How many customers?") == "es"

    def test_auto_routes_to_detection(self):
        assert resolve_locale("auto", "How many customers?") == "en"
        assert resolve_locale("auto", "¿Cuántos clientes?") == "es"

    def test_unknown_setting_falls_back_to_auto(self):
        assert resolve_locale("xx", "How many customers?") == "en"


class TestTemplatesCoverage:
    """All templates must define both supported locales."""

    @pytest.mark.parametrize(
        "registry",
        [GENERATE_SQL, REPORT, PROPOSE_QUESTIONS],
    )
    def test_each_template_has_en_and_es(self, registry):
        assert "en" in registry and "es" in registry
        assert registry["en"] and registry["es"]
