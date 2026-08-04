"""OpenTelemetry tracing, gated by the ENABLE_TRACING feature flag.

When the flag is off (or the OpenTelemetry packages are not installed) every
public helper here degrades to a cheap no-op, so the rest of the app can call
``workflow_span(...)`` unconditionally.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.core.settings import AppSettings

logger = logging.getLogger(__name__)

# Low-value/noisy endpoints kept out of traces (health checks, topology, config).
EXCLUDED_URLS = "/health,/graph,/providers,/metrics"

_TRACING_ENABLED = False


def setup_tracing(app: "FastAPI", settings: "AppSettings") -> None:
    """Configure a TracerProvider and instrument FastAPI, if the flag is on."""
    global _TRACING_ENABLED
    if not settings.enable_tracing:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        logger.warning(
            "ENABLE_TRACING is set but OpenTelemetry is not installed; "
            "run `pip install -e '.[observability]'`. Tracing disabled."
        )
        return

    provider = TracerProvider(resource=Resource.create({"service.name": settings.service_name}))
    provider.add_span_processor(BatchSpanProcessor(_build_exporter(settings)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls=EXCLUDED_URLS)

    _TRACING_ENABLED = True
    logger.info("OpenTelemetry tracing enabled (service=%s).", settings.service_name)


def _build_exporter(settings: "AppSettings"):
    """OTLP/HTTP exporter when an endpoint is configured, else console."""
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    if settings.otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            logger.info("OTel traces exporting to OTLP endpoint %s", settings.otlp_endpoint)
            return OTLPSpanExporter(endpoint=settings.otlp_endpoint)
        except ImportError:
            logger.warning("OTLP exporter not installed; falling back to console span exporter.")

    logger.info("OTel traces exporting to console (set OTEL_EXPORTER_OTLP_ENDPOINT for OTLP).")
    return ConsoleSpanExporter()


@contextmanager
def workflow_span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a span for a unit of workflow work.

    Yields the live span when tracing is enabled, otherwise ``None`` so callers
    can guard attribute writes with ``if span is not None``.
    """
    if not _TRACING_ENABLED:
        yield None
        return

    from opentelemetry import trace

    tracer = trace.get_tracer("app.workflow")
    with tracer.start_as_current_span(name) as span:
        _set_attributes(span, attributes)
        yield span


def _set_attributes(span: Any, attributes: dict[str, Any]) -> None:
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)
