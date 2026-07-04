"""OpenTelemetry tracing helpers.

Provides a ``child_span()`` context manager used by each LLM tool to emit
per-call spans. When ``OTEL_ENABLED`` is not "1" (the default), all calls
return a no-op span so the tools work correctly in environments without an
OTLP collector.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any


class _NoopSpan:
    """Stand-in for an OpenTelemetry Span when OTEL is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ARG002
        pass

    def record_exception(self, exc: Exception, **_kwargs: Any) -> None:
        pass

    def set_status(self, *_args: Any, **_kwargs: Any) -> None:
        pass


@contextlib.contextmanager
def child_span(name: str, **attributes: Any):
    """Create a child OpenTelemetry span, or a no-op if OTEL is disabled.

    Usage::

        with child_span("llm.call", llm_model="claude-haiku-4-5") as span:
            response = llm.invoke(messages)
            span.set_attribute("llm.tokens", response_tokens)
    """
    if os.environ.get("OTEL_ENABLED", "0") != "1":
        span = _NoopSpan()
        yield span
        return

    try:
        from opentelemetry import trace as _trace

        tracer = _trace.get_tracer(__name__)
        with tracer.start_as_current_span(name) as span:
            for k, v in attributes.items():
                span.set_attribute(k, v)
            yield span
    except Exception:  # noqa: BLE001 — never crash a run over telemetry
        yield _NoopSpan()


@contextlib.contextmanager
def pipeline_node_span(node_name: str, run_id: str = "", **attributes: Any):
    """OTel span for a single LangGraph pipeline node.

    Creates a span named ``pipeline.node.<node_name>`` that:
    - carries ``pipeline.node`` and ``pipeline.run_id`` as standard attributes
    - records any raised exception and marks the span ERROR so traces show
      exactly which node failed and with what error
    - is a true child of any parent span already on the context (e.g. a root
      ``pipeline.run`` span from the orchestrator)

    No-op when ``OTEL_ENABLED`` is not "1", so adding spans has zero overhead
    in environments without an OTLP collector.

    Usage (applied via _node_with_span wrapper in pipeline.py — not called directly)::

        with pipeline_node_span("parse", run_id=run_id) as span:
            result = parse_node(state, config)
            span.set_attribute("output.topics_count", len(result.get("topics", [])))
    """
    if os.environ.get("OTEL_ENABLED", "0") != "1":
        yield _NoopSpan()
        return

    try:
        from opentelemetry import trace as _trace
        from opentelemetry.trace import StatusCode

        tracer = _trace.get_tracer("backlog_synthesizer.pipeline")
        with tracer.start_as_current_span(f"pipeline.node.{node_name}") as span:
            span.set_attribute("pipeline.node", node_name)
            if run_id:
                span.set_attribute("pipeline.run_id", run_id)
            for k, v in attributes.items():
                span.set_attribute(k, v)
            try:
                yield span
                span.set_status(StatusCode.OK)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, description=str(exc)[:200])
                raise
    except Exception:  # noqa: BLE001 — never crash a run over telemetry
        yield _NoopSpan()
