#!/usr/bin/env python3
"""Refresh the saved AI model price table used by the ai-token-usage skill.

This script is the ONLY place that talks to the network. It writes
``references/pricing.json`` — a snapshot of per-model prices (USD per 1M
tokens) sourced from each provider's official pricing page. The report
(``ai_token_usage.py``) reads that file and never fetches live, so refreshing
is a separate, schedulable maintenance step.

Recommended cadence: run monthly, e.g. via cron:

    0 9 1 * * cd /path/to/skills/ai-token-usage && python3 scripts/fetch_pricing.py

What it does
------------
1. Starts from ``EMBEDDED_PRICING`` — a curated table verified against the
   official pages (see ``sources``), used as the reliable baseline.
2. Best-effort live-enriches DeepSeek from its official docs page (plain
   HTML). Other providers' pages are JS/anti-bot protected, so their rows
   stay curated but are clearly attributed with source URLs and a fetch date.
3. Writes ``references/pricing.json`` with an updated ``fetched`` timestamp.

Flags
-----
    --dry-run   Print the resulting table; do not write the file.
    --check     Exit non-zero if the saved file is older than --max-age days
                (default 35). Useful as a CI/scheduled freshness guard.
    --max-age N Days before --check warns (default 35).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.normpath(os.path.join(HERE, "..", "references"))
PRICING_PATH = os.path.join(REF_DIR, "pricing.json")

SOURCES = {
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing",
    "zhipu_glm": "https://docs.z.ai/guides/overview/pricing",
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "openai": "https://openai.com/api/pricing",
    "copilot": "https://github.com/features/copilot/plans",
    "fx": "https://open.er-api.com/v6/latest/USD",
}

# 1 USD = this many CNY. Embedded fallback; refreshed live when reachable.
EMBEDDED_FX_USD_CNY = 7.1

# Curated, official-rate baseline (USD per 1M tokens, standard/peak list rate).
# Verified 2026-08-26 from the SOURCES above. Live refresh best-effort overrides
# DeepSeek rows; everything else is refreshed by re-running this script monthly.
EMBEDDED_PRICING = {
    "deepseek-v4-flash": {
        "input": 0.44, "output": 1.32, "cache_read": 0.014,
        "input_cache_miss": 0.44, "source": "deepseek",
        "note": "Peak rates; off-peak is half. Cache-hit input $0.014/M.",
    },
    "deepseek-v4-pro": {
        "input": 1.32, "output": 3.96, "cache_read": 0.044,
        "input_cache_miss": 1.32, "source": "deepseek",
        "note": "Peak rates; off-peak is half.",
    },
    "deepseek-v4-flash-vision-exp": {
        "input": 0.44, "output": 1.32, "cache_read": 0.014,
        "input_cache_miss": 0.44, "source": "deepseek",
    },
    # Placeholder for unknown router models (e.g. Copilot "Auto"). The client
    # only logs "Auto"; the real model is resolved server-side and unknown.
    # Defaults to deepseek-v4-flash rates — reconfigure freely if you know the
    # typical model Auto routes to.
    "auto": {"input": 0.44, "cache_read": 0.014, "output": 1.32,
             "source": "placeholder",
             "note": "Router 'Auto' model; defaults to deepseek-v4-flash rates. Edit to match your assumed model."},
    # Z.ai GLM text models — official rates from docs.z.ai/guides/overview/pricing
    # (columns: input | cached input = cache_read | storage free | output, USD / 1M).
    "glm-5.3": {"input": 1.4, "cache_read": 0.26, "output": 4.4, "source": "zhipu_glm"},
    "glm-5.2": {"input": 1.4, "cache_read": 0.26, "output": 4.4, "source": "zhipu_glm",
                "note": "Z.ai standard rate (z-ai/glm-5.2)."},
    "z-ai/glm-5.2": {"input": 1.4, "cache_read": 0.26, "output": 4.4, "source": "zhipu_glm",
                     "note": "Alias of glm-5.2."},
    "glm-5.1": {"input": 1.4, "cache_read": 0.26, "output": 4.4, "source": "zhipu_glm"},
    "glm-5": {"input": 1.0, "cache_read": 0.2, "output": 3.2, "source": "zhipu_glm"},
    "glm-5-turbo": {"input": 1.2, "cache_read": 0.24, "output": 4.0, "source": "zhipu_glm"},
    "glm-4.7": {"input": 0.6, "cache_read": 0.11, "output": 2.2, "source": "zhipu_glm"},
    "glm-4.7-flashx": {"input": 0.07, "cache_read": 0.01, "output": 0.4, "source": "zhipu_glm"},
    "glm-4.6": {"input": 0.6, "cache_read": 0.11, "output": 2.2, "source": "zhipu_glm"},
    "glm-4.5": {"input": 0.6, "cache_read": 0.11, "output": 2.2, "source": "zhipu_glm"},
    "glm-4.5-x": {"input": 2.2, "cache_read": 0.45, "output": 8.9, "source": "zhipu_glm"},
    "glm-4.5-air": {"input": 0.2, "cache_read": 0.03, "output": 1.1, "source": "zhipu_glm"},
    "glm-4.5-airx": {"input": 1.1, "cache_read": 0.22, "output": 4.5, "source": "zhipu_glm"},
    "glm-4-32b-0414-128k": {"input": 0.1, "output": 0.1, "source": "zhipu_glm"},
    "glm-4.7-flash": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "source": "zhipu_glm", "free": True},
    "glm-4.5-flash": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "source": "zhipu_glm", "free": True},
    # Tencent Cloud TokenHub text models — RMB rates from
    # cloud.tencent.com/document/product/1823/130055, converted to USD via fx
    # so the RMB display round-trips exactly. (TokenHub is a reseller, so these
    # differ from the direct Z.ai/DeepSeek list rates.)
    "hy3": {"input": 0.14843, "cache_read": 0.03711, "output": 0.59373, "source": "tencent_tokhub",
            "note": "TokenHub Hy3: RMB 1 / 4 / 0.25 per 1M (input/output/cache)."},
    "mimo-v2.5": {"input": 0.44517, "cache_read": 0.00371, "output": 0.89033, "source": "tencent_tokhub",
                  "note": "TokenHub MiMo-V2.5-Pro: RMB 3 / 6 / 0.025 per 1M (input/output/cache)."},
    "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "source": "anthropic"},
    "claude-opus-4.6": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "source": "anthropic"},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "source": "anthropic"},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "source": "anthropic"},
    "claude-haiku-4.5": {"input": 1.0, "output": 5.0, "cache_read": 0.1, "source": "anthropic"},
    "gpt-5": {"input": 1.25, "output": 10.0, "cache_read": 0.125, "source": "openai"},
    "gpt-5-mini": {"input": 0.25, "output": 2.0, "cache_read": 0.025, "source": "openai"},
    "gpt-5-nano": {"input": 0.05, "output": 0.4, "cache_read": 0.005, "source": "openai"},
    "gpt-4.1": {"input": 2.0, "output": 8.0, "cache_read": 0.5, "source": "openai"},
    "gpt-4.1-mini": {"input": 0.4, "output": 1.6, "cache_read": 0.1, "source": "openai"},
    "gpt-4.1-nano": {"input": 0.1, "output": 0.4, "cache_read": 0.025, "source": "openai"},
    "o4-mini": {"input": 1.1, "output": 4.4, "cache_read": 0.275, "source": "openai"},
    "o3": {"input": 2.0, "output": 8.0, "cache_read": 0.5, "source": "openai"},
    "gpt-5.3-codex": {
        "input": 1.75, "output": 14.0, "cache_read": 0.175,
        "source": "openai", "note": "Codex model.",
    },
    "copilot": {
        "subscription": True, "input": None, "output": None, "source": "copilot",
        "note": "GitHub Copilot is billed by subscription, not per token.",
    },
}


def _sane_deepseek(entry: dict) -> bool:
    """Reject obviously-wrong live parses (e.g. all-equal garbage)."""
    inn = entry.get("input")
    out = entry.get("output")
    if not (isinstance(inn, (int, float)) and isinstance(out, (int, float))):
        return False
    if not (0 < out <= 50 and 0 < inn < out and inn > out * 0.01):
        return False
    return True


def _fetch_deepseek() -> dict[str, dict] | None:
    """Best-effort live pull of DeepSeek v4 rates from official docs.

    Returns a dict of model -> {input, output, cache_read} on success, else
    None. Every parsed entry is sanity-checked; on failure we keep the
    curated baseline (a wrong live pull is worse than a slightly stale one).
    """
    try:
        req = urllib.request.Request(
            SOURCES["deepseek"], headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        return None

    try:
        import re
        out: dict[str, dict] = {}
        models = ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp"]
        for model in models:
            idx = html.lower().find(model)
            if idx < 0:
                continue
            block = html[idx: idx + 4000]
            prices = [float(p) for p in re.findall(r"\$(\d+(?:\.\d+)?)", block)[:6]]
            # Expected order: hit-off, hit-peak, miss-off, miss-peak,
            # out-off, out-peak. Use peak miss (input) and peak output.
            if len(prices) >= 6:
                entry = {
                    "input": prices[3],
                    "output": prices[5],
                    "cache_read": prices[1],
                    "input_cache_miss": prices[3],
                    "source": "deepseek",
                    "note": "Live pull; peak rates. Off-peak is half.",
                }
                if _sane_deepseek(entry):
                    out[model] = entry
        return out if out else None
    except Exception:
        return None


def _fetch_fx() -> float | None:
    """Best-effort live USD->CNY rate from a public FX API. None on failure."""
    try:
        req = urllib.request.Request(
            SOURCES["fx"], headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        rate = data.get("rates", {}).get("CNY")
        return float(rate) if isinstance(rate, (int, float)) else None
    except Exception:
        return None


def build(fetched: str) -> dict:
    models = dict(EMBEDDED_PRICING)
    live = _fetch_deepseek()
    if live:
        for k, v in live.items():
            models[k] = {**models.get(k, {}), **v, "live": True}
    fx_rate = _fetch_fx() or EMBEDDED_FX_USD_CNY
    fx = {
        "USD_CNY": round(fx_rate, 4),
        "fetched": fetched,
        "source": "open.er-api.com" if _fetch_fx() else "embedded default",
        "note": "1 USD = USD_CNY CNY. Used to report cost in RMB (¥) on request.",
    }
    return {
        "currency": "USD",
        "fetched": fetched,
        "note": (
            "Rates are per 1,000,000 tokens in USD, using each provider's "
            "standard (non-cached) list rate. The skill merges cache tokens "
            "into the input bucket, so estimated cost is a CONSERVATIVE UPPER "
            "BOUND: providers bill cached tokens cheaper. Adjust the `input` "
            "rate per model for a tighter estimate. Refresh monthly via "
            "scripts/fetch_pricing.py."
        ),
        "sources": SOURCES,
        "fx": fx,
        "models": models,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh the saved AI pricing table.")
    ap.add_argument("--dry-run", action="store_true", help="Print, do not write.")
    ap.add_argument("--check", action="store_true", help="Warn if file older than --max-age.")
    ap.add_argument("--max-age", type=int, default=35, help="Max age in days for --check.")
    args = ap.parse_args()

    fetched = date.today().isoformat()
    data = build(fetched)

    if args.check:
        if not os.path.exists(PRICING_PATH):
            print("pricing.json missing — run fetch_pricing.py", file=sys.stderr)
            return 1
        try:
            with open(PRICING_PATH) as f:
                saved = json.load(f)
            saved_date = date.fromisoformat(saved.get("fetched", "2000-01-01"))
            age = (date.today() - saved_date).days
            if age > args.max_age:
                print(f"pricing.json is {age} days old (> {args.max_age}) — refresh recommended",
                      file=sys.stderr)
                return 1
            print(f"pricing.json fresh ({age} days old).")
            return 0
        except Exception as e:
            print(f"could not read pricing.json: {e}", file=sys.stderr)
            return 1

    text = json.dumps(data, indent=2, sort_keys=True)
    if args.dry_run:
        print(text)
        return 0

    os.makedirs(REF_DIR, exist_ok=True)
    with open(PRICING_PATH, "w") as f:
        f.write(text + "\n")
    n = len(data["models"])
    print(f"Wrote {PRICING_PATH}: {n} models, fetched {fetched}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
