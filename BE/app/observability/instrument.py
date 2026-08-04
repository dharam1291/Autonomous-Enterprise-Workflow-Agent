"""Wrappers that add spans + metrics to LangGraph nodes and LLM calls.

Both wrappers are always safe to apply: when the tracing/metrics flags are off
the span is a no-op and the record helpers do nothing, so instrumenting is free.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

from app.observability.metrics import record_llm, record_node
from app.observability.tracing import workflow_span

if TYPE_CHECKING:
    from app.domain.models import ProviderConfig
    from app.graph.state import ClaimGraphState
    from app.llm.clients.base_client import LLMClient

NodeCallable = Callable[["ClaimGraphState"], "ClaimGraphState"]


def instrument_node(name: str, node: NodeCallable) -> NodeCallable:
    """Wrap a graph node so each execution emits a span and node metrics."""

    def _wrapped(state: "ClaimGraphState") -> "ClaimGraphState":
        started = time.perf_counter()
        with workflow_span(f"node.{name}", **{"workflow.node": name}):
            try:
                return node(state)
            finally:
                record_node(name, time.perf_counter() - started)

    return _wrapped


def instrument_llm_client(inner: "LLMClient") -> "LLMClient":
    """Wrap an LLM client so every provider call emits a span and LLM metrics."""
    return _InstrumentedLLMClient(inner)


class _InstrumentedLLMClient:
    """Transparent proxy adding observability around the four LLM operations."""

    def __init__(self, inner: "LLMClient") -> None:
        self._inner = inner

    def classify_document(self, text: str, config: "ProviderConfig") -> Any:
        return self._call("classify_document", config, self._inner.classify_document, text, config)

    def extract_entities(self, text: str, config: "ProviderConfig") -> Any:
        return self._call("extract_entities", config, self._inner.extract_entities, text, config)

    def draft_letter(self, state: Any, config: "ProviderConfig", letter_type: str) -> Any:
        return self._call("draft_letter", config, self._inner.draft_letter, state, config, letter_type)

    def draft_exception_summary(self, state: Any, config: "ProviderConfig") -> Any:
        return self._call("draft_exception_summary", config, self._inner.draft_exception_summary, state, config)

    def _call(self, operation: str, config: "ProviderConfig", fn: Callable[..., Any], *args: Any) -> Any:
        provider = config.llm.provider
        model = config.llm.model
        started = time.perf_counter()
        with workflow_span(
            f"llm.{operation}",
            **{"llm.provider": provider, "llm.model": model, "llm.operation": operation},
        ) as span:
            try:
                result = fn(*args)
            except Exception as exc:
                if span is not None:
                    span.record_exception(exc)
                record_llm(provider, operation, model, time.perf_counter() - started, error=True)
                raise
            record_llm(provider, operation, model, time.perf_counter() - started, error=False)
            return result
