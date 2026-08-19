"""Availability probes for VS Code-derived AI coding IDEs.

Qoder, CodeBuddy, Trae, and CloudCode do not persist token usage in local
files the way Codex/Claude Code/OpenCode do — their session stores hold only
UI layout and chat transcript metadata. Actual usage is tracked server-side
(web dashboard / cloud console).

These functions therefore *probe* the known local data paths. When no
parseable token store exists, they return structured "unavailable locally"
notes instead of fabricating zeros. This is future-proof: if any of these
products later add a local token store, its real parser should move into its
own per-vendor file (matching the ``copilot.py`` / ``codex.py`` / ``opencode.py``
convention) and be wired into the report driver.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from common import (
    AGENT_QODER,
    AGENT_CODEBUDDY,
    AGENT_TRAE,
    AGENT_CLOUDCODE,
    UsageBucket,
    SessionInfo,
)


# ---------------------------------------------------------------------------
# Data-source location helpers (macOS / Linux / Windows)
# ---------------------------------------------------------------------------

def _vscode_workspace_vscdb_dirs(app_name: str) -> list[Path]:
    """Return candidate workspaceStorage state.vscdb paths for a VS Code-derived IDE."""
    home = os.path.expanduser("~")
    roots: list[str] = [
        f"{home}/Library/Application Support/{app_name}/User/workspaceStorage",  # macOS
        f"{home}/.config/{app_name}/User/workspaceStorage",  # Linux
    ]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        roots.append(f"{local}/{app_name}/User/workspaceStorage")  # Windows
    out: list[Path] = []
    for r in roots:
        d = Path(r)
        if d.is_dir():
            out.append(d)
    return out


def _vscode_global_vscdb_dir(app_name: str) -> Path | None:
    home = os.path.expanduser("~")
    candidates = [
        f"{home}/Library/Application Support/{app_name}/User/globalStorage",
        f"{home}/.config/{app_name}/User/globalStorage",
    ]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates.append(f"{local}/{app_name}/User/globalStorage")
    for c in candidates:
        p = Path(c)
        if p.is_dir():
            return p
    return None


def _find_vscdb_files(dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        files.extend(sorted(d.rglob("state.vscdb")))
    return files


def _find_top_level_session_db(app_name: str) -> Path | None:
    """Some IDEs (e.g. CodeBuddy CN) keep a top-level ``<app>-sessions.vscdb``
    with one ``session:*`` row per conversation. Return its path if present.

    Tries both the literal app name and a lowercased, space-stripped variant,
    because the on-disk file may use a normalized name (e.g. the "CodeBuddy CN"
    app stores ``codebuddy-sessions.vscdb``).
    """
    home = os.path.expanduser("~")
    # Try both the literal app-folder name and a lowercased space-stripped one
    # (some installers normalize the folder), and several filename variants:
    # e.g. "CodeBuddy CN" folder + ``codebuddy-sessions.vscdb`` on disk.
    folder_variants = {app_name, app_name.lower().replace(" ", "")}
    file_stems = {
        app_name,
        app_name.lower().replace(" ", ""),
        app_name.split()[0],
        app_name.split()[0].lower(),
    }
    roots = [
        f"{home}/Library/Application Support",  # macOS
        f"{home}/.config",  # Linux
    ]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        roots.append(local)  # Windows
    for root in roots:
        for folder in folder_variants:
            for stem in file_stems:
                for ext in ("vscdb", "db"):
                    p = Path(root) / folder / f"{stem}-sessions.{ext}"
                    if p.is_file():
                        return p
    return None


def _count_session_rows(db_path: Path) -> int:
    """Count ``session:*`` rows in a probe DB (best-effort; returns 0 on error)."""
    try:
        conn = sqlite3.connect(str(db_path))
        n = conn.execute(
            "SELECT COUNT(*) FROM ItemTable WHERE key LIKE 'session:%'"
        ).fetchone()[0]
        conn.close()
        return int(n)
    except sqlite3.Error:
        return 0


# Key patterns that indicate a local chat-session record across different IDEs.
# (Qoder: ``aicoding-chat-<uuid>``; Trae: ``ai-chat.chatQueryCompletion.v1.<id>``.)
_CHAT_SESSION_KEY_LIKES = (
    "session:%",
    "aicoding-chat-%",
    "ai-chat.chatQueryCompletion%",
    "ai-chat:sessionRelation%",
)


def _count_chat_sessions_in_vscdb(db_path: Path) -> int:
    """Count local chat-session records in a ``state.vscdb`` ItemTable.

    Returns the number of distinct session-like keys, or 0 on error / none.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        total = 0
        for pat in _CHAT_SESSION_KEY_LIKES:
            n = conn.execute(
                "SELECT COUNT(*) FROM ItemTable WHERE key LIKE ?", (pat,)
            ).fetchone()[0]
            total += int(n)
        conn.close()
        return total
    except sqlite3.Error:
        return 0


