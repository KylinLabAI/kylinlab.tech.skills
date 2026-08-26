"""Output formatters — table, CSV, JSON, markdown report, chart image, and current-session display."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from typing import Any

from common import (
    UNKNOWN_MODEL,
    UsageBucket,
    SessionInfo,
    CurrentSessionUsage,
    compact_text,
    format_compact,
    total_bucket,
)
from pricing import (
    estimate_cost,
    currency as price_currency,
    fmt_cost,
    cost_label,
    to_display,
    fx_rate,
)


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

def print_rows(headers: list[str], rows: list[list[str]], left_align: set[int] | None = None) -> None:
    left_align = left_align or set()
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(c)) for w, c in zip(widths, row)]

    def fmt(row: list[str]) -> str:
        cells = []
        for i, (cell, w) in enumerate(zip(row, widths)):
            cells.append(cell.ljust(w) if i in left_align else cell.rjust(w))
        return "  ".join(cells)

    print(fmt(headers))
    print(fmt(["-" * w for w in widths]))
    for row in rows:
        print(fmt(row))


def _tok_total(entry) -> int:
    """Return total token count from a daily_model entry.

    Entries may be a plain int (legacy) or a split dict
    ``{"input":, "output":, "cache":}``. Total includes cache so it matches the
    report's displayed ``total_tokens`` (which folds cache into the input line).
    """
    if isinstance(entry, dict):
        return int(entry.get("input", 0)) + int(entry.get("output", 0)) + int(entry.get("cache", 0))
    return int(entry or 0)


def print_trend_chart(
    daily: dict[str, UsageBucket],
    dates: list[str],
    width: int,
    per_agent: dict[str, UsageBucket] | None = None,
    daily_agent: dict[str, dict[str, int]] | None = None,
    daily_model: dict[str, dict] | None = None,
) -> None:
    width = max(10, width)
    values = [(d, daily.get(d, UsageBucket()).total_tokens) for d in dates]
    max_value = max((v for _, v in values), default=0)

    print()
    print("Daily total token trend:")
    if max_value == 0:
        for d, _ in values:
            print(f"  {d}  {'0':>8}")
        return
    for d, v in values:
        bar_len = round((v / max_value) * width) if v else 0
        bar = "#" * max(1, bar_len) if v else ""
        print(f"  {d}  {format_compact(v):>8}  {bar}")

    # Per-agent daily trend
    if daily_agent:
        all_agents = sorted({a for day_map in daily_agent.values() for a in day_map})
        if len(all_agents) > 1:
            for agent_name in all_agents:
                agent_vals = [(d, daily_agent.get(d, {}).get(agent_name, 0)) for d in dates]
                agent_max = max((v for _, v in agent_vals), default=0)
                if agent_max == 0:
                    continue
                print()
                print(f"Daily token trend — {agent_name}:")
                for d, v in agent_vals:
                    if v == 0:
                        continue
                    bar_len = round((v / agent_max) * width) if v else 0
                    bar = "#" * max(1, bar_len) if v else ""
                    print(f"  {d}  {format_compact(v):>8}  {bar}")

    # Per-model daily trend
    if daily_model:
        all_models = sorted({m for day_map in daily_model.values() for m in day_map})
        if len(all_models) > 1:
            for model_name in all_models:
                model_vals = [(d, _tok_total(daily_model.get(d, {}).get(model_name, 0))) for d in dates]
                model_max = max((v for _, v in model_vals), default=0)
                if model_max == 0:
                    continue
                print()
                print(f"Daily token trend — {model_name}:")
                for d, v in model_vals:
                    if v == 0:
                        continue
                    bar_len = round((v / model_max) * width) if v else 0
                    bar = "#" * max(1, bar_len) if v else ""
                    print(f"  {d}  {format_compact(v):>8}  {bar}")


def print_top_sessions(
    per_session: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    limit: int,
    session_cost: dict[str, float] | None = None,
) -> None:
    if limit <= 0:
        return
    ranked = sorted(per_session.items(), key=lambda x: x[1].total_tokens, reverse=True)[:limit]
    if not ranked:
        return
    rows = []
    for rank, (sk, bucket) in enumerate(ranked, 1):
        info = session_infos.get(sk, SessionInfo(session_key=sk))
        row = [
            str(rank),
            f"{bucket.total_tokens:,}",
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            str(bucket.turns),
            info.agent,
            ", ".join(sorted(bucket.models)) or UNKNOWN_MODEL,
            compact_text(info.task or "-", 80),
        ]
        if session_cost is not None:
            row.append(fmt_cost(session_cost.get(sk, 0)))
        rows.append(row)

    print()
    print(f"Top {len(rows)} sessions by total tokens:")
    headers = ["#", "total", "input", "output", "turns", "agent", "models", "task"]
    if session_cost is not None:
        headers.append("cost")
    print_rows(headers, rows, left_align={5, 6, 7})


def print_agent_summary(
    per_agent: dict[str, UsageBucket],
    agent_cost: dict[str, float] | None = None,
) -> None:
    rows = []
    for agent, bucket in sorted(per_agent.items(), key=lambda x: x[1].total_tokens, reverse=True):
        row = [
            agent,
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            f"{bucket.total_tokens:,}",
            str(bucket.turns),
            str(len(bucket.sessions)),
            ", ".join(sorted(bucket.models)) if bucket.models else "",
        ]
        if agent_cost is not None:
            row.append(fmt_cost(agent_cost.get(agent, 0)))
        rows.append(row)
    if not rows:
        return
    print()
    print("Usage by agent:")
    headers = ["agent", "input", "output", "total", "turns", "sessions", "models"]
    if agent_cost is not None:
        headers.append("cost")
    print_rows(headers, rows, left_align={0, 6})


def print_availability_notes(notes: list[dict[str, str]]) -> None:
    """Print a compact note about IDEs that do not expose local token logs."""
    unavailable = [n for n in notes if n["available"] == "no"]
    if not unavailable:
        return
    print()
    print("Local token data availability:")
    for n in unavailable:
        print(
            f"  - {n['agent']}: not available locally "
            f"({n['detail']} See {n['dashboard']} for usage.)"
        )


def print_model_summary(
    per_model: dict[str, UsageBucket],
    model_cost: dict[str, float] | None = None,
) -> None:
    rows = []
    for model, bucket in sorted(per_model.items(), key=lambda x: x[1].total_tokens, reverse=True):
        row = [
            model,
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            f"{bucket.total_tokens:,}",
            str(bucket.turns),
            str(len(bucket.sessions)),
            ", ".join(sorted(bucket.agents)) if bucket.agents else "",
        ]
        if model_cost is not None:
            row.append(fmt_cost(model_cost.get(model, 0)))
        rows.append(row)
    if not rows:
        return
    print()
    print("Usage by model:")
    headers = ["model", "input", "output", "total", "turns", "sessions", "agents"]
    if model_cost is not None:
        headers.append("cost")
    print_rows(headers, rows, left_align={0, 6})


# ---------------------------------------------------------------------------
# Chart image generation
# ---------------------------------------------------------------------------

def _format_tick(value: float, _pos: Any = None) -> str:
    """Format axis tick labels compactly (e.g. 10M, 500K)."""
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.0f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(int(value))


def generate_chart_image(
    daily: dict[str, UsageBucket],
    dates: list[str],
    daily_model: dict[str, dict] | None,
    model_rates: dict[str, float] | None = None,
    output_path: str = "",
    verbose: bool = True,
) -> None:
    """Generate a multi-panel chart image:

    1. Daily token usage by model (stacked) — combines the previous by-agent
       and by-model panels into one.
    2. Daily cost (RMB).
    3. Daily sessions.
    4. Daily turns.
    5. Model usage share (pie).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ImportError:
        print("matplotlib is required for chart images. Install: pip install matplotlib",
              file=sys.stderr)
        return

    short_dates = [d[5:] for d in dates]  # MM-DD for x-axis
    fig, axes = plt.subplots(5, 1, figsize=(max(9, len(dates) * 0.8), 16), squeeze=False)
    axes = axes.flatten()
    cmap = plt.colormaps["tab10"]

    has_model = daily_model and len({m for dm in daily_model.values() for m in dm}) > 0

    # --- Panel 1: Daily tokens by model (stacked) ---
    ax = axes[0]
    if has_model:
        all_models = sorted({m for dm in daily_model.values() for m in dm})
        mcolors = {m: cmap(i % 10) for i, m in enumerate(all_models)}
        bottom = [0] * len(dates)
        for m in all_models:
            vals = [_tok_total(daily_model.get(d, {}).get(m, 0)) for d in dates]
            ax.bar(short_dates, vals, bottom=bottom, label=m,
                   color=mcolors[m], edgecolor="white", linewidth=0.5)
            bottom = [b + v for b, v in zip(bottom, vals)]
        # Daily total token count on top of each stacked bar.
        for i, tot in enumerate(bottom):
            if tot > 0:
                ax.text(i, tot, _format_tick(tot), ha="center", va="bottom",
                        fontsize=7, fontweight="bold")
        ax.set_ylim(top=max(bottom) * 1.12 if bottom else 1)
        ax.legend(loc="upper left", fontsize=8)
    else:
        totals = [daily.get(d, UsageBucket()).total_tokens for d in dates]
        ax.bar(short_dates, totals, color="#5B9BD5")
        for i, tot in enumerate(totals):
            if tot > 0:
                ax.text(i, tot, _format_tick(tot), ha="center", va="bottom",
                        fontsize=7, fontweight="bold")
        ax.set_ylim(top=max(totals) * 1.12 if totals else 1)
    ax.set_title("Daily Token Usage by Model", fontweight="bold")
    ax.set_ylabel("Tokens")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_format_tick))
    ax.tick_params(axis="x", rotation=45)

    # --- Panel 2: Daily cost (RMB) ---
    # Computed exactly from each day's per-model input/output/cache split using
    # the saved price table (cached tokens are much cheaper, so the split
    # matters). model_rates is only a fallback for legacy scalar entries.
    ax = axes[1]
    fx = fx_rate()
    cost_vals = []
    for d in dates:
        c = 0.0
        for m, entry in (daily_model.get(d, {}) or {}).items():
            if isinstance(entry, dict):
                # estimate_cost expects input_tokens to already include cache;
                # the split stores standard input separately, so re-add cache.
                usd = estimate_cost(
                    m,
                    int(entry.get("input", 0)) + int(entry.get("cache", 0)),
                    entry.get("output", 0),
                    entry.get("cache", 0),
                )
                if usd:
                    c += float(usd) * fx
            else:
                c += (model_rates.get(m, 0.0) or 0.0) * entry
        cost_vals.append(c)
    ax.plot(short_dates, cost_vals, marker="o", color="#E5A844", linewidth=2)
    ax.set_title("Daily Cost (RMB)", fontweight="bold")
    ax.set_ylabel("RMB")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_format_tick))
    ax.tick_params(axis="x", rotation=45)
    for i, v in enumerate(cost_vals):
        if v > 0:
            ax.text(i, v, _format_tick(v), ha="center", va="bottom", fontsize=7)

    # --- Panel 3: Daily sessions ---
    ax = axes[2]
    sess = [len(daily.get(d, UsageBucket()).sessions) for d in dates]
    ax.bar(short_dates, sess, color="#4A90D9")
    ax.set_title("Daily Sessions", fontweight="bold")
    ax.set_ylabel("Sessions")
    ax.tick_params(axis="x", rotation=45)

    # --- Panel 4: Daily turns ---
    ax = axes[3]
    turns = [daily.get(d, UsageBucket()).turns for d in dates]
    ax.bar(short_dates, turns, color="#7AB648")
    ax.set_title("Daily Turns", fontweight="bold")
    ax.set_ylabel("Turns")
    ax.tick_params(axis="x", rotation=45)

    # --- Panel 5: Model usage share (pie) ---
    ax = axes[4]
    pie_totals: dict[str, int] = {}
    for d in dates:
        for m, tok in (daily_model.get(d, {}) or {}).items():
            pie_totals[m] = pie_totals.get(m, 0) + _tok_total(tok)
    if pie_totals:
        labels = sorted(pie_totals, key=lambda x: -pie_totals[x])
        sizes = [pie_totals[m] for m in labels]
        ax.pie(sizes, labels=labels, colors=[cmap(i % 10) for i in range(len(labels))],
               autopct=lambda p: f"{p:.0f}%", textprops={"fontsize": 8}, startangle=90)
        ax.set_title("Model Usage Share", fontweight="bold")
    else:
        ax.axis("off")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    if verbose:
        print(f"\nChart saved to: {output_path}")


