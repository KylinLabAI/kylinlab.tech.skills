"""Claude Code log parser (CLI + VS Code extension) — scan and current-session analysis.

Claude Code stores per-turn (non-cumulative) token usage in
~/.claude/projects/<project-slug>/<uuid>.jsonl with subagent sessions in
<uuid>/subagents/agent-<id>.jsonl.
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from common import (
    AGENT_CLAUDE_CODE,
    AGENT_CLAUDE_CLI,
    AGENT_CLAUDE_VSCODE,
    CLAUDE_ENTRYPOINT_MAP,
    UNKNOWN_MODEL,
    UsageBucket,
    SessionInfo,
    CurrentSessionUsage,
    compact_text,
    add_usage,
    parse_timestamp,
    lookup_model_context_window,
    unify_tokens,
)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_claude_code_session_files(
    claude_projects_dir: Path,
    include_subagents: bool = True,
) -> list[Path]:
    """Find all Claude Code session JSONL files.

    Scans ``<claude_projects_dir>/*/`` for ``*.jsonl`` files and optionally
    ``*/subagents/agent-*.jsonl`` files.  Skips ``*.meta.json``, ``memory``
    directories, and non-JSONL files.
    """
    root = claude_projects_dir.expanduser().resolve()
    if not root.is_dir():
        return []

    files: list[Path] = []

    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue

        # Main session files
        for entry in sorted(project_dir.iterdir()):
            if entry.suffix == ".jsonl" and entry.is_file():
                files.append(entry)

        if not include_subagents:
            continue

        # Subagent session files
        for session_entry in sorted(project_dir.iterdir()):
            if not session_entry.is_dir():
                continue
            subagents_dir = session_entry / "subagents"
            if not subagents_dir.is_dir():
                continue
            for agent_file in sorted(subagents_dir.iterdir()):
                if agent_file.suffix == ".jsonl" and agent_file.name.startswith("agent-"):
                    files.append(agent_file)

    return files


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_task_from_user(content: list) -> str:
    """Extract a human-readable task from a user message's content list.

    Main sessions use ``[{"type": "text", "text": "..."}, ...]``.
    Subagent sessions sometimes use character arrays (single-char strings).
    """
    if not content:
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = str(item.get("text") or "")
            if text:
                parts.append(text)
        elif isinstance(item, str):
            parts.append(item)
    raw = "".join(parts)
    return compact_text(raw, 96)


def _detect_agent_label(entrypoint: str) -> str:
    """Map a Claude Code entrypoint string to an agent label constant."""
    return CLAUDE_ENTRYPOINT_MAP.get(entrypoint, AGENT_CLAUDE_CODE)


# ---------------------------------------------------------------------------
# Historical scan
# ---------------------------------------------------------------------------

def scan_claude_code(
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
    """Scan Claude Code session files (CLI + VS Code extension).

    Returns ``(scanned, counted)`` where *scanned* is the total number of
    ``assistant`` records with usage and *counted* is the number that fall
    within *start* ≤ timestamp < *end*.

    *agent_filter*: if set to ``claude-cli`` or ``claude-vscode``, only
    count sessions matching that entrypoint category.
    """
    scanned = 0
    counted = 0

    for path in files:
        # Determine if this is a subagent file
        is_subagent = "/subagents/agent-" in str(path)
        agent_id = ""
        if is_subagent:
            # Extract agent ID from filename like "agent-a0b9ce2246d439d90.jsonl"
            agent_id = path.stem  # e.g. "agent-a0b9ce2246d439d90"

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        # Pre-scan: find the first record with entrypoint and sessionId
        session_id = ""
        agent_label = AGENT_CLAUDE_CODE
        current_model = UNKNOWN_MODEL
        task = ""
        attribution_agent = ""
        first_timestamp: datetime | None = None
        cwd = ""
        entrypoint_found = False

        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not session_id:
                sid = record.get("sessionId")
                if sid:
                    session_id = str(sid)

            if not entrypoint_found:
                ep = record.get("entrypoint")
                if ep:
                    agent_label = _detect_agent_label(str(ep))
                    entrypoint_found = True

            if not cwd:
                c = record.get("cwd")
                if c:
                    cwd = str(c)

            if not first_timestamp:
                ts = parse_timestamp(record.get("timestamp", ""))
                if ts:
                    first_timestamp = ts

            if is_subagent and not attribution_agent:
                aa = record.get("attributionAgent")
                if aa:
                    attribution_agent = str(aa)

            if not task:
                if record.get("type") == "user":
                    msg = record.get("message") or {}
                    content = msg.get("content", [])
                    task = _extract_task_from_user(content)
                    if task and attribution_agent:
                        task = f"[{attribution_agent}] {task}"

            if not current_model or current_model == UNKNOWN_MODEL:
                msg = record.get("message") or {}
                m = msg.get("model")
                if m:
                    current_model = str(m)

        # Skip if agent_filter doesn't match
        if agent_filter and agent_label != agent_filter:
            continue

        # Build session key and SessionInfo
        if is_subagent and agent_id:
            session_key = f"claude:{session_id}/{agent_id}"
        else:
            session_key = f"claude:{session_id}"

        info = SessionInfo(
            session_key=session_key,
            agent=agent_label,
            model=current_model,
            task=task,
            started_at=first_timestamp.isoformat() if first_timestamp else "",
            cwd=cwd,
        )
        session_infos[session_key] = info

        # Main scan: iterate assistant records with usage
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if record.get("type") != "assistant":
                continue

            msg = record.get("message") or {}
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue

            input_tok, output_tok, cache_read = unify_tokens(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                reasoning_tokens=usage.get("reasoning_tokens")
                or usage.get("reasoning_output_tokens"),
                cache_read=usage.get("cache_read_input_tokens"),
                cache_creation=usage.get("cache_creation_input_tokens"),
            )
            if input_tok == 0 and output_tok == 0:
                continue

            scanned += 1

            # Update model mid-session if changed
            m = msg.get("model")
            if m:
                current_model = str(m)
                info.model = current_model

            ts = parse_timestamp(record.get("timestamp", ""))
            if ts is None or ts < start or ts >= end:
                continue

            add_usage(
                daily, per_session, per_model, per_agent,
                input_tok, output_tok, session_key, current_model,
                agent_label, ts,
                daily_agent, daily_model,
                per_agent_model, daily_agent_model,
                cache_read=cache_read,
            )
            counted += 1

    return scanned, counted


# ---------------------------------------------------------------------------
# Current session analysis
# ---------------------------------------------------------------------------

def analyze_current_claude_code_session(
    session_path: Path, lines: list[str],
) -> CurrentSessionUsage:
    """Parse a single Claude Code session JSONL file and return token/context usage."""
    usage = CurrentSessionUsage(session_id=session_path.stem, agent=AGENT_CLAUDE_CODE)
    usage.category_note = (
        "Claude Code logs do not expose exact system/tool/skill/message "
        "category counts; system overhead estimated from first turn prompt."
    )

    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Session identity
        if not usage.session_id or usage.session_id == session_path.stem:
            sid = record.get("sessionId")
            if sid:
                usage.session_id = str(sid)
                ts = parse_timestamp(record.get("timestamp", ""))
                if ts:
                    usage.creation_date = ts.astimezone().strftime("%Y-%m-%d %H:%M:%S")

        # Entrypoint → agent
        if usage.agent == AGENT_CLAUDE_CODE:
            ep = record.get("entrypoint")
            if ep:
                usage.agent = _detect_agent_label(str(ep))

        if record.get("type") != "assistant":
            continue

        msg = record.get("message") or {}

        # Model
        m = msg.get("model")
        if m:
            usage.model_name = str(m)

        u = msg.get("usage")
        if not isinstance(u, dict):
            continue

        prompt, output, _ = unify_tokens(
            input_tokens=u.get("input_tokens"),
            output_tokens=u.get("output_tokens"),
            reasoning_tokens=u.get("reasoning_tokens") or u.get("reasoning_output_tokens"),
            cache_read=u.get("cache_read_input_tokens"),
            cache_creation=u.get("cache_creation_input_tokens"),
        )
        if prompt == 0 and output == 0:
            continue

        usage.per_turn.append({"prompt": prompt, "output": output})
        usage.total_prompt += prompt
        usage.total_output += output
        usage.turns += 1
        if usage.turns == 1:
            usage.system_overhead_tokens = prompt

    # Look up context window from known models
    usage.max_input_tokens = lookup_model_context_window(usage.model_name)
    if usage.max_input_tokens == 0:
        # Fallback: guess based on model family
        name_lower = usage.model_name.lower()
        if "deepseek" in name_lower or "claude" in name_lower:
            usage.max_input_tokens = 200_000

    return usage
