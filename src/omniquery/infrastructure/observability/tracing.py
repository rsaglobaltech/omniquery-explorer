"""OpenTelemetry tracing bootstrap.

The tracer provider is initialised once at process start. If
``OBS_OTEL_ENABLED`` is false (the default), every span call becomes a
cheap no-op via OTel's built-in ``NoOpTracer``. When enabled, spans are
exported via OTLP/HTTP to ``OBS_OTEL_ENDPOINT``.

Usage:

    from omniquery.infrastructure.observability.tracing import span

    async def some_node(state):
        with span("agent.introspect", session_id=state["session_id"]):
            ...
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from omniquery.config import ObservabilitySettings

logger = logging.getLogger(__name__)
_INITIALISED = False
_TRACER: trace.Tracer | None = None


def configure_tracing(settings: ObservabilitySettings) -> None:
    """Initialise the global tracer provider exactly once per process."""
    global _INITIALISED, _TRACER
    if _INITIALISED:
        return
    _INITIALISED = True

    if not settings.otel_enabled:
        _TRACER = trace.get_tracer("omniquery")
        return

    resource = Resource.create({"service.name": "omniquery-explorer"})
    provider = TracerProvider(resource=resource)
    if settings.otel_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception:  # noqa: BLE001
            logger.exception("OTel exporter failed to initialise; tracing disabled")
    trace.set_tracer_provider(provider)
    _TRACER = trace.get_tracer("omniquery")


def get_tracer() -> trace.Tracer:
    if _TRACER is None:
        return trace.get_tracer("omniquery")
    return _TRACER


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Context manager wrapping an OTel span with optional attributes."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as s:
        for key, value in attributes.items():
            if value is not None:
                s.set_attribute(key, value)
        try:
            yield s
        except Exception as exc:  # noqa: BLE001
            s.record_exception(exc)
            s.set_status(trace.StatusCode.ERROR, str(exc))
            raise