# ---------------------------------------------------------------------------
# Table orchestrator
# ---------------------------------------------------------------------------

def compute_costs(
    per_model: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
) -> tuple[dict[str, float], dict[str, float], dict[str, float], float, bool]:
    """Return (model_cost, agent_cost, session_cost, total_cost, show_cost).

    Shared by the table and markdown renderers so the cost estimate is computed
    identically everywhere. Reads `references/pricing.json` via `pricing`.
    """
    model_cost: dict[str, float] = {}
    for m, bucket in per_model.items():
        c = estimate_cost(m, bucket.input_tokens, bucket.output_tokens, bucket.cache_read_tokens)
        if c is not None:
            model_cost[m] = c
    agent_cost: dict[str, float] = {}
    session_cost: dict[str, float] = {}
    for sk, bucket in per_session.items():
        info = session_infos.get(sk)
        m = info.model if info else ""
        c = estimate_cost(m, bucket.input_tokens, bucket.output_tokens, bucket.cache_read_tokens)
        if c is None:
            continue
        agent_cost[info.agent if info else ""] = (
            agent_cost.get(info.agent if info else "", 0.0) + c
        )
        session_cost[sk] = c
    total_cost = sum(model_cost.values())
    show_cost = bool(model_cost)
    return model_cost, agent_cost, session_cost, total_cost, show_cost


