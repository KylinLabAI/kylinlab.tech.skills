"""Output formatters — table, CSV, JSON, chart image, and current-session display."""

from __future__ import annotations

import csv
import json
import sys
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


def print_trend_chart(
    daily: dict[str, UsageBucket],
    dates: list[str],
    width: int,
    per_agent: dict[str, UsageBucket] | None = None,
    daily_agent: dict[str, dict[str, int]] | None = None,
    daily_model: dict[str, dict[str, int]] | None = None,
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
                model_vals = [(d, daily_model.get(d, {}).get(model_name, 0)) for d in dates]
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
) -> None:
    if limit <= 0:
        return
    ranked = sorted(per_session.items(), key=lambda x: x[1].total_tokens, reverse=True)[:limit]
    if not ranked:
        return
    rows = []
    for rank, (sk, bucket) in enumerate(ranked, 1):
        info = session_infos.get(sk, SessionInfo(session_key=sk))
        rows.append([
            str(rank),
            f"{bucket.total_tokens:,}",
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            str(bucket.turns),
            info.agent,
            ", ".join(sorted(bucket.models)) or UNKNOWN_MODEL,
            compact_text(info.task or "-", 80),
        ])

    print()
    print(f"Top {len(rows)} sessions by total tokens:")
    print_rows(
        ["#", "total", "input", "output", "turns", "agent", "models", "task"],
        rows,
        left_align={5, 6, 7},
    )


def print_agent_summary(per_agent: dict[str, UsageBucket]) -> None:
    rows = []
    for agent, bucket in sorted(per_agent.items(), key=lambda x: x[1].total_tokens, reverse=True):
        rows.append([
            agent,
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            f"{bucket.total_tokens:,}",
            str(bucket.turns),
            str(len(bucket.sessions)),
            ", ".join(sorted(bucket.models)) if bucket.models else "",
        ])
    if not rows:
        return
    print()
    print("Usage by agent:")
    print_rows(
        ["agent", "input", "output", "total", "turns", "sessions", "models"],
        rows,
        left_align={0, 6},
    )


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


