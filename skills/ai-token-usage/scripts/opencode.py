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
    unify_tokens,
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
    per_agent_model: dict[str, dict[str, UsageBucket]] | None = None,
    daily_agent_model: dict[str, dict[str, dict[str, int]]] | None = None,
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
            SELECT id, time_created, model, cost, title, directory,
                   tokens_input, tokens_output, tokens_reasoning,
                   tokens_cache_read, tokens_cache_write
            FROM session
            ORDER BY time_created
            """
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return 0, 0

    # Per-session turn counts. OpenCode's `session` table stores only aggregate
    # token totals (one row per session), so it cannot tell us how many
    # exchanges a session had. The real message log lives in the `message`
    # table; each completed assistant response is one turn.
    msg_turns: dict[str, int] = {}
    try:
        for mr in conn.execute(
            """
            SELECT session_id, count(*) AS n
            FROM message
            WHERE json_extract(data, '$.role') = 'assistant'
            GROUP BY session_id
            """
        ).fetchall():
            msg_turns[mr["session_id"]] = int(mr["n"])
    except sqlite3.Error:
        msg_turns = {}

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

        # Unified model: all cache tokens count as input context; reasoning
        # folds into output. cache_read is tracked separately for cheaper
        # pricing. Routed through the shared unify_tokens helper.
        input_standard, output_unified, cache_read_unified = unify_tokens(
            input_tokens=input_tok,
            output_tokens=output_tok,
            reasoning_tokens=reasoning,
            cache_read=cache_read,
            cache_write=cache_write,
        )
        session_key = f"opencode:{row['id']}"
        # Token-bearing sessions should have at least one assistant turn;
        # default to 1 for sessions whose messages are not in the log.
        turns = msg_turns.get(row["id"]) or 1
        title = (row["title"] or "").strip()
        directory = (row["directory"] or "").strip()
        info = SessionInfo(
            session_key=session_key,
            agent=AGENT_OPENCODE,
            model=model,
            task=(f"{title} — {directory}".strip(" —") if title or directory else ""),
            started_at=ts.isoformat(),
            cwd=directory,
        )
        session_infos.setdefault(session_key, info)
        add_usage(
            daily, per_session, per_model, per_agent,
            input_standard, output_unified, session_key, model,
            AGENT_OPENCODE, ts,
            daily_agent, daily_model,
            per_agent_model, daily_agent_model,
            turns=turns,
            cache_read=cache_read_unified,
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
    prompt, output, _ = unify_tokens(
        input_tokens=row["tokens_input"],
        output_tokens=row["tokens_output"],
        reasoning_tokens=row["tokens_reasoning"],
        cache_read=row["tokens_cache_read"],
        cache_write=row["tokens_cache_write"],
    )
    usage.total_prompt = prompt
    usage.total_output = output
    turns = 0
    try:
        tconn = sqlite3.connect(str(db))
        turns = tconn.execute(
            """
            SELECT count(*) FROM message
            WHERE json_extract(data, '$.role') = 'assistant'
              AND session_id = ?
            """,
            (row["id"],),
        ).fetchone()[0]
        tconn.close()
    except sqlite3.Error:
        turns = 0
    usage.turns = turns or 1
    usage.system_overhead_tokens = prompt  # total only; cannot separate categories
    usage.current_context_tokens = prompt
    return usage