def _merge_bucket(dst: UsageBucket, src: UsageBucket) -> None:
    """Add all fields/sets of `src` into `dst` in place."""
    dst.input_tokens += src.input_tokens
    dst.output_tokens += src.output_tokens
    dst.total_tokens += src.total_tokens
    dst.cache_read_tokens += src.cache_read_tokens
    dst.turns += src.turns
    dst.sessions.update(src.sessions)
    dst.models.update(src.models)
    dst.agents.update(src.agents)


def build_agent_view(
    members: list[str],
    folder_agent: str,
    *,
    per_session: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    per_agent_model: dict[str, dict[str, UsageBucket]],
    session_infos: dict[str, SessionInfo],
    dates: list[str],
    daily_agent_model: dict[str, dict[str, dict[str, int]]],
) -> dict:
    """Build a self-contained view for one agent group (e.g. claude-code).

    `members` are the raw agent labels that map to `folder_agent`
    (claude-cli + claude-vscode -> claude-code). The returned dict has the same
    shape expected by `render_markdown_report` / `generate_chart_image`.
    """
    sess: dict[str, UsageBucket] = {
        sk: b for sk, b in per_session.items()
        if (session_infos.get(sk).agent if session_infos.get(sk) else "") in members
    }

    pa = {folder_agent: UsageBucket()}
    for a in members:
        if a in per_agent:
            _merge_bucket(pa[folder_agent], per_agent[a])
    pa[folder_agent].agents = {folder_agent}

    pm: dict[str, UsageBucket] = {}
    for a in members:
        for model, mb in (per_agent_model.get(a) or {}).items():
            t = pm.setdefault(model, UsageBucket())
            _merge_bucket(t, mb)
            t.agents = {folder_agent}

    daily = {d: UsageBucket() for d in dates}
    for sk, b in sess.items():
        d = (session_infos.get(sk).started_at or "")[:10]
        if d in daily:
            db = daily[d]
            db.input_tokens += b.input_tokens
            db.output_tokens += b.output_tokens
            db.total_tokens += b.total_tokens
            db.cache_read_tokens += b.cache_read_tokens
            db.turns += b.turns
            db.sessions.add(sk)
            db.models.update(b.models)
            db.agents.add(folder_agent)

    da = {d: {folder_agent: daily[d].total_tokens} for d in dates}
    dm: dict[str, dict] = {}
    for d in dates:
        m: dict[str, dict] = {}
        for a in members:
            for model, split in (daily_agent_model.get(d, {}).get(a) or {}).items():
                if isinstance(split, dict):
                    e = m.setdefault(model, {"input": 0, "output": 0, "cache": 0})
                    e["input"] += int(split.get("input", 0))
                    e["output"] += int(split.get("output", 0))
                    e["cache"] += int(split.get("cache", 0))
                else:
                    m[model] = m.get(model, 0) + int(split or 0)
        if m:
            dm[d] = m

    return {
        "daily": daily,
        "per_session": sess,
        "per_model": pm,
        "per_agent": pa,
        "daily_agent": da,
        "daily_model": dm,
    }


