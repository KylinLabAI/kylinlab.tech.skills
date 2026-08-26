"""Copilot VS Code extension log parser — scan and current-session analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import (
    AGENT_COPILOT,
    UNKNOWN_MODEL,
    UsageBucket,
    SessionInfo,
    CurrentSessionUsage,
    compact_text,
    add_usage,
)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_copilot_session_files(vscode_data: str) -> list[Path]:
    files: list[Path] = []
    # Workspace-scoped sessions
    ws_storage = Path(vscode_data) / "workspaceStorage"
    if ws_storage.exists():
        for chat_dir in ws_storage.glob("*/chatSessions"):
            files.extend(chat_dir.glob("*.jsonl"))
    # Empty-window sessions (no workspace open)
    empty_win = Path(vscode_data) / "globalStorage" / "emptyWindowChatSessions"
    if empty_win.exists():
        files.extend(empty_win.glob("*.jsonl"))
    return sorted(files)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_session_meta(initial_record: dict) -> tuple[str, datetime | None, str]:
    """Return (session_id, creation_date, model) from Copilot initial record."""
    v = initial_record.get("v", {})
    if not isinstance(v, dict):
        return ("", None, "")
    session_id = v.get("sessionId", "")
    creation_date: datetime | None = None
    creation_ts = v.get("creationDate")
    if creation_ts and isinstance(creation_ts, (int, float)):
        creation_date = datetime.fromtimestamp(creation_ts / 1000, tz=timezone.utc)
    model = ""
    input_state = v.get("inputState", {})
    if isinstance(input_state, dict):
        selected = input_state.get("selectedModel", {})
        if isinstance(selected, dict):
            md = selected.get("metadata", {})
            if isinstance(md, dict):
                model = md.get("name", md.get("id", ""))
    return (session_id, creation_date, model)


def _extract_usage(record: dict) -> tuple[int, int] | None:
    """Extract (input, output) tokens from a Copilot incremental result record."""
    if record.get("kind") != 1:
        return None
    k = record.get("k", [])
    if not isinstance(k, list) or len(k) < 3:
        return None
    if k[-1] != "result" or k[0] != "requests":
        return None
    v = record.get("v", {})
    if not isinstance(v, dict):
        return None
    prompt = 0
    completion = 0
    usage = v.get("usage")
    if isinstance(usage, dict):
        prompt = usage.get("promptTokens", 0)
        completion = usage.get("completionTokens", 0)
    if prompt == 0 and completion == 0:
        metadata = v.get("metadata")
        if isinstance(metadata, dict):
            prompt = metadata.get("promptTokens", 0)
            completion = metadata.get("outputTokens", 0) or metadata.get("completionTokens", 0)
    if not isinstance(prompt, int):
        prompt = 0
    if not isinstance(completion, int):
        completion = 0
    if prompt == 0 and completion == 0:
        return None
    return (prompt, completion)


def _extract_model(record: dict) -> str | None:
    if record.get("kind") != 1:
        return None
    k = record.get("k", [])
    if not isinstance(k, list) or "selectedModel" not in k:
        return None
    v = record.get("v", {})
    if not isinstance(v, dict):
        return None
    md = v.get("metadata", {})
    if isinstance(md, dict):
        return md.get("name", md.get("id", ""))
    return None


def _extract_task(initial_record: dict) -> str:
    """Extract the first user message from the initial record as the session task."""
    v = initial_record.get("v", {})
    if not isinstance(v, dict):
        return ""
    requests = v.get("requests", [])
    if not isinstance(requests, list):
        return ""
    for req in requests:
        if not isinstance(req, dict):
            continue
        msg = req.get("message", {})
        if isinstance(msg, dict):
            text = msg.get("text", "")
            if text:
                return compact_text(str(text), 96)
    return ""


def _extract_tokens_from_result(result: dict) -> tuple[int, int]:
    """Extract (prompt, output) tokens from a Copilot result dict."""
    prompt = 0
    output = 0
    u = result.get("usage")
    if isinstance(u, dict):
        prompt = u.get("promptTokens", 0)
        output = u.get("completionTokens", 0)
    if prompt == 0 and output == 0:
        m = result.get("metadata")
        if isinstance(m, dict):
            prompt = m.get("promptTokens", 0)
            output = m.get("outputTokens", 0) or m.get("completionTokens", 0)
    if not isinstance(prompt, int):
        prompt = 0
    if not isinstance(output, int):
        output = 0
    return prompt, output


# ---------------------------------------------------------------------------
# Historical scan
# ---------------------------------------------------------------------------

def scan_copilot(
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
) -> tuple[int, int]:
    """Scan Copilot VS Code extension session files. Returns (scanned, counted)."""
    scanned = 0
    counted = 0

    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        if not lines:
            continue
        try:
            first = json.loads(lines[0])
        except json.JSONDecodeError:
            continue

        session_id, creation_date, model = _extract_session_meta(first)
        session_key = f"copilot:{session_id or path.stem}"
        current_model = model or UNKNOWN_MODEL
        task = _extract_task(first)

        info = SessionInfo(
            session_key=session_key,
            agent=AGENT_COPILOT,
            model=current_model,
            task=task,
            started_at=creation_date.isoformat() if creation_date else "",
        )
        session_infos[session_key] = info

        # Extract usage from initial full-state record requests
        if first.get("kind") in (0, "v"):
            v_data = first.get("v", {})
            if isinstance(v_data, dict):
                requests = v_data.get("requests", [])
                if isinstance(requests, list):
                    for req in requests:
                        if not isinstance(req, dict):
                            continue
                        result = req.get("result", {})
                        if not isinstance(result, dict):
                            continue
                        prompt, completion = 0, 0
                        usage = result.get("usage")
                        if isinstance(usage, dict):
                            prompt = usage.get("promptTokens", 0)
                            completion = usage.get("completionTokens", 0)
                        if prompt == 0 and completion == 0:
                            rmeta = result.get("metadata")
                            if isinstance(rmeta, dict):
                                prompt = rmeta.get("promptTokens", 0)
                                completion = rmeta.get("outputTokens", 0) or rmeta.get("completionTokens", 0)
                        if not isinstance(prompt, int):
                            prompt = 0
                        if not isinstance(completion, int):
                            completion = 0
                        if prompt == 0 and completion == 0:
                            continue
                        scanned += 1
                        if creation_date and start <= creation_date < end:
                            add_usage(daily, per_session, per_model, per_agent,
                                      prompt, completion, session_key, current_model,
                                      AGENT_COPILOT, creation_date,
                                      daily_agent, daily_model,
                                      per_agent_model, daily_agent_model)
                            counted += 1

        # Incremental records
        for line in lines[1:]:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            new_model = _extract_model(record)
            if new_model:
                current_model = new_model
                info.model = new_model
            usage = _extract_usage(record)
            if usage is None:
                continue
            scanned += 1
            if creation_date and start <= creation_date < end:
                add_usage(daily, per_session, per_model, per_agent,
                          usage[0], usage[1], session_key, current_model,
                          AGENT_COPILOT, creation_date,
                          daily_agent, daily_model,
                          per_agent_model, daily_agent_model)
                counted += 1

    return scanned, counted


# ---------------------------------------------------------------------------
# Current session analysis
# ---------------------------------------------------------------------------

def analyze_current_copilot_session(
    session_path: Path,
    lines: list[str],
    first: dict[str, Any],
) -> CurrentSessionUsage:
    """Parse a single Copilot session JSONL file and return context usage."""
    usage = CurrentSessionUsage()
    usage.agent = AGENT_COPILOT

    v = first.get("v", {})
    if isinstance(v, dict):
        usage.session_id = v.get("sessionId", session_path.stem)
        ts = v.get("creationDate")
        if ts and isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            usage.creation_date = dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")

        input_state = v.get("inputState", {})
        if isinstance(input_state, dict):
            sel = input_state.get("selectedModel", {})
            if isinstance(sel, dict):
                md = sel.get("metadata", {})
                if isinstance(md, dict):
                    usage.model_name = md.get("name", md.get("id", ""))
                    usage.max_input_tokens = md.get("maxInputTokens", 0) or 0
                    usage.max_output_tokens = md.get("maxOutputTokens", 0) or 0

        # Usage from initial record requests
        for req in v.get("requests", []):
            if not isinstance(req, dict):
                continue
            result = req.get("result", {})
            if not isinstance(result, dict):
                continue
            prompt, output = _extract_tokens_from_result(result)
            if prompt or output:
                usage.per_turn.append({"prompt": prompt, "output": output})
                usage.total_prompt += prompt
                usage.total_output += output
                usage.turns += 1
                if usage.turns == 1:
                    usage.system_overhead_tokens = prompt

    # Parse incremental records
    for line in lines[1:]:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("kind") != 1:
            continue
        k = record.get("k", [])

        # Model change
        if isinstance(k, list) and "selectedModel" in k:
            rv = record.get("v", {})
            if isinstance(rv, dict):
                md = rv.get("metadata", {})
                if isinstance(md, dict):
                    new_model = md.get("name", md.get("id", ""))
                    if new_model:
                        usage.model_name = new_model
                    new_max = md.get("maxInputTokens", 0)
                    if new_max:
                        usage.max_input_tokens = new_max
                    new_max_out = md.get("maxOutputTokens", 0)
                    if new_max_out:
                        usage.max_output_tokens = new_max_out

        # Result record with tokens
        if isinstance(k, list) and len(k) >= 3 and k[-1] == "result" and k[0] == "requests":
            rv = record.get("v", {})
            if isinstance(rv, dict):
                prompt, output = _extract_tokens_from_result(rv)
                if prompt or output:
                    usage.per_turn.append({"prompt": prompt, "output": output})
                    usage.total_prompt += prompt
                    usage.total_output += output
                    usage.turns += 1
                    if usage.turns == 1:
                        usage.system_overhead_tokens = prompt

    return usage
