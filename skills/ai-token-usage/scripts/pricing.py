"""Pricing lookup and cost estimation for the ai-token-usage skill.

Reads the saved price table at ``references/pricing.json`` (refreshed by
``scripts/fetch_pricing.py``) and estimates USD cost from token counts. No
network access here — the report path stays offline.

Model matching is case-insensitive and resolves in this order:
  * exact key in ``pricing.json``      -> that model's rates
  * ``*free*`` token in the name       -> the same model without the free
                                          token (e.g. ``deepseek-v4-flash-free``
                                          -> ``deepseek-v4-flash`` rates)
  * longest substring match in table   -> that model's rates
  * no match (unknown model)           -> the ``fallback`` entry's rates
                                          (``auto`` by default)

Nothing is silently priced at $0: a model that cannot be resolved falls back to
the ``auto`` rates so its usage still contributes to the cost estimate.
"""

from __future__ import annotations

import json
import os
import re
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

# Table key used to price models that are not in the price table at all
# (unknown model names, and `*free*` names whose base model is also unknown).
# Override by setting a top-level "fallback" key in references/pricing.json.
FALLBACK_KEY = str(_DATA.get("fallback") or "auto")

# Model names that had to be priced with the fallback entry during this run.
_FALLBACK_HITS: set[str] = set()


def fallback_models() -> list[str]:
    """Return sorted model names priced with the fallback entry so far."""
    return sorted(_FALLBACK_HITS)


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
# Default False: free-tier models are priced at their base model's rate so
# usage assessment reflects real cost even for free promotions.
EXCLUDE_FREE = False


def set_exclude_free(value: bool) -> None:
    global EXCLUDE_FREE
    EXCLUDE_FREE = bool(value)


# "free" counts as a free-tier marker only when it is a standalone token, so
# names such as "freedom-model" are not mangled.
_FREE_TOKEN_RE = re.compile(r"(^|[-_./\s])free([-_./\s]|$)")


def _is_free_name(name: str) -> bool:
    return bool(_FREE_TOKEN_RE.search(name or ""))


def _free_base_candidates(name: str) -> list[str]:
    """Candidate base names for a free-tier model, e.g. "deepseek-v4-flash-free".

    Returns e.g. ["deepseek-v4-flash"]; for vendor-prefixed names such as
    "z-ai/glm-4.7-flash-free" it also returns the bare "glm-4.7-flash".
    """
    base = re.sub(r"[-_.\s]*free[-_.\s]*", "-", name).strip("-_./ ")
    cands: list[str] = []
    for cand in (base, base.split("/")[-1]):
        c = _norm(cand).strip("-_./ ")
        if c and c != _norm(name) and c not in cands:
            cands.append(c)
    return cands


def _substring_match(name: str) -> str | None:
    """Longest table key contained in ``name`` (e.g. "z-ai/glm-5.2" -> "glm-5.2")."""
    best_key = None
    best_len = 0
    for key in _MODELS:
        kl = _norm(key)
        if kl and kl in name and len(kl) > best_len:
            best_len = len(kl)
            best_key = key
    return best_key


def _zero_out(entry: dict[str, Any]) -> dict[str, Any]:
    return {**entry, "input": 0.0, "output": 0.0, "cache_read": 0.0, "free": True}


def _fallback_entry(name: str, **tags: Any) -> dict[str, Any] | None:
    """Price entry for unknown models (the ``fallback`` / ``auto`` rates)."""
    key = _norm(FALLBACK_KEY)
    entry = _MODELS.get(key)
    if entry is None or entry.get("input") is None or entry.get("output") is None:
        return None
    if not EXCLUDE_FREE:  # with --exclude-free the fallback rate is zeroed out
        _FALLBACK_HITS.add(name)
    return dict(entry, _key=key, unknown=True, priced_from=key, **tags)


def lookup(model: str) -> dict[str, Any] | None:
    """Return the price entry dict for ``model``.

    Resolution order: exact key -> free-tier base model -> longest substring
    match -> the ``fallback`` (``auto``) entry. Returns None only when the
    fallback entry itself is missing or has no per-token rates (e.g. the
    subscription-based ``copilot`` entry matched exactly).
    """
    name = _norm(model)
    if not name:
        return None

    # 1. Exact key in the price table.
    if name in _MODELS:
        entry = dict(_MODELS[name], _key=name)
        priced_as = _norm(str(entry.get("priced_as") or ""))
        if priced_as and priced_as in _MODELS:
            src = priced_as
            entry = dict(
                _MODELS[src], _key=name, priced_from=src,
                free=True, free_tier=bool(entry.get("free")),
            )
        if EXCLUDE_FREE and (entry.get("free") or entry.get("free_tier")):
            entry = _zero_out(entry)
        return entry

    # 2. Free-tier model: price it at the same model's non-free rates.
    if _is_free_name(name):
        base_key = None
        for cand in _free_base_candidates(name):
            if cand in _MODELS:
                base_key = cand
                break
            base_key = _substring_match(cand)
            if base_key:
                break
        if base_key:
            entry = dict(
                _MODELS[base_key], _key=name, priced_from=base_key,
                free=True, free_tier=True,
            )
        else:
            # Free-tier model with no priceable base: fall back to `auto`
            # instead of silently costing $0.
            entry = _fallback_entry(name, free=True, free_tier=True) or {
                "input": 0.0, "output": 0.0, "cache_read": 0.0,
                "free": True, "_key": name,
            }
        if EXCLUDE_FREE:
            entry = _zero_out(entry)
        return entry

    # 3. Longest substring match (e.g. "z-ai/glm-5.2" -> "glm-5.2").
    best_key = _substring_match(name)
    if best_key:
        return dict(_MODELS[best_key], _key=best_key, priced_from=best_key)

    # 4. Unknown model -> fallback ("auto") rates.
    return _fallback_entry(name)


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
) -> float | None:
    """Estimate USD cost for ``model`` given token counts.

    Returns None only when no rate applies at all — i.e. an exact table entry
    without per-token prices (the ``copilot`` subscription) or a missing
    ``fallback`` entry. Unknown models are priced at the fallback (``auto``)
    rates rather than $0; use ``fallback_models()`` to see which ones were.

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
