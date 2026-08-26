"""Codex log parser (CLI + VS Code extension) — scan and current-session analysis."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from common import (
    AGENT_CODEX,
    AGENT_CODEX_CLI,
    AGENT_CODEX_VSCODE,
    CODEX_ORIGINATOR_MAP,
    CODEX_TOKEN_FIELDS,
    UNKNOWN_MODEL,
    UsageBucket,
    SessionInfo,
    CurrentSessionUsage,
    compact_text,
    add_usage,
    parse_timestamp,
    unify_tokens,
)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_codex_session_files(codex_home: Path, include_archived: bool) -> list[Path]:
    roots = [codex_home / "sessions"]
    if include_archived:
        roots.append(codex_home / "archived_sessions")
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(root.rglob("*.jsonl"))
    return sorted(files)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_usage_total(event: dict) -> dict[str, int] | None:
    if event.get("type") != "event_msg":
        return None
    payload = event.get("payload") or {}
    if payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not info:
        return None
    usage = info.get("total_token_usage")
    if not usage:
        return None
    return {f: int(usage.get(f) or 0) for f in CODEX_TOKEN_FIELDS}


def _positive_delta(current: dict[str, int], previous: dict[str, int] | None) -> dict[str, int]:
    if previous is None:
        return current.copy()
    delta = {}
    for f in CODEX_TOKEN_FIELDS:
        value = current[f] - previous.get(f, 0)
        delta[f] = value if value > 0 else 0
    return delta


def _has_usage(delta: dict[str, int]) -> bool:
    return any(delta[f] > 0 for f in CODEX_TOKEN_FIELDS)


def _meaningful_task(message: str) -> str:
    marker = "## My request for Codex:"
    if marker in message:
        message = message.split(marker, 1)[1]
    stripped = message.strip()
    if not stripped or stripped.startswith("<environment_context>") or stripped.startswith("<turn_aborted>"):
        return ""
    return compact_text(stripped, 96)


# ---------------------------------------------------------------------------
# Historical scan
# ---------------------------------------------------------------------------

def scan_codex(
    files: list[Path],
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
    agent_filter: str | None = None,
) -> tuple[int, int]:
    """Scan Codex session files (CLI + VS Code extension). Returns (scanned, counted).

    agent_filter: if set to codex-cli or codex-vscode, only count sessions
    matching that originator category.
    """
    scanned = 0
    counted = 0

    for path in files:
        previous_total: dict[str, int] | None = None
        current_model = UNKNOWN_MODEL
        agent_label = AGENT_CODEX  # default; refined from originator below
        session_key = f"codex:{path.stem}"
        info = SessionInfo(session_key=session_key, agent=AGENT_CODEX)

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        # Pre-scan: determine originator from session_meta (typically line 1)
        # so we can skip the file early if it doesn't match agent_filter.
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "session_meta":
                payload = event.get("payload") or {}
                originator = str(payload.get("originator", ""))
                agent_label = CODEX_ORIGINATOR_MAP.get(originator, AGENT_CODEX)
                info.agent = agent_label
                info.started_at = payload.get("timestamp", "")
                info.cwd = payload.get("cwd", "")
                break

        if agent_filter and agent_label != agent_filter:
            continue

        session_infos[session_key] = info

        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            payload = event.get("payload") or {}

            if event_type == "turn_context":
                m = payload.get("model")
                if m:
                    current_model = str(m)
                    info.model = current_model

            # Task extraction
            if not info.task:
                if event_type == "event_msg" and payload.get("type") == "user_message":
                    task = _meaningful_task(str(payload.get("message") or ""))
                    if task:
                        info.task = task
                elif event_type == "response_item" and payload.get("role") == "user":
                    parts = []
                    for item in payload.get("content") or []:
                        if isinstance(item, dict) and item.get("type") == "input_text":
                            parts.append(str(item.get("text") or ""))
                    task = _meaningful_task("\n".join(parts))
                    if task:
                        info.task = task

            # Token usage
            usage_total = _read_usage_total(event)
            if usage_total is None:
                continue

            scanned += 1
            timestamp = parse_timestamp(event.get("timestamp", ""))
            delta = _positive_delta(usage_total, previous_total)
            previous_total = usage_total

            if timestamp is None or timestamp < start or timestamp >= end or not _has_usage(delta):
                continue

            # Map Codex fields → unified (input, output, cache_read) via the
            # shared helper. cached_input_tokens are cache reads (cheaper).
            input_tok, output_tok, cache_read = unify_tokens(
                input_tokens=delta["input_tokens"],
                output_tokens=delta["output_tokens"],
                reasoning_tokens=delta["reasoning_output_tokens"],
                cache_read=delta["cached_input_tokens"],
            )

            add_usage(daily, per_session, per_model, per_agent,
                      input_tok, output_tok, session_key, current_model,
                      agent_label, timestamp,
                      daily_agent, daily_model,
                      per_agent_model, daily_agent_model,
                      cache_read=cache_read)
            counted += 1

    return scanned, counted


# ---------------------------------------------------------------------------
# Current session analysis
# ---------------------------------------------------------------------------

def analyze_current_codex_session(session_path: Path, lines: list[str]) -> CurrentSessionUsage:
    """Parse a single Codex session JSONL file and return token/context usage."""
    usage = CurrentSessionUsage(session_id=session_path.stem, agent=AGENT_CODEX)
    usage.category_note = (
        "Codex logs do not expose exact system/tool/skill/message category "
        "counts; system and messages are estimated from prompt deltas."
    )
    previous_total: dict[str, int] | None = None

    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")
        payload = event.get("payload") or {}

        if event_type == "session_meta":
            usage.session_id = payload.get("id") or usage.session_id
            ts = parse_timestamp(payload.get("timestamp", ""))
            if ts:
                usage.creation_date = ts.astimezone().strftime("%Y-%m-%d %H:%M:%S")

        if event_type == "turn_context":
            model = payload.get("model")
            if model:
                usage.model_name = str(model)

        usage_total = _read_usage_total(event)
        if usage_total is None:
            continue

        info = payload.get("info") or {}
        context_window = info.get("model_context_window")
        if isinstance(context_window, int) and context_window > 0:
            usage.max_input_tokens = context_window

        delta = _positive_delta(usage_total, previous_total)
        previous_total = usage_total
        last_usage = info.get("last_token_usage")
        if isinstance(last_usage, dict):
            usage.current_context_tokens = int(last_usage.get("input_tokens") or 0)
        else:
            usage.current_context_tokens = usage_total["input_tokens"]

        if not _has_usage(delta):
            continue

        prompt, output, _ = unify_tokens(
            input_tokens=delta["input_tokens"],
            output_tokens=delta["output_tokens"],
            reasoning_tokens=delta["reasoning_output_tokens"],
            cache_read=delta["cached_input_tokens"],
        )
        usage.per_turn.append({"prompt": prompt, "output": output})
        usage.total_prompt += prompt
        usage.total_output += output
        usage.turns += 1
        if usage.turns == 1:
            usage.system_overhead_tokens = prompt

    return usage