def compute_model_rates(per_model_like: dict[str, UsageBucket]) -> dict[str, float]:
    """Return {model: RMB-per-total-token} using the saved price table.

    Used by the chart's daily-cost panel (which always renders cost in RMB).
    Treats a model's tokens at its blended (input+output+cache) rate converted
    to RMB via the USD→CNY rate in `references/pricing.json`.
    """
    rates: dict[str, float] = {}
    fx = fx_rate()
    for model, b in per_model_like.items():
        if b.total_tokens and b.total_tokens > 0:
            usd = estimate_cost(model, b.input_tokens, b.output_tokens, b.cache_read_tokens)
            rates[model] = (float(usd) * fx / b.total_tokens) if usd else 0.0
        else:
            rates[model] = 0.0
    return rates


def build_payload(
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    dates: list[str],
    top_sessions: int,
    metadata: dict[str, Any],
    per_agent_model: dict[str, dict[str, UsageBucket]] | None = None,
    daily_agent_model: dict[str, dict[str, dict[str, int]]] | None = None,
) -> dict[str, Any]:
    """Full structured payload; saved as raw data and used for JSON output."""
    model_cost, agent_cost, session_cost, total_cost, show_cost = compute_costs(
        per_model, per_session, session_infos
    )
    payload: dict[str, Any] = {
        "metadata": metadata,
        "dates": dates,
        "daily": [daily.get(d, UsageBucket()).to_dict(d) for d in dates],
        "total": total_bucket(daily).to_dict(),
        "by_agent": [
            {"agent": agent, **bucket.to_dict()}
            for agent, bucket in sorted(per_agent.items(), key=lambda x: x[1].total_tokens, reverse=True)
        ],
        "by_model": [
            {"model": model, **bucket.to_dict(),
             "cost": round(to_display(estimate_cost(model, bucket.input_tokens, bucket.output_tokens, bucket.cache_read_tokens) or 0), 6)}
            for model, bucket in sorted(per_model.items(), key=lambda x: x[1].total_tokens, reverse=True)
        ],
        "session_infos": {k: v.to_dict() for k, v in session_infos.items()},
        "per_session": {
            sk: {
                **session_infos.get(sk, SessionInfo(session_key=sk)).to_dict(bucket),
                "cost": round(to_display(estimate_cost(
                    session_infos.get(sk, SessionInfo(session_key=sk)).model,
                    bucket.input_tokens, bucket.output_tokens, bucket.cache_read_tokens,
                ) or 0), 6),
            }
            for sk, bucket in per_session.items()
        },
    }
    if per_agent_model is not None:
        payload["per_agent_model"] = {
            a: {m: b.to_dict() for m, b in mm.items()}
            for a, mm in per_agent_model.items()
        }
    if daily_agent_model is not None:
        payload["daily_agent_model"] = {
            d: {a: dict(mm) for a, mm in am.items()}
            for d, am in daily_agent_model.items()
        }
        # Derived, analysis-friendly views (also saved for offline exploration).
        dm: dict[str, dict] = {}
        da: dict[str, dict] = {}
        for d, am in daily_agent_model.items():
            mm: dict = {}
            aa: dict = {}
            for a, m2 in am.items():
                for m, sp in m2.items():
                    if isinstance(sp, dict):
                        e = mm.setdefault(m, {"input": 0, "output": 0, "cache": 0})
                        e["input"] += int(sp.get("input", 0))
                        e["output"] += int(sp.get("output", 0))
                        e["cache"] += int(sp.get("cache", 0))
                        aa[a] = aa.get(a, 0) + e["input"] + e["output"] + e["cache"]
                    else:
                        mm[m] = mm.get(m, 0) + int(sp or 0)
                        aa[a] = aa.get(a, 0) + int(sp or 0)
            if mm:
                dm[d] = mm
            if aa:
                da[d] = aa
        payload["daily_model"] = dm
        payload["daily_agent"] = da
    if top_sessions > 0:
        ranked = sorted(per_session.items(), key=lambda x: x[1].total_tokens, reverse=True)[:top_sessions]
        payload["top_sessions"] = [
            {
                **session_infos.get(sk, SessionInfo(session_key=sk)).to_dict(bucket),
                "cost": round(to_display(estimate_cost(
                    session_infos.get(sk, SessionInfo(session_key=sk)).model,
                    bucket.input_tokens, bucket.output_tokens, bucket.cache_read_tokens,
                ) or 0), 6),
            }
            for sk, bucket in ranked
        ]
    if show_cost:
        payload["total_cost"] = round(
            sum(
                c for c in (
                    to_display(estimate_cost(m, b.input_tokens, b.output_tokens, b.cache_read_tokens) or 0)
                    for m, b in per_model.items()
                ) if c is not None
            ), 6)
        payload["cost_currency"] = cost_label()
        payload["cost_note"] = (
            "Estimate in the requested display currency; cached tokens priced "
            "at the discounted cache-read rate."
        )
    return payload


