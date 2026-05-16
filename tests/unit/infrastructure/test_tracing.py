from __future__ import annotations

import omniquery.infrastructure.observability.tracing as tracing_mod
from omniquery.config import ObservabilitySettings


def test_span_works_when_disabled_noop():
    tracing_mod._INITIALISED = False
    tracing_mod._TRACER = None
    tracing_mod.configure_tracing(ObservabilitySettings(otel_enabled=False))
    with tracing_mod.span("test.noop", foo="bar") as s:
        assert s is not None


def test_span_records_exception_and_reraises():
    tracing_mod._INITIALISED = False
    tracing_mod._TRACER = None
    tracing_mod.configure_tracing(ObservabilitySettings(otel_enabled=False))
    import pytest

    with pytest.raises(RuntimeError):
        with tracing_mod.span("test.error"):
            raise RuntimeError("boom")
