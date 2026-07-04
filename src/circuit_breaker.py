"""Thread-safe circuit breaker for LLM provider calls.

States
------
CLOSED    — normal; calls go through.
OPEN      — fast-failing; calls are immediately redirected/rejected.
HALF_OPEN — one probe call is allowed to test recovery; success → CLOSED,
            failure → OPEN with a refreshed timeout.

Environment variables
---------------------
CB_FAILURE_THRESHOLD   int  default 3   failures before tripping to OPEN
CB_RECOVERY_TIMEOUT_SEC float default 60  seconds before a probe is tried
"""
from __future__ import annotations

import os
import threading
import time
from enum import Enum

from logger_setup import get_logger

logger = get_logger(__name__)

# State values for the Prometheus gauge.
_CB_GAUGE_CLOSED    = 0
_CB_GAUGE_OPEN      = 1
_CB_GAUGE_HALF_OPEN = 2


def _emit_state(provider: str, value: int) -> None:
    """Update the circuit-breaker Prometheus gauge (best-effort, never raises)."""
    try:
        from metrics import record_circuit_breaker_state
        record_circuit_breaker_state(provider, value)
    except Exception:  # noqa: BLE001
        pass

_FAILURE_THRESHOLD = int(os.environ.get("CB_FAILURE_THRESHOLD", "5"))
_RECOVERY_TIMEOUT  = float(os.environ.get("CB_RECOVERY_TIMEOUT_SEC", "60"))


class CBState(Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-provider circuit breaker."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = _FAILURE_THRESHOLD,
        recovery_timeout: float = _RECOVERY_TIMEOUT,
    ) -> None:
        self.name               = name
        self._threshold         = failure_threshold
        self._timeout           = recovery_timeout
        self._failures          = 0
        self._opened_at: float | None = None
        self._probe_in_flight   = False
        self._lock              = threading.Lock()

    # ------------------------------------------------------------------ state

    @property
    def state(self) -> CBState:
        with self._lock:
            return self._state_unlocked()

    def _state_unlocked(self) -> CBState:
        if self._opened_at is None:
            return CBState.CLOSED
        if time.monotonic() - self._opened_at >= self._timeout:
            return CBState.HALF_OPEN
        return CBState.OPEN

    def is_open(self) -> bool:
        """Return True when the caller should fast-fail or redirect.

        In HALF_OPEN state the first caller gets False (probe allowed); all
        concurrent callers get True until the probe resolves.
        """
        with self._lock:
            s = self._state_unlocked()
            if s == CBState.OPEN:
                return True
            if s == CBState.HALF_OPEN:
                if self._probe_in_flight:
                    return True
                self._probe_in_flight = True  # allow exactly one probe
                _emit_state(self.name, _CB_GAUGE_HALF_OPEN)
                return False
            return False

    # ------------------------------------------------------------------ signals

    def record_success(self) -> None:
        with self._lock:
            prev = self._state_unlocked()
            self._failures        = 0
            self._opened_at       = None
            self._probe_in_flight = False
            if prev != CBState.CLOSED:
                logger.info("Circuit breaker CLOSED for %s (recovered)", self.name)
        _emit_state(self.name, _CB_GAUGE_CLOSED)

    def record_failure(self) -> None:
        new_state_value = _CB_GAUGE_CLOSED
        with self._lock:
            self._probe_in_flight = False
            self._failures += 1
            if self._failures >= self._threshold:
                was_closed = self._opened_at is None
                self._opened_at = time.monotonic()  # refresh on repeated failures
                new_state_value = _CB_GAUGE_OPEN
                if was_closed:
                    logger.warning(
                        "Circuit breaker OPEN for %s after %d consecutive failure(s). "
                        "Will retry in %.0fs.",
                        self.name, self._failures, self._timeout,
                    )
        _emit_state(self.name, new_state_value)


# Module-level singletons — shared across all pipeline invocations in the process.
CLAUDE_CB = CircuitBreaker("anthropic")
GEMINI_CB = CircuitBreaker("google")
