"""Shared daily-budget and request-rate enforcement across replica pods.

Provides a Redis-backed spend counter with automatic fallback to the
existing per-pod file-based logic when Redis is unavailable.

Why Redis?
----------
The original ``_user_today_spend`` in ``ui/run_history.py`` reads JSON
files from ``LOGS_DIR``.  On a single-pod deployment this works; on
multi-replica deployments (Azure Container Apps, Kubernetes) each pod
has its own view of the filesystem unless they share a mounted volume.
Redis (or Postgres) provides a single source of truth that all pods
write to atomically, making per-user daily budget caps enforceable
cluster-wide.

Configuration
-------------
Set ``REDIS_URL`` (e.g. ``redis://my-redis:6379/0``) to enable Redis
mode.  Without it the module falls back transparently to the file-based
approach — no code changes required at call sites.

Rate limiting (request count, independent of $ cost):
  MAX_SYNTHESES_PER_HOUR  — max runs per user per rolling hour  (0 = disabled)
  MAX_SYNTHESES_PER_DAY   — max runs per user per UTC calendar day (0 = disabled)

Key schema
----------
  ``budget:<user_id>:<YYYYMMDD>``       — hash with field ``spend_usd``
  ``rate:<user_id>:h:<YYYYMMDDHH>``     — integer request count for this UTC hour
  ``rate:<user_id>:d:<YYYYMMDD>``       — integer request count for this UTC day
  TTL: 25 hours for budget keys; 2 h for hourly rate keys; 25 h for daily rate keys
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

from logger_setup import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_REDIS_URL = os.environ.get("REDIS_URL", "")
_KEY_TTL_SECONDS = 25 * 3600  # 25 h — covers UTC midnight rollovers


def _today() -> str:
    return datetime.utcnow().strftime("%Y%m%d")


def _redis_key(user_id: str, date: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in (user_id or "anonymous"))
    return f"budget:{safe}:{date}"


# ── Redis client (lazy, optional) ─────────────────────────────────────────────

_redis_client = None
_redis_available = False


def _get_redis():
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None
    if not _REDIS_URL:
        _redis_available = False
        return None
    try:
        import redis  # type: ignore[import]
        client = redis.from_url(_REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _redis_client = client
        _redis_available = True
        logger.info("Budget store: Redis connected at %s", _REDIS_URL)
        return _redis_client
    except Exception as exc:  # noqa: BLE001
        _redis_available = False
        logger.warning("Budget store: Redis unavailable (%s) — falling back to file-based", exc)
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def get_today_spend(user_id: str) -> float:
    """Return today's total spend in USD for *user_id* across all pods.

    Falls back to file-based spend if Redis is not configured.
    """
    r = _get_redis()
    if r is not None:
        try:
            key = _redis_key(user_id, _today())
            raw = r.hget(key, "spend_usd")
            return float(raw) if raw else 0.0
        except Exception as exc:  # noqa: BLE001
            logger.warning("Budget store Redis read failed (%s) — using file fallback", exc)

    # File-based fallback (single-pod only)
    from ui.run_history import _user_today_spend
    return _user_today_spend(user_id)


def record_spend(user_id: str, cost_usd: float) -> float:
    """Atomically add *cost_usd* to today's spend counter.

    Returns the new total after the increment.  This must be called
    AFTER a synthesis completes so the first run of the day always goes
    through (check-then-run avoids double-blocking legitimate first runs).
    """
    if cost_usd <= 0:
        return get_today_spend(user_id)

    r = _get_redis()
    if r is not None:
        try:
            key = _redis_key(user_id, _today())
            pipe = r.pipeline()
            pipe.hincrbyfloat(key, "spend_usd", cost_usd)
            pipe.expire(key, _KEY_TTL_SECONDS)
            results = pipe.execute()
            return float(results[0])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Budget store Redis write failed (%s) — spend not recorded to Redis", exc)

    # File-based path: spend is already recorded to disk by _save_run_to_disk;
    # return current file-based total.
    from ui.run_history import _user_today_spend
    return _user_today_spend(user_id)


def is_over_budget(user_id: str, daily_limit_usd: float) -> tuple[bool, float]:
    """Return (over_budget, current_spend).

    ``daily_limit_usd <= 0`` means no cap — always returns (False, spend).
    """
    if daily_limit_usd <= 0:
        return False, 0.0
    spend = get_today_spend(user_id)
    return spend >= daily_limit_usd, spend


# ── Atomic reserve / settle pattern ────────────────────────────────────────────
# Closes the race window where two concurrent requests both pass the budget gate
# before either records spend:
#
#   approved, new_total = try_reserve(user, estimated, limit)
#   if not approved: show error and stop
#   ... run synthesis ...
#   settle_reservation(user, actual_cost, estimated_cost)
#
# Redis path: a Lua script atomically checks (current + estimated <= limit) and
# increments in one round-trip.  File fallback: per-user threading lock.

import threading as _threading
_USER_LOCKS: dict[str, _threading.Lock] = {}
_USER_LOCKS_LOCK = _threading.Lock()


def _user_lock(user_id: str):
    with _USER_LOCKS_LOCK:
        if user_id not in _USER_LOCKS:
            _USER_LOCKS[user_id] = _threading.Lock()
        return _USER_LOCKS[user_id]


_LUA_RESERVE = """
local key   = KEYS[1]
local est   = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local ttl   = tonumber(ARGV[3])
local cur   = tonumber(redis.call('HGET', key, 'spend_usd') or '0')
if limit > 0 and cur + est > limit then
    return {0, tostring(cur)}