def print_table(
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    dates: list[str],
    show_chart: bool,
    chart_width: int,
    top_sessions: int,
    daily_agent: dict[str, dict[str, int]] | None = None,
    daily_model: dict[str, dict[str, int]] | None = None,
    chart_file: str | None = None,
) -> None:
    # --- Cost estimation (reads references/pricing.json) ---
    model_cost, agent_cost, session_cost, total_cost, show_cost = compute_costs(
        per_model, per_session, session_infos
    )

    # --- Total summary ---
    total = total_bucket(daily)
    print()
    print("=" * 60)
    print(f"  Total tokens:  {total.total_tokens:>15,}  ({format_compact(total.total_tokens)})")
    print(f"  Input tokens:  {total.input_tokens:>15,}")
    print(f"  Output tokens: {total.output_tokens:>15,}")
    print(f"  Turns:         {total.turns:>15,}")
    print(f"  Sessions:      {len(total.sessions):>15,}")
    if show_cost:
        print(f"  Est. cost:     {cost_label():>15} {fmt_cost(total_cost):>14}")
    print("=" * 60)

    # --- Table 1: Usage by agent ---
    print_agent_summary(per_agent, agent_cost if show_cost else None)

    # --- Table 2: Usage by model ---
    print_model_summary(per_model, model_cost if show_cost else None)

    # --- Top N sessions ---
    print_top_sessions(
        per_session, session_infos, top_sessions,
        session_cost if show_cost else None,
    )

    # --- Daily usage table ---
    headers = ["date", "input", "output", "total", "turns", "sessions", "agents"]
    rows = []
    for d in dates:
        bucket = daily.get(d, UsageBucket())
        if bucket.total_tokens == 0:
            continue
        rows.append([
            d,
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            f"{bucket.total_tokens:,}",
            str(bucket.turns),
            str(len(bucket.sessions)),
            ", ".join(sorted(bucket.agents)) if bucket.agents else "",
        ])
    if rows:
        print()
        print("Daily usage:")
        print_rows(headers, rows, left_align={6})

    # --- Trend charts ---
    if show_chart:
        active_dates = [d for d in dates if daily.get(d, UsageBucket()).total_tokens > 0]
        print_trend_chart(daily, active_dates, chart_width, per_agent, daily_agent, daily_model)

    if chart_file:
        active_dates = [d for d in dates if daily.get(d, UsageBucket()).total_tokens > 0]
        generate_chart_image(
            daily, active_dates, daily_model, compute_model_rates(per_model), chart_file
        )


