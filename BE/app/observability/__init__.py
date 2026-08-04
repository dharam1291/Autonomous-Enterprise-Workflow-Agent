"""Feature-flag-gated observability: OTel traces and Prometheus metrics.

Two flags drive everything (see AppSettings / .env):
  * ENABLE_TRACING -> OpenTelemetry traces
  * ENABLE_METRICS -> Prometheus metrics at /metrics

All helpers are safe to call whether or not the flags are on; when off they
are no-ops, so application code never has to branch on the flags itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.observability.instrument import instrument_llm_client, instrument_node
from app.observability.metrics import record_claim_result, setup_metrics
from app.observability.tracing import setup_tracing, workflow_span

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.core.settings import AppSettings

__all__ = [
    "configure_observability",
    "workflow_span",
    "record_claim_result",
    "instrument_node",
    "instrument_llm_client",
]


def configure_observability(app: "FastAPI", settings: "AppSettings") -> None:
    """Wire up tracing and metrics according to the feature flags."""
    setup_tracing(app, settings)
    setup_metrics(app, settings)