def print_model_summary(per_model: dict[str, UsageBucket]) -> None:
    rows = []
    for model, bucket in sorted(per_model.items(), key=lambda x: x[1].total_tokens, reverse=True):
        rows.append([
            model,
            f"{bucket.input_tokens:,}",
            f"{bucket.output_tokens:,}",
            f"{bucket.total_tokens:,}",
            str(bucket.turns),
            str(len(bucket.sessions)),
            ", ".join(sorted(bucket.agents)) if bucket.agents else "",
        ])
    if not rows:
        return
    print()
    print("Usage by model:")
    print_rows(
        ["model", "input", "output", "total", "turns", "sessions", "agents"],
        rows,
        left_align={0, 6},
    )


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
    daily_agent: dict[str, dict[str, int]] | None,
    daily_model: dict[str, dict[str, int]] | None,
    output_path: str,
) -> None:
    """Generate a multi-panel chart image with daily token trends."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ImportError:
        print("matplotlib is required for --chart-file. Install: pip install matplotlib",
              file=sys.stderr)
        return

    # Determine how many subplots
    panels = 1  # always: total
    has_agent = daily_agent and len({a for dm in daily_agent.values() for a in dm}) > 1
    has_model = daily_model and len({m for dm in daily_model.values() for m in dm}) > 1
    if has_agent:
        panels += 1
    if has_model:
        panels += 1

    short_dates = [d[5:] for d in dates]  # MM-DD for x-axis
    fig, axes = plt.subplots(panels, 1, figsize=(max(8, len(dates) * 0.8), 4 * panels),
                             squeeze=False)
    axes = axes.flatten()
    panel_idx = 0
    colors_agent = {
        "copilot": "#4A90D9",
        "codex": "#E5A844",
        "claude-cli": "#D9744A",
        "claude-vscode": "#C5603A",
        "claude-code": "#D9744A",
    }
    model_colors = {}
    cmap = plt.colormaps["tab10"]

    # --- Panel 1: Total daily tokens ---
    ax = axes[panel_idx]
    totals = [daily.get(d, UsageBucket()).total_tokens for d in dates]
    ax.bar(short_dates, totals, color="#5B9BD5", edgecolor="white", linewidth=0.5)
    ax.set_title("Daily Total Token Usage", fontweight="bold", fontsize=12)
    ax.set_ylabel("Tokens")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_format_tick))
    ax.tick_params(axis="x", rotation=45)
    for i, v in enumerate(totals):
        if v > 0:
            ax.text(i, v, _format_tick(v), ha="center", va="bottom", fontsize=7)
    panel_idx += 1

    # --- Panel 2: By agent (stacked bar) ---
    if has_agent:
        ax = axes[panel_idx]
        all_agents = sorted({a for dm in daily_agent.values() for a in dm})
        bottom = [0] * len(dates)
        for agent_name in all_agents:
            vals = [daily_agent.get(d, {}).get(agent_name, 0) for d in dates]
            color = colors_agent.get(agent_name, cmap(all_agents.index(agent_name) % 10))
            ax.bar(short_dates, vals, bottom=bottom, label=agent_name,
                   color=color, edgecolor="white", linewidth=0.5)
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_title("Daily Token Usage by Agent", fontweight="bold", fontsize=12)
        ax.set_ylabel("Tokens")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(_format_tick))
        ax.legend(loc="upper left", fontsize=9)
        ax.tick_params(axis="x", rotation=45)
        panel_idx += 1

    # --- Panel 3: By model (stacked bar) ---
    if has_model:
        ax = axes[panel_idx]
        all_models = sorted({m for dm in daily_model.values() for m in dm})
        for i, m in enumerate(all_models):
            model_colors[m] = cmap(i % 10)
        bottom = [0] * len(dates)
        for model_name in all_models:
            vals = [daily_model.get(d, {}).get(model_name, 0) for d in dates]
            ax.bar(short_dates, vals, bottom=bottom, label=model_name,
                   color=model_colors[model_name], edgecolor="white", linewidth=0.5)
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_title("Daily Token Usage by Model", fontweight="bold", fontsize=12)
        ax.set_ylabel("Tokens")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(_format_tick))
        ax.legend(loc="upper left", fontsize=9)
        ax.tick_params(axis="x", rotation=45)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\nChart saved to: {output_path}")


# ---------------------------------------------------------------------------
# Table orchestrator
# ---------------------------------------------------------------------------

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
    # --- Total summary ---
    total = total_bucket(daily)
    print()
    print("=" * 60)
    print(f"  Total tokens:  {total.total_tokens:>15,}  ({format_compact(total.total_tokens)})")
    print(f"  Input tokens:  {total.input_tokens:>15,}")
    print(f"  Output tokens: {total.output_tokens:>15,}")
    print(f"  Turns:         {total.turns:>15,}")
    print(f"  Sessions:      {len(total.sessions):>15,}")
    print("=" * 60)

    # --- Table 1: Usage by agent ---
    print_agent_summary(per_agent)

    # --- Table 2: Usage by model ---
    print_model_summary(per_model)

    # --- Top N sessions ---
    print_top_sessions(per_session, session_infos, top_sessions)

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
        generate_chart_image(daily, active_dates, daily_agent, daily_model, chart_file)


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
) -> None:
    payload: dict[str, Any] = {
        "metadata": metadata,
        "daily": [daily.get(d, UsageBucket()).to_dict(d) for d in dates if daily.get(d, UsageBucket()).total_tokens > 0],
        "total": total_bucket(daily).to_dict(),
    }

    # By agent
    payload["by_agent"] = [
        {"agent": agent, **bucket.to_dict()}
        for agent, bucket in sorted(per_agent.items(), key=lambda x: x[1].total_tokens, reverse=True)
    ]

    # By model
    payload["by_model"] = [
        {"model": model, **bucket.to_dict()}
        for model, bucket in sorted(per_model.items(), key=lambda x: x[1].total_tokens, reverse=True)
    ]

    # Top sessions
    if top_sessions > 0:
        ranked = sorted(per_session.items(), key=lambda x: x[1].total_tokens, reverse=True)[:top_sessions]
        payload["top_sessions"] = [
            session_infos.get(sk, SessionInfo(session_key=sk)).to_dict(bucket)
            for sk, bucket in ranked
        ]

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
