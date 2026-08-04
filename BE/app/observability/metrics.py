"""Prometheus-style application metrics, gated by the ENABLE_METRICS flag.

When the flag is off (or prometheus-client is not installed) the record
helpers are cheap no-ops and no /metrics endpoint is mounted.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.core.settings import AppSettings

logger = logging.getLogger(__name__)

METRICS_PATH = "/metrics"

_METRICS_ENABLED = False
_metrics: dict[str, Any] = {}


def setup_metrics(app: "FastAPI", settings: "AppSettings") -> None:
    """Register metrics, an HTTP-timing middleware, and the /metrics route."""
    global _METRICS_ENABLED
    if not settings.enable_metrics:
        return
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
    except ImportError:
        logger.warning(
            "ENABLE_METRICS is set but prometheus-client is not installed; "
            "run `pip install -e '.[observability]'`. Metrics disabled."
        )
        return

    from starlette.requests import Request
    from starlette.responses import Response

    _metrics["http_requests"] = Counter(
        "http_requests_total",
        "Total HTTP requests handled.",
        ["method", "path", "status"],
    )
    _metrics["http_latency"] = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds.",
        ["method", "path"],
    )
    _metrics["claims_total"] = Counter(
        "claims_processed_total",
        "Claim workflows processed, by terminal status.",
        ["tenant", "provider", "status"],
    )
    _metrics["claim_duration"] = Histogram(
        "claim_processing_duration_seconds",
        "Time to run a claim workflow end to end, in seconds.",
    )
    _metrics["node_runs"] = Counter(
        "workflow_node_runs_total",
        "LangGraph node executions.",
        ["node"],
    )
    _metrics["node_duration"] = Histogram(
        "workflow_node_duration_seconds",
        "Per-node execution time, in seconds.",
        ["node"],
    )
    _metrics["llm_requests"] = Counter(
        "llm_requests_total",
        "LLM calls issued, by provider/operation/model.",
        ["provider", "operation", "model"],
    )
    _metrics["llm_errors"] = Counter(
        "llm_request_errors_total",
        "LLM calls that raised an error.",
        ["provider", "operation"],
    )
    _metrics["llm_duration"] = Histogram(
        "llm_request_duration_seconds",
        "LLM call latency, in seconds.",
        ["provider", "operation"],
    )

    @app.middleware("http")
    async def _prometheus_middleware(request: Request, call_next):
        if request.url.path == METRICS_PATH:
            return await call_next(request)
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        route = _route_template(request)
        _metrics["http_latency"].labels(request.method, route).observe(elapsed)
        _metrics["http_requests"].labels(request.method, route, response.status_code).inc()
        return response

    @app.get(METRICS_PATH, include_in_schema=False)
    def metrics_endpoint() -> "Response":
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    _METRICS_ENABLED = True
    logger.info("Prometheus metrics enabled at %s.", METRICS_PATH)


def _route_template(request: Any) -> str:
    """Matched route path (e.g. /workflows/{workflow_id}) to keep cardinality low."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def record_claim_result(
    tenant_id: str,
    provider_id: str,
    status: str,
    duration_seconds: float | None = None,
) -> None:
    """Record the terminal status (and optional duration) of a claim workflow."""
    if not _METRICS_ENABLED:
        return
    _metrics["claims_total"].labels(tenant_id, provider_id, status).inc()
    if duration_seconds is not None:
        _metrics["claim_duration"].observe(duration_seconds)


def record_node(node: str, duration_seconds: float) -> None:
    """Record a single LangGraph node execution."""
    if not _METRICS_ENABLED:
        return
    _metrics["node_runs"].labels(node).inc()
    _metrics["node_duration"].labels(node).observe(duration_seconds)


def record_llm(
    provider: str,
    operation: str,
    model: str,
    duration_seconds: float,
    error: bool = False,
) -> None:
    """Record a single LLM call (success or failure)."""
    if not _METRICS_ENABLED:
        return
    _metrics["llm_requests"].labels(provider, operation, model).inc()
    _metrics["llm_duration"].labels(provider, operation).observe(duration_seconds)
    if error:
        _metrics["llm_errors"].labels(provider, operation).inc()
