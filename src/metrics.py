"""Prometheus metrics for Backlog Synthesizer.

Exposes a /metrics HTTP endpoint on METRICS_PORT (default 9090) in a
background daemon thread, independent of Streamlit on port 8502.

Metrics
-------
backlog_syntheses_total{status}         Counter  success / failure / cancelled
backlog_synthesis_duration_seconds      Histogram wall-clock time per run
backlog_synthesis_cost_usd              Histogram LLM spend per run (USD)
backlog_tokens_total{model,direction}   Counter  input / output token counts
backlog_llm_errors_total{provider}      Counter  API errors by provider
backlog_active_synthesis                Gauge    1 while a run is in progress

Usage
-----
    from metrics import start_metrics_server, record_synthesis_start, record_synthesis_end

    start_metrics_server()          # call once at Streamlit startup

    record_synthesis_start()
    try:
        ...
        record_synthesis_end("success", elapsed, cost_usd, token_usage, model)
    except Exception:
        record_synthesis_end("failure", elapsed)

All functions are no-ops if prometheus-client is not installed so the app
still starts cleanly in environments without Prometheus infrastructure.
"""

from __future__ import annotations

import os
import threading
from typing import Any

_METRICS_PORT = int(os.environ.get("METRICS_PORT", "9090"))

# ── Try to import prometheus_client ──────────────────────────────────────────
try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        start_http_server as _start_http_server,
    )
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_server_lock = threading.Lock()
_server_started = False


def _get_or_create(metric_cls, name: str, doc: str, *args, **kwargs):
    """Return an existing Prometheus metric or create a new one.

    The Prometheus REGISTRY is a process-level singleton. When Streamlit
    hot-reloads this module (re-executes without restarting the process),
    each metric constructor raises ValueError because the name is already
    registered.  This helper catches that and returns the existing collector
    so all call-sites continue to work without interruption.
    """
    try:
        return metric_cls(name, doc, *args, **kwargs)
    except ValueError:
        # Already registered — find and return the existing collector.
        # Counters: registry key is "<name>_total"; Histograms/Gauges: "<name>".
        from prometheus_client import REGISTRY
        for candidate in (name + "_total", name):
            existing = REGISTRY._names_to_collectors.get(candidate)
            if existing is not None:
                return existing
        raise  # genuine duplicate with different labels — re-raise


# ── Metric definitions ────────────────────────────────────────────────────────
if _AVAILABLE:
    SYNTHESES_TOTAL = _get_or_create(
        Counter,
        "backlog_syntheses_total",
        "Total synthesis runs by final status (success/failure/cancelled)",
        ["status"],
    )
    SYNTHESIS_DURATION = _get_or_create(
        Histogram,
        "backlog_synthesis_duration_seconds",
        "Wall-clock time per synthesis run",
        buckets=[15, 30, 60, 90, 120, 180, 300, 600],
    )
    SYNTHESIS_COST = _get_or_create(
        Histogram,
        "backlog_synthesis_cost_usd",
        "LLM API spend per synthesis run (USD)",
        buckets=[0.01, 0.05, 0.10, 0.25, 0.50, 1.00, 2.00, 5.00],
    )
    TOKENS_TOTAL = _get_or_create(
        Counter,
        "backlog_tokens_total",
        "Cumulative LLM tokens consumed",
        ["model", "direction"],   # direction: input | output
    )
    LLM_ERRORS_TOTAL = _get_or_create(
        Counter,
        "backlog_llm_errors_total",
        "LLM API errors by provider",
        ["provider"],             # anthropic | google | unknown
    )
    ACTIVE_SYNTHESIS = _get_or_create(
        Gauge,
        "backlog_active_synthesis",
        "1 while a synthesis pipeline is running, 0 otherwise",
    )
    # Circuit-breaker state per LLM provider.
    # Values: 0 = CLOSED (healthy), 1 = OPEN (rejecting), 2 = HALF_OPEN (probing).
    # Allows Prometheus alert rules like:
    #   alert: LLMProviderDown
    #   expr:  backlog_circuit_breaker_state{provider="anthropic"} == 1
    CB_STATE = _get_or_create(
        Gauge,
        "backlog_circuit_breaker_state",
        "Circuit breaker state per LLM provider (0=CLOSED 1=OPEN 2=HALF_OPEN)",
        ["provider"],
    )


# ── Public API ────────────────────────────────────────────────────────────────

def start_metrics_server() -> None:
    """Start the Prometheus HTTP server on METRICS_PORT (idempotent)."""
    global _server_started
    if not _AVAILABLE:
        return
    with _server_lock:
        if _server_started:
            return
        try:
            _start_http_server(_METRICS_PORT)
            _server_started = True
        except OSError:
            pass  # port already bound (e.g. reloaded module) — not fatal


def record_synthesis_start() -> None:
    """Mark a synthesis as in-progress."""
    if _AVAILABLE:
        ACTIVE_SYNTHESIS.set(1)


def record_synthesis_end(
    status: str,
    elapsed_seconds: float,
    cost_usd: float = 0.0,
    token_usage: dict[str, Any] | None = None,
    model: str = "",
) -> None:
    """Record the outcome of a completed synthesis run.

    Args:
        status:          "success", "failure", or "cancelled"
        elapsed_seconds: wall-clock time from start to finish
        cost_usd:        estimated LLM spend (0 if unknown)
        token_usage:     dict with "total": {"input": N, "output": N}
        model:           primary model name used in the run
    """
    if not _AVAILABLE:
        return
    ACTIVE_SYNTHESIS.set(0)
    SYNTHESES_TOTAL.labels(status=status).inc()
    SYNTHESIS_DURATION.observe(elapsed_seconds)
    if status == "success" and cost_usd > 0:
        SYNTHESIS_COST.observe(cost_usd)
    if token_usage:
        _record_tokens(token_usage, model)


def record_llm_error(provider: str = "unknown") -> None:
    """Increment the LLM error counter for the given provider."""
    if _AVAILABLE:
        LLM_ERRORS_TOTAL.labels(provider=provider.lower()).inc()


def record_circuit_breaker_state(provider: str, state_value: int) -> None:
    """Update the circuit breaker state gauge for *provider*.

    state_value: 0 = CLOSED, 1 = OPEN, 2 = HALF_OPEN.
    Called by CircuitBreaker.record_success() and record_failure().
    """
    if _AVAILABLE:
        CB_STATE.labels(provider=provider.lower()).set(state_value)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _record_tokens(token_usage: dict[str, Any], model: str) -> None:
    total = token_usage.get("total") or {}
    label = model or "unknown"
    inp = int(total.get("input", 0) or 0)
    out = int(total.get("output", 0) or 0)
    if inp:
        TOKENS_TOTAL.labels(model=label, direction="input").inc(inp)
    if out:
        TOKENS_TOTAL.labels(model=label, direction="output").inc(out)