# ---------------------------------------------------------------------------
# Markdown report (consistent template, saved to disk)
# ---------------------------------------------------------------------------

def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a GitHub-flavored markdown table (no fixed column widths)."""
    if not rows:
        return "_No data._"
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def render_markdown_report(
    path: str,
    *,
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    dates: list[str],
    top_sessions: int,
    daily_agent: dict[str, dict[str, int]] | None = None,
    daily_model: dict[str, dict[str, int]] | None = None,
    chart_rel: str | None = None,
    meta: dict[str, str] | None = None,
) -> None:
    """Write a self-contained markdown report using a fixed section template.

    The template is identical on every run so reports are comparable over time.
    """
    meta = meta or {}
    model_cost, agent_cost, session_cost, total_cost, show_cost = compute_costs(
        per_model, per_session, session_infos
    )
    total = total_bucket(daily)

    L: list[str] = []
    L.append("# AI Token Usage Report")
    L.append("")
    L.append(f"- **Generated:** {meta.get('generated_at', datetime.now().strftime('%Y-%m-%d %H:%M'))}")
    L.append(f"- **Range:** {meta.get('range', 'n/a')}")
    L.append(f"- **Agent filter:** {meta.get('agent', 'all')}")
    L.append(f"- **Currency:** {meta.get('currency', cost_label())}")
    L.append("")

    # Summary
    L.append("## Summary")
    L.append("")
    summary_rows = [
        ["Total tokens", f"{total.total_tokens:,} ({format_compact(total.total_tokens)})"],
        ["Input tokens", f"{total.input_tokens:,}"],
        ["Output tokens", f"{total.output_tokens:,}"],
        ["Turns", f"{total.turns:,}"],
        ["Sessions", f"{len(total.sessions):,}"],
    ]
    if show_cost:
        summary_rows.append(["Est. cost", f"{cost_label()} {fmt_cost(total_cost)}"])
    L.append(_md_table(["Metric", "Value"], summary_rows))
    L.append("")

    # By agent
    L.append("## Usage by Agent")
    L.append("")
    agent_rows = []
    for agent, bucket in sorted(per_agent.items(), key=lambda x: x[1].total_tokens, reverse=True):
        row = [
            agent,
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            f"{bucket.total_tokens:,}",
            str(bucket.turns),
            str(len(bucket.sessions)),
            ", ".join(sorted(bucket.models)) if bucket.models else "",
        ]
        if show_cost:
            row.append(fmt_cost(agent_cost.get(agent, 0)))
        agent_rows.append(row)
    agent_headers = ["agent", "input", "output", "total", "turns", "sessions", "models"]
    if show_cost:
        agent_headers.append("cost")
    L.append(_md_table(agent_headers, agent_rows))
    L.append("")

    # By model
    L.append("## Usage by Model")
    L.append("")
    model_rows = []
    for model, bucket in sorted(per_model.items(), key=lambda x: x[1].total_tokens, reverse=True):
        row = [
            model,
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            f"{bucket.total_tokens:,}",
            str(bucket.turns),
            str(len(bucket.sessions)),
            ", ".join(sorted(bucket.agents)) if bucket.agents else "",
        ]
        if show_cost:
            row.append(fmt_cost(model_cost.get(model, 0)))
        model_rows.append(row)
    model_headers = ["model", "input", "output", "total", "turns", "sessions", "agents"]
    if show_cost:
        model_headers.append("cost")
    L.append(_md_table(model_headers, model_rows))
    L.append("")

    # Top sessions
    if top_sessions > 0:
        L.append(f"## Top {top_sessions} Sessions")
        L.append("")
        ranked = sorted(per_session.items(), key=lambda x: x[1].total_tokens, reverse=True)[:top_sessions]
        sess_rows = []
        for rank, (sk, bucket) in enumerate(ranked, 1):
            info = session_infos.get(sk, SessionInfo(session_key=sk))
            row = [
                str(rank),
                f"{bucket.total_tokens:,}",
                f"{bucket.input_tokens:,}",
                f"{bucket.output_tokens:,}",
                str(bucket.turns),
                info.agent,
                ", ".join(sorted(bucket.models)) or UNKNOWN_MODEL,
                compact_text(info.task or "-", 80),
            ]
            if show_cost:
                row.append(fmt_cost(session_cost.get(sk, 0)))
            sess_rows.append(row)
        sess_headers = ["#", "total", "input", "output", "turns", "agent", "models", "task"]
        if show_cost:
            sess_headers.append("cost")
        L.append(_md_table(sess_headers, sess_rows))
        L.append("")

    # Daily usage
    L.append("## Daily Usage")
    L.append("")
    daily_rows = []
    for d in dates:
        bucket = daily.get(d, UsageBucket())
        if bucket.total_tokens == 0:
            continue
        daily_rows.append([
            d,
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            f"{bucket.total_tokens:,}",
            str(bucket.turns),
            str(len(bucket.sessions)),
            ", ".join(sorted(bucket.agents)) if bucket.agents else "",
        ])
    L.append(_md_table(
        ["date", "input", "output", "total", "turns", "sessions", "agents"], daily_rows
    ))
    L.append("")

    # Chart
    if chart_rel:
        L.append("## Trend Chart")
        L.append("")
        L.append(f"![token usage trend]({chart_rel})")
        L.append("")

    # Notes
    notes = meta.get("notes") or []
    if notes:
        L.append("## Notes")
        L.append("")
        for n in notes:
            L.append(f"- {n}")
        L.append("")

    L.append("---")
    L.append("")
    L.append("_Generated by the `ai-token-usage` skill. Cost is an estimate from "
             "`references/pricing.json`; cached tokens are priced at the discounted "
             "cache-read rate. Non-parseable tools (TRAE, CodeBuddy, etc.) are not included._")
    L.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def print_csv(daily: dict[str, UsageBucket], dates: list[str]) -> None:
    fieldnames = ["date", "input_tokens", "output_tokens", "total_tokens", "turns", "sessions", "agents"]
    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
    writer.writeheader()
    for d in dates:
        bucket = daily.get(d, UsageBucket())
        row = bucket.to_dict(d)
        row["date"] = row.pop("label")
        row.pop("models", None)
        writer.writerow(row)
    total = total_bucket(daily)
    row = total.to_dict("TOTAL")
    row["date"] = row.pop("label")
    row.pop("models", None)
    writer.writerow(row)


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def print_json(
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    dates: list[str],
    top_sessions: int,
    metadata: dict[str, Any],
    per_agent_model: dict[str, dict[str, UsageBucket]] | None = None,
    daily_agent_model: dict[str, dict[str, dict[str, int]]] | None = None,
) -> None:
    payload = build_payload(
        daily, per_session, per_model, per_agent, session_infos, dates,
        top_sessions, metadata, per_agent_model, daily_agent_model,
    )
    print(json.dumps(payload, indent=2, sort_keys=False))


# ---------------------------------------------------------------------------
# Current session display
# ---------------------------------------------------------------------------

def print_current_session(usage: CurrentSessionUsage, fmt: str) -> None:
    """Print context usage summary for the current session."""
    if fmt == "json":
        payload = {
            "session_id": usage.session_id,
            "agent": usage.agent,
            "model": usage.model_name,
            "created": usage.creation_date,
            "context_window": usage.max_input_tokens,
            "full_context_window": usage.full_context_window,
            "max_output_tokens": usage.max_output_tokens,
            "last_prompt_tokens": usage.last_prompt,
            "context_used_pct": round(usage.context_pct, 1),
            "system_prompt_tokens": usage.system_overhead_tokens,
            "message_tokens": usage.messages_tokens,
            "free_space_tokens": usage.free_space_tokens,
            "output_reserved_tokens": usage.output_reserved,
            "category_note": usage.category_note,
            "total_prompt_tokens": usage.total_prompt,
            "total_output_tokens": usage.total_output,
            "total_tokens": usage.total_tokens,
            "turns": usage.turns,
            "per_turn": usage.per_turn,
        }
        print(json.dumps(payload, indent=2, sort_keys=False))
        return

    if fmt == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=[
            "turn", "prompt_tokens", "output_tokens", "total_tokens",
        ])
        writer.writeheader()
        for i, t in enumerate(usage.per_turn, 1):
            writer.writerow({"turn": i, "prompt_tokens": t["prompt"],
                             "output_tokens": t["output"],
                             "total_tokens": t["prompt"] + t["output"]})
        return

    # Table format — Claude-style context usage display
    full_ctx = usage.full_context_window
    max_input = usage.max_input_tokens
    last_p = usage.last_prompt
    output_reserved = usage.output_reserved
    sys_overhead = usage.system_overhead_tokens
    messages_tokens = usage.messages_tokens
    free = usage.free_space_tokens
    used_total = last_p + output_reserved  # portion of full window consumed
    used_pct = (used_total / full_ctx * 100) if full_ctx else 0

    # Per-category percentages relative to full context window
    sys_pct = (sys_overhead / full_ctx * 100) if full_ctx else 0
    msg_pct = (messages_tokens / full_ctx * 100) if full_ctx else 0
    free_pct = (free / full_ctx * 100) if full_ctx else 0
    out_pct = (output_reserved / full_ctx * 100) if full_ctx else 0

    print()
    print("Context Usage")
    if usage.agent:
        print(f"  {usage.agent}")
    print(f"  {usage.model_name or UNKNOWN_MODEL}")

    if full_ctx > 0:
        print(f"  {format_compact(used_total)}/{format_compact(full_ctx)} tokens used ({used_pct:.1f}%)")

        # ASCII bar — proportional segments
        bar_width = 50
        seg_sys = round((sys_overhead / full_ctx) * bar_width) if full_ctx else 0
        seg_msg = round((messages_tokens / full_ctx) * bar_width) if full_ctx else 0
        seg_out = round((output_reserved / full_ctx) * bar_width) if full_ctx else 0
        seg_free = bar_width - seg_sys - seg_msg - seg_out
        if sys_overhead > 0 and seg_sys == 0:
            seg_sys = 1
            seg_free -= 1
        if messages_tokens > 0 and seg_msg == 0:
            seg_msg = 1
            seg_free -= 1
        if output_reserved > 0 and seg_out == 0:
            seg_out = 1
            seg_free -= 1
        if seg_free < 0:
            seg_free = 0
        bar = "S" * seg_sys + "M" * seg_msg + "░" * seg_free + "O" * seg_out
        print(f"  [{bar}]")
        print(f"   {'S':>1}=System  {'M':>1}=Messages  {'░':>1}=Free  {'O':>1}=Output reserved")
        print()

        print("  Estimated usage by category")
        print(f"  ● System prompt (tools+skills): {format_compact(sys_overhead)} tokens ({sys_pct:.1f}%)")
        print(f"  ● Messages:                     {format_compact(messages_tokens)} tokens ({msg_pct:.1f}%)")
        print(f"  □ Free space:                   {format_compact(free)} tokens ({free_pct:.1f}%)")
        print(f"  ▨ Output reserved:              {format_compact(output_reserved)} tokens ({out_pct:.1f}%)")
        print(f"                                  ─────────────────────")
        print(f"    Total context window:         {format_compact(full_ctx)} tokens")
        if usage.category_note:
            print(f"    Note: {usage.category_note}")
        print()

    print(f"  Session created: {usage.creation_date}")
    print(f"  Total turns:     {usage.turns}")
    print(f"  Total prompt:    {usage.total_prompt:,} tokens")
    print(f"  Total output:    {usage.total_output:,} tokens")
    print(f"  Total tokens:    {usage.total_tokens:,} tokens")
    print()

    # Per-turn breakdown
    if usage.per_turn:
        print("  Per-turn breakdown:")
        print(f"    {'Turn':>4}  {'Prompt':>12}  {'Output':>10}  {'Total':>12}  Context")
        print(f"    {'----':>4}  {'------':>12}  {'------':>10}  {'-----':>12}  -------")
        for i, t in enumerate(usage.per_turn, 1):
            tp = t["prompt"]
            to = t["output"]
            tt = tp + to
            ctx_pct = (tp / max_input * 100) if max_input else 0
            print(f"    {i:>4}  {tp:>12,}  {to:>10,}  {tt:>12,}  {ctx_pct:.1f}%")
