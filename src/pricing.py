"""Per-million-token pricing for LLM models (Claude + Gemini).

Numbers reflect each provider's published list prices as of late 2025.
They're hardcoded here because:
  - The pricing endpoints aren't stable public APIs.
  - The UI cost panel is labeled "estimate" — small drift between list
    price and a customer's actual bill is acceptable.
  - Keeping it local means cost rendering works offline.

To add a model, add an entry to `MODEL_PRICES` keyed by the leading prefix
of the model ID (e.g. "claude-sonnet-4-5"). `estimate_cost_usd()` does a
longest-prefix match so e.g. "claude-sonnet-4-5-20250930" matches the
"claude-sonnet-4-5" entry.

Free-tier convention:
    Gemini's AI Studio free tier currently charges $0 for `gemini-2.5-flash`
    and `gemini-2.5-flash-lite` usage up to its daily quota. We deliberately
    list the PAID-tier rates here so the cost panel reflects list price
    (the published number the user would pay outside free tier). The UI
    tags Gemini models with "(free tier eligible)" so the user knows the
    actual bill on AI Studio's free tier is $0. This matches V2's convention.
"""

from __future__ import annotations

# Prices are USD per 1 million tokens: {"input": <price>, "output": <price>}
MODEL_PRICES: dict[str, dict[str, float]] = {
    # Claude
    "claude-sonnet-4-5":   {"input": 3.0,   "output": 15.0},
    "claude-sonnet-4":     {"input": 3.0,   "output": 15.0},
    "claude-3-5-sonnet":   {"input": 3.0,   "output": 15.0},
    "claude-3-7-sonnet":   {"input": 3.0,   "output": 15.0},
    "claude-opus-4-5":     {"input": 75.0,  "output": 75.0},
    "claude-opus-4":       {"input": 75.0,  "output": 75.0},
    "claude-3-opus":       {"input": 75.0,  "output": 75.0},
    "claude-haiku-4-5":    {"input": 1.0,   "output": 5.0},
    "claude-3-5-haiku":    {"input": 0.8,   "output": 4.0},
    "claude-3-haiku":      {"input": 0.25,  "output": 1.25},
    # Gemini
    "gemini-2.5-flash-lite": {"input": 0.1,  "output": 0.4},
    "gemini-2.5-flash":    {"input": 0.3,   "output": 2.5},
    "gemini-2.5-pro":      {"input": 10.0,  "output": 10.0},
    "gemini-2.0-flash":    {"input": 0.1,   "output": 0.4},
    "gemini-1.5-flash":    {"input": 0.075, "output": 0.3},
    "gemini-1.5-pro":      {"input": 2.5,   "output": 10.0},
}

FREE_TIER_MODELS: set[str] = frozenset({
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
})


def is_free_tier_eligible(model: str) -> bool:
    """True when `model` is on a provider's free tier (longest-prefix match)."""
    model_lower = model.lower()
    for key in FREE_TIER_MODELS:
        if model_lower.startswith(key):
            return True
    return False


def _lookup(model: str) -> dict[str, float] | None:
    """Longest-prefix match against MODEL_PRICES, case-insensitive."""
    model_lower = model.lower()
    best_key = None
    best_len = -1
    for key in MODEL_PRICES:
        if model_lower.startswith(key) and len(key) > best_len:
            best_key = key
            best_len = len(key)
    return MODEL_PRICES[best_key] if best_key is not None else None


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """Return the estimated USD cost for `input_tokens` + `output_tokens` on `model`.

    Returns None when the model isn't in the price table — the caller should
    render "no price entry" rather than $0.00 so it's obvious the number is
    missing, not zero.
    """
    prices = _lookup(model)
    if prices is None:
        return None
    return (
        input_tokens  / 1_000_000 * prices["input"]
        + output_tokens / 1_000_000 * prices["output"]
    )