# VS Code-derived IDE app names (macOS / Linux / Windows bundle names).
_QODER_APP_NAMES = ["Qoder", "QoderCN"]
_CODEBUDDY_APP_NAMES = ["CodeBuddy", "CodeBuddy CN"]
_TRAE_APP_NAMES = ["Trae", "Trae CN"]
_CLOUDCODE_APP_NAMES = ["CloudCode", "CloudCode CN", "cloudecode", "ClaudeCode"]


def _probe_vscode_token_store(app_names: list[str]) -> tuple[bool, str]:
    """Return (found_token_store, detail_message).

    These IDEs do not persist token usage locally. We probe for any local
    session data across all candidate app folders and storage locations, and
    report the largest count found (and that token counts are not stored)
    instead of fabricating zeros.
    """
    best_total = 0
    best_label = ""
    found_any = False
    for app in app_names:
        # Top-level session DB (e.g. CodeBuddy CN's codebuddy-sessions.vscdb).
        sdb = _find_top_level_session_db(app)
        if sdb is not None:
            n = _count_session_rows(sdb)
            found_any = True
            if n > best_total:
                best_total = n
                best_label = f"{n} session record(s) in {sdb.name}"
        # VS Code workspace storage (state.vscdb per workspace).
        ws_dirs = _vscode_workspace_vscdb_dirs(app)
        if ws_dirs:
            found_any = True
            files = _find_vscdb_files(ws_dirs)
            n = sum(_count_chat_sessions_in_vscdb(f) for f in files)
            if n > best_total:
                best_total = n
                best_label = f"{n} chat-session record(s) found"
        # VS Code global storage (single state.vscdb).
        g = _vscode_global_vscdb_dir(app)
        if g:
            found_any = True
            gdb = g / "state.vscdb"
            n = _count_chat_sessions_in_vscdb(gdb) if gdb.is_file() else 0
            if n > best_total:
                best_total = n
                best_label = f"{n} chat-session record(s) in globalStorage"

    if not found_any:
        return False, "No local session data directory found for this IDE."
    if best_total == 0:
        return False, (
            f"Local session data directory exists for {app_names[0]} but no "
            f"token-usage records are stored on disk (usage is tracked "
            f"server-side)."
        )
    return False, (
        f"Local session data exists for {app_names[0]} ({best_label}), but no "
        f"token-usage records are stored on disk (usage is tracked server-side)."
    )


def scan_qoder(
    start, end,
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    daily_agent=None,
    daily_model=None,
) -> tuple[int, int]:
    found, _ = _probe_vscode_token_store(_QODER_APP_NAMES)
    if not found:
        return 0, 0
    return 0, 0


def scan_codebuddy(
    start, end,
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    daily_agent=None,
    daily_model=None,
) -> tuple[int, int]:
    found, _ = _probe_vscode_token_store(_CODEBUDDY_APP_NAMES)
    if not found:
        return 0, 0
    return 0, 0


def scan_trae(
    start, end,
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    daily_agent=None,
    daily_model=None,
) -> tuple[int, int]:
    found, _ = _probe_vscode_token_store(_TRAE_APP_NAMES)
    if not found:
        return 0, 0
    return 0, 0


def scan_cloudecode(
    start, end,
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    session_infos: dict[str, SessionInfo],
    daily_agent=None,
    daily_model=None,
) -> tuple[int, int]:
    found, _ = _probe_vscode_token_store(_CLOUDCODE_APP_NAMES)
    if not found:
        return 0, 0
    return 0, 0


def availability_notes() -> list[dict[str, str]]:
    """Return per-tool status for IDEs that do not expose local token logs."""
    notes: list[dict[str, str]] = []
    for agent, app_names, dashboard in [
        (AGENT_QODER, _QODER_APP_NAMES, "Qoder web dashboard"),
        (AGENT_CODEBUDDY, _CODEBUDDY_APP_NAMES, "Tencent Cloud console"),
        (AGENT_TRAE, _TRAE_APP_NAMES, "TRAE web dashboard"),
        (AGENT_CLOUDCODE, _CLOUDCODE_APP_NAMES, "CloudBase console"),
    ]:
        found, detail = _probe_vscode_token_store(app_names)
        notes.append({
            "agent": agent,
            "available": "yes" if found else "no",
            "detail": detail if not found else "Local token store found.",
            "dashboard": dashboard,
        })
    return notes
