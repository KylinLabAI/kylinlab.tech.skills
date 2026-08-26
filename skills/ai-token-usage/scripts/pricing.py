"""Pricing lookup and cost estimation for the ai-token-usage skill.

Reads the saved price table at ``references/pricing.json`` (refreshed by
``scripts/fetch_pricing.py``) and estimates USD cost from token counts. No
network access here — the report path stays offline.

Model matching is case-insensitive and falls back to:
  * ``*free*`` model names            -> $0 (free tiers)
  * longest substring match in table -> that model's rates
  * no match                         -> cost is None (unknown)
"""

from __future__ import annotations

import json
import os
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_PRICING_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "references", "pricing.json")
)

_MAYBE_FLOAT = (int, float)


def _load() -> dict[str, Any]:
    try:
        with open(_PRICING_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"models": {}, "currency": "USD"}


_DATA = _load()
_MODELS = _DATA.get("models", {})
_CURRENCY = _DATA.get("currency", "USD")
_FX_USD_CNY = float((_DATA.get("fx") or {}).get("USD_CNY", 7.1))
_DISPLAY = "USD"  # "USD" or "CNY"


def set_currency(cur: str) -> None:
    """Set the report display currency. Accepts USD, CNY, or RMB (==CNY)."""
    global _DISPLAY
    c = (cur or "USD").upper()
    if c == "RMB":
        c = "CNY"
    if c not in ("USD", "CNY"):
        c = "USD"
    _DISPLAY = c


def fx_rate() -> float:
    """Return how many CNY per 1 USD."""
    return _FX_USD_CNY


def to_display(usd_amount: float) -> float:
    """Convert a USD amount into the currently selected display currency."""
    if _DISPLAY == "CNY":
        return float(usd_amount) * _FX_USD_CNY
    return float(usd_amount)


def cost_symbol() -> str:
    return "¥" if _DISPLAY == "CNY" else "$"


def cost_label() -> str:
    return "CNY" if _DISPLAY == "CNY" else "USD"


def fmt_cost(usd_amount: float) -> str:
    """Format a USD amount as a string in the selected display currency."""
    if usd_amount is None:
        return "n/a"
    return f"{cost_symbol()}{to_display(usd_amount):,.2f}"

def _norm(name: str) -> str:
    return (name or "").lower().strip()


# When True, free-tier models are priced at $0 (for a "billable only" view).
# Default False: free-tier models are priced at their paid base rate so usage
# assessment reflects real cost even for free promotions.
EXCLUDE_FREE = False


def set_exclude_free(value: bool) -> None:
    global EXCLUDE_FREE
    EXCLUDE_FREE = bool(value)


def lookup(model: str) -> dict[str, Any] | None:
    """Return the price entry dict for ``model``, or None if unknown."""
    name = _norm(model)
    if not name:
        return None

    if name in _MODELS:
        return dict(_MODELS[name], _key=name)
    if "free" in name:
        # Free-tier model: price it at its paid base rate by default so usage
        # assessment reflects real cost (e.g. "deepseek-v4-flash-free" ->
        # "deepseek-v4-flash"). Strip the "free" suffix to find the base.
        base = name.replace("free", "").strip("-_")
        base_key = base if base in _MODELS else None
        if base_key is None:
            # fall back to longest-substring match on the stripped base name
            best = None
            bl = 0
            for k in _MODELS:
                kl = _norm(k)
                if kl and kl in base and len(kl) > bl:
                    bl = len(kl)
                    best = k
            base_key = best
        if base_key is not None:
            entry = dict(_MODELS[base_key], _key=base_key, free=True, free_tier=True)
        else:
            entry = {"input": 0.0, "output": 0.0, "free": True, "_key": name}
        if EXCLUDE_FREE:
            entry = {**entry, "input": 0.0, "output": 0.0, "cache_read": 0.0, "free": True}
        return entry
    # Longest substring match (e.g. "z-ai/glm-5.2" -> "glm-5.2").
    best_key = None
    best_len = 0
    for key in _MODELS:
        kl = _norm(key)
        if kl and kl in name and len(kl) > best_len:
            best_len = len(kl)
            best_key = key
    if best_key:
        return dict(_MODELS[best_key], _key=best_key)
    return None


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
) -> float | None:
    """Estimate USD cost for ``model`` given token counts. None if unknown.

    ``input_tokens`` is assumed to already include any cached tokens (as the
    report's token totals do). Cached tokens are priced at the cheaper
    ``cache_read`` rate when the model defines one; otherwise they are priced
    at the standard input rate.
    """
    entry = lookup(model)
    if not entry:
        return None
    rate_in = entry.get("input")
    rate_out = entry.get("output")
    if rate_in is None or rate_out is None:
        return None  # subscription / no per-token price
    rate_in = float(rate_in)
    rate_out = float(rate_out)
    rate_cache = entry.get("cache_read")
    rate_cache = float(rate_cache) if rate_cache is not None else rate_in

    cache_read_tokens = int(cache_read_tokens or 0)
    standard_input = max(0, int(input_tokens or 0) - cache_read_tokens)
    cost = (standard_input / 1_000_000) * rate_in + \
           (cache_read_tokens / 1_000_000) * rate_cache + \
           (int(output_tokens or 0) / 1_000_000) * rate_out
    return round(cost, 6)


def currency() -> str:
    return _CURRENCY
