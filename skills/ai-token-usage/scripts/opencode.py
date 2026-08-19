"""OpenCode token-usage parser.

OpenCode persists full per-session token usage (input/output/reasoning/
cache_read/cache_write and cost) in a local SQLite database
(``~/.local/share/opencode/opencode.db``). This module reads it directly.

Unlike the VS Code-derived IDEs (see ``probe_ides.py``), OpenCode has real
local token data and is parsed like Copilot/Codex/Claude Code.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any

from common import (
    AGENT_OPENCODE,
    UNKNOWN_MODEL,
    UsageBucket,
    SessionInfo,
    CurrentSessionUsage,
    add_usage,
    parse_timestamp,
)


def _extract_opencode_model(raw: Any) -> str:
    """OpenCode stores the model as a JSON string like
    '{"id":"qwen-max","providerID":"alibaba-cn"}'. Extract the id; fall back to
    the raw value or UNKNOWN_MODEL."""
    if raw is None:
        return UNKNOWN_MODEL
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                mid = obj.get("id") or obj.get("name") or obj.get("model")
                if mid:
                    return str(mid)
            except (json.JSONDecodeError, TypeError):
                pass
        if s:
            return s
    if isinstance(raw, dict):
        return str(raw.get("id") or raw.get("name") or UNKNOWN_MODEL)
    return UNKNOWN_MODEL


def find_opencode_db() -> object:
    home = os.path.expanduser("~")
    candidates = [
        f"{home}/.local/share/opencode/opencode.db",
        f"{home}/.opencode/opencode.db",
        f"{os.environ.get('XDG_DATA_HOME', home + '/.local/share')}/opencode/opencode.db",
    ]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates.append(f"{local}/opencode/opencode.db")
    for c in candidates:
        p = __import__("pathlib").Path(c)
        if p.is_file():
            return p
    return None


def scan_opencode(
    start: datetime,
    end: datetime,
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    daily_agent: dict[str, dict[str, int]] | None = None,
    daily_model: dict[str, dict[str, int]] | None = None,
) -> tuple[int, int]:
    """Scan OpenCode's local SQLite database for token usage. Returns (scanned, counted)."""
    db = find_opencode_db()
    if db is None:
        return 0, 0

    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return 0, 0

    scanned = 0
    counted = 0
    try:
        rows = conn.execute(
            """
            SELECT id, time_created, model, cost,
                   tokens_input, tokens_output, tokens_reasoning,
                   tokens_cache_read, tokens_cache_write
            FROM session
            ORDER BY time_created
            """
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return 0, 0

    for row in rows:
        ts = parse_timestamp(row["time_created"] or "")
        if ts is None:
            continue
        scanned += 1
        if ts < start or ts >= end:
            continue

        model = _extract_opencode_model(row["model"])
        input_tok = int(row["tokens_input"] or 0)
        output_tok = int(row["tokens_output"] or 0)
        reasoning = int(row["tokens_reasoning"] or 0)
        cache_read = int(row["tokens_cache_read"] or 0)
        cache_write = int(row["tokens_cache_write"] or 0)
        if input_tok == 0 and output_tok == 0 and reasoning == 0 \
                and cache_read == 0 and cache_write == 0:
            continue

        # Unified model: output includes reasoning tokens.
        output_unified = output_tok + reasoning
        session_key = f"opencode:{row['id']}"
        info = SessionInfo(
            session_key=session_key,
            agent=AGENT_OPENCODE,
            model=model,
            started_at=ts.isoformat(),
        )
        session_infos.setdefault(session_key, info)
        add_usage(
            daily, per_session, per_model, per_agent,
            input_tok, output_unified, session_key, model,
            AGENT_OPENCODE, ts,
            daily_agent, daily_model,
        )
        counted += 1

    conn.close()
    return scanned, counted


def analyze_current_opencode_session() -> CurrentSessionUsage | None:
    """Return the most recent OpenCode session's context usage, if available."""
    db = find_opencode_db()
    if db is None:
        return None
    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, time_created, model,
                   tokens_input, tokens_output, tokens_reasoning,
                   tokens_cache_read, tokens_cache_write, cost
            FROM session
            ORDER BY time_created DESC
            LIMIT 1
            """
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if row is None:
        return None

    usage = CurrentSessionUsage(session_id=row["id"], agent=AGENT_OPENCODE)
    usage.category_note = (
        "OpenCode stores total per-session token counts; per-turn and "
        "category breakdown are not available locally."
    )
    ts = parse_timestamp(row["time_created"] or "")
    if ts:
        usage.creation_date = ts.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    usage.model_name = _extract_opencode_model(row["model"])
    prompt = int(row["tokens_input"] or 0)
    output = int(row["tokens_output"] or 0) + int(row["tokens_reasoning"] or 0)
    usage.total_prompt = prompt
    usage.total_output = output
    usage.turns = 1
    usage.system_overhead_tokens = prompt  # total only; cannot separate categories
    usage.current_context_tokens = prompt
    return usage