end
local new = tonumber(redis.call('HINCRBYFLOAT', key, 'spend_usd', est))
redis.call('EXPIRE', key, ttl)
return {1, tostring(new)}
"""


def try_reserve(
    user_id: str,
    estimated_cost_usd: float,
    daily_limit_usd: float,
) -> tuple[bool, float]:
    """Atomically check budget and reserve *estimated_cost_usd* before a run.

    Returns ``(approved, spend_after_reservation)``.
    Always call ``settle_reservation`` after the run to correct for the
    difference between estimated and actual cost.

    If ``daily_limit_usd <= 0`` the check is skipped and (True, 0.0) is
    returned — no cap configured.
    """
    if daily_limit_usd <= 0 or estimated_cost_usd <= 0:
        return True, get_today_spend(user_id)

    r = _get_redis()
    if r is not None:
        try:
            key = _redis_key(user_id, _today())
            result = r.eval(
                _LUA_RESERVE, 1, key,
                str(estimated_cost_usd),
                str(daily_limit_usd),
                str(_KEY_TTL_SECONDS),
            )
            approved = bool(int(result[0]))
            new_total = float(result[1])
            return approved, new_total
        except Exception as exc:  # noqa: BLE001
            logger.warning("Budget store Redis reserve failed (%s) — falling back", exc)

    # File-based fallback: use a per-user lock to serialise concurrent checks.
    with _user_lock(user_id):
        from ui.run_history import _user_today_spend
        current = _user_today_spend(user_id)
        if current + estimated_cost_usd > daily_limit_usd:
            return False, current
        # Record the reservation immediately so a second concurrent caller
        # sees the reserved amount when it acquires the lock.
        _record_spend_file(user_id, estimated_cost_usd)
        return True, current + estimated_cost_usd


def settle_reservation(
    user_id: str,
    actual_cost_usd: float,
    reserved_cost_usd: float,
) -> float:
    """Adjust the budget counter after a run: charge actual, refund unused reservation.

    ``delta = actual - reserved``.  Positive means the run cost more than
    estimated — charge the extra.  Negative means the run was cheaper — refund
    the difference.  Zero means the estimate was exact.
    """
    delta = actual_cost_usd - reserved_cost_usd
    if abs(delta) < 0.0001:
        return get_today_spend(user_id)  # close enough, no adjustment needed

    r = _get_redis()
    if r is not None:
        try:
            key = _redis_key(user_id, _today())
            pipe = r.pipeline()
            pipe.hincrbyfloat(key, "spend_usd", delta)
            pipe.expire(key, _KEY_TTL_SECONDS)
            results = pipe.execute()
            return float(results[0])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Budget settle Redis write failed (%s)", exc)

    # File-based: only adjust upward (refunds are silently dropped on the
    # file path because single-pod deployments don't have the double-spend risk).
    if delta > 0:
        _record_spend_file(user_id, delta)
    return get_today_spend(user_id)


def _record_spend_file(user_id: str, cost_usd: float) -> None:
    """Write a minimal spend record to the file-based store."""
    try:
        from ui.run_history import _user_runs_dir
        import json, time as _time
        runs_dir = _user_runs_dir(user_id)
        runs_dir.mkdir(parents=True, exist_ok=True)
        ts = _time.strftime("%Y%m%dT%H%M%S")
        record = {"cost_usd": cost_usd, "timestamp": ts, "source": "budget_reserve"}
        (runs_dir / f"_spend_{ts}_{id(record)}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("File-based spend record failed: %s", exc)


# ── Per-user request rate limiting ─────────────────────────────────────────────
# Tracks synthesis *count* (not cost) per user per hour and per day.
# Independent of the $ budget gate — both checks run before a run starts.

def _rate_key_hour(user_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in (user_id or "anonymous"))
    hour = datetime.utcnow().strftime("%Y%m%d%H")
    return f"rate:{safe}:h:{hour}"


def _rate_key_day(user_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in (user_id or "anonymous"))
    return f"rate:{safe}:d:{_today()}"


def _file_rate_count(user_id: str, window: str) -> int:
    """Count runs for *user_id* in the given window using run-history files.

    window: "hour" — last 60 min; "day" — current UTC calendar day.
    """
    try:
        from ui.run_history import _user_runs_dir
        import json as _json
        runs_dir = _user_runs_dir(user_id)
        if not runs_dir.exists():
            return 0
        now = datetime.utcnow()
        count = 0
        for f in runs_dir.glob("*.json"):
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                ts_str = data.get("timestamp") or ""
                if not ts_str:
                    continue
                # timestamp format: YYYYMMDD_HHMMSS or YYYYMMDDTHHMMSS
                ts_clean = ts_str.replace("_", "").replace("T", "").replace("-", "")[:14]
                ts_dt = datetime.strptime(ts_clean[:14], "%Y%m%d%H%M%S")
                if window == "hour":
                    diff = (now - ts_dt).total_seconds()
                    if 0 <= diff < 3600:
                        count += 1
                elif window == "day":
                    if ts_dt.strftime("%Y%m%d") == now.strftime("%Y%m%d"):
                        count += 1
            except Exception:  # noqa: BLE001
                continue
        return count
    except Exception as exc:  # noqa: BLE001
        logger.warning("File-based rate count failed: %s", exc)
        return 0


def get_request_counts(user_id: str) -> tuple[int, int]:
    """Return (hourly_count, daily_count) of synthesis requests for *user_id*.

    Used by the UI to display current usage vs. limit.
    """
    r = _get_redis()
    if r is not None:
        try:
            h_raw = r.get(_rate_key_hour(user_id))
            d_raw = r.get(_rate_key_day(user_id))
            return int(h_raw or 0), int(d_raw or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rate count Redis read failed (%s)", exc)
    return _file_rate_count(user_id, "hour"), _file_rate_count(user_id, "day")


def check_rate_limit(
    user_id: str,
    max_per_hour: int,
    max_per_day: int,
) -> tuple[bool, str]:
    """Check whether *user_id* is within their request rate limits.

    Returns ``(allowed, reason)``.
    ``reason`` is an empty string when allowed.
    Either limit ≤ 0 means that window is disabled.
    """
    if max_per_hour <= 0 and max_per_day <= 0:
        return True, ""

    hourly, daily = get_request_counts(user_id)

    if max_per_hour > 0 and hourly >= max_per_hour:
        return False, (
            f"Hourly limit reached — you have made **{hourly}** synthesis request(s) "
            f"in the last hour (limit: {max_per_hour}). Please wait before trying again."
        )
    if max_per_day > 0 and daily >= max_per_day:
        return False, (
            f"Daily limit reached — you have made **{daily}** synthesis request(s) "
            f"today (limit: {max_per_day}). Try again tomorrow."
        )
    return True, ""


def increment_request_count(user_id: str) -> tuple[int, int]:
    """Increment hourly and daily request counters after a successful run.

    Returns the new ``(hourly_count, daily_count)``.
    """
    r = _get_redis()
    if r is not None:
        try:
            h_key = _rate_key_hour(user_id)
            d_key = _rate_key_day(user_id)
            pipe = r.pipeline()
            pipe.incr(h_key)
            pipe.expire(h_key, 2 * 3600)      # 2-hour TTL — covers the full rolling hour
            pipe.incr(d_key)
            pipe.expire(d_key, _KEY_TTL_SECONDS)
            results = pipe.execute()
            return int(results[0]), int(results[2])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rate increment Redis write failed (%s)", exc)
    # File-based: counts are derived from run-history files — no explicit write needed.
    return _file_rate_count(user_id, "hour") + 1, _file_rate_count(user_id, "day") + 1
