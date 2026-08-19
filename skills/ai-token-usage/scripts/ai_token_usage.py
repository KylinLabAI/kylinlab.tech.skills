#!/usr/bin/env python3
"""Report combined AI token usage from Copilot (VS Code) and Codex (CLI).

This is the entry-point script.  Agent-specific parsers live in separate
modules (copilot.py, codex.py) and shared types/helpers in common.py.
Output formatting lives in output.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from common import (
    AGENT_COPILOT,
    AGENT_CODEX,
    AGENT_CODEX_CLI,
    AGENT_CODEX_VSCODE,
    AGENT_CLAUDE_CODE,
    AGENT_CLAUDE_CLI,
    AGENT_CLAUDE_VSCODE,
    AGENT_QODER,
    AGENT_CODEBUDDY,
    AGENT_TRAE,
    AGENT_OPENCODE,
    AGENT_CLOUDCODE,
    ALL_AGENTS,
    UsageBucket,
    SessionInfo,
    CurrentSessionUsage,
    resolve_range,
    date_keys,
)
from copilot import (
    find_copilot_session_files,
    scan_copilot,
    analyze_current_copilot_session,
)
from codex import (
    find_codex_session_files,
    scan_codex,
    analyze_current_codex_session,
)
from claude_code import (
    find_claude_code_session_files,
    scan_claude_code,
    analyze_current_claude_code_session,
)
from output import (
    print_table,
    print_csv,
    print_json,
    print_current_session,
    print_availability_notes,
)
from opencode import (
    scan_opencode,
    analyze_current_opencode_session,
)
from probe_ides import (
    scan_qoder,
    scan_codebuddy,
    scan_trae,
    scan_cloudecode,
    availability_notes,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def default_vscode_data_dir() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Code/User")
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "Code", "User")
    else:
        return os.path.expanduser("~/.config/Code/User")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report combined AI token usage from Copilot (VS Code) and Codex (CLI)."
    )
    parser.add_argument(
        "--vscode-data",
        default=default_vscode_data_dir(),
        help="VS Code user-data directory (auto-detected).",
    )
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME", "~/.codex"),
        help="Codex home directory (default: ~/.codex).",
    )
    parser.add_argument(
        "--claude-projects-dir",
        default=os.path.expanduser("~/.claude/projects"),
        help="Claude Code projects directory (default: ~/.claude/projects).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to include (default: 30).",
    )
    parser.add_argument("--since", help="Start date inclusive (YYYY-MM-DD).")
    parser.add_argument("--until", help="End date inclusive (YYYY-MM-DD).")
    parser.add_argument(
        "--format",
        choices=("table", "csv", "json"),
        default="table",
        help="Output format (default: table).",
    )
    parser.add_argument(
        "--top-sessions",
        type=int,
        default=3,
        help="Number of top sessions to show (default: 3, 0 to disable).",
    )
    parser.add_argument(
        "--no-chart",
        action="store_true",
        help="Do not print the daily usage trend chart.",
    )
    parser.add_argument(
        "--chart-file",
        help="Save daily trend chart as an image file (PNG/PDF/SVG). Requires matplotlib.",
    )
    parser.add_argument(
        "--chart-width",
        type=int,
        default=48,
        help="Maximum bar width for the trend chart (default: 48).",
    )
    parser.add_argument(
        "--agent",
        choices=ALL_AGENTS,
        help="Report only one agent (codex includes both codex-cli and codex-vscode).",
    )
    parser.add_argument(
        "--no-archived",
        action="store_true",
        help="Exclude Codex archived_sessions.",
    )
    parser.add_argument(
        "--no-subagents",
        action="store_true",
        help="Exclude Claude Code subagent sessions from token counts.",
    )
    parser.add_argument(
        "--current-session",
        action="store_true",
        help="Show context usage summary for the current (most recent) Copilot chat session.",
    )
    parser.add_argument(
        "--session-file",
        help="Path to a specific session JSONL file to analyze (used with --current-session).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Current-session dispatcher
# ---------------------------------------------------------------------------

def analyze_current_session(session_path: Path) -> CurrentSessionUsage:
    """Parse a single session and return context usage.

    For OpenCode the "path" is a sentinel string (opencode:<id>) referring to a
    database row, handled separately.
    """
    if str(session_path).startswith("opencode:"):
        return analyze_current_opencode_session() or CurrentSessionUsage()
    try:
        lines = session_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return CurrentSessionUsage()
    if not lines:
        return CurrentSessionUsage()

    try:
        first = json.loads(lines[0])
    except json.JSONDecodeError:
        return CurrentSessionUsage()

    # Codex format: session_meta / turn_context / event_msg / response_item
    if first.get("type") in {"session_meta", "turn_context", "event_msg", "response_item"}:
        return analyze_current_codex_session(session_path, lines)

    # Claude Code format: queue-operation, user, assistant, attachment,
    # file-history-snapshot, system — none of which match Codex or Copilot
    if first.get("type") in {
        "queue-operation", "user", "assistant", "attachment",
        "file-history-snapshot", "system",
    }:
        return analyze_current_claude_code_session(session_path, lines)

    # Copilot format: first record has a "kind" field or "v" structure
    return analyze_current_copilot_session(session_path, lines, first)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    # --- Current session mode ---
    if args.current_session:
        if args.session_file:
            session_path = Path(args.session_file)
        else:
            candidates: list[Path] = []
            opencode_current = None
            if args.agent in (None, AGENT_COPILOT):
                candidates.extend(find_copilot_session_files(args.vscode_data))
            if args.agent in (None, AGENT_CODEX, AGENT_CODEX_CLI, AGENT_CODEX_VSCODE):
                candidates.extend(
                    find_codex_session_files(
                        Path(args.codex_home).expanduser().resolve(),
                        include_archived=not args.no_archived,
                    )
                )
            if args.agent in (None, AGENT_CLAUDE_CODE, AGENT_CLAUDE_CLI, AGENT_CLAUDE_VSCODE):
                candidates.extend(
                    find_claude_code_session_files(
                        Path(args.claude_projects_dir).expanduser().resolve(),
                        include_subagents=not args.no_subagents,
                    )
                )
            if args.agent in (None, AGENT_OPENCODE):
                oc = analyze_current_opencode_session()
                if oc is not None and oc.total_prompt > 0:
                    # OpenCode is database-backed; track via a flag, not a path.
                    opencode_current = oc
            if not candidates:
                if opencode_current is not None:
                    usage = opencode_current
                    print_current_session(usage, args.format)
                    return 0
                print("No AI session files found.", file=sys.stderr)
                return 1
            session_path = max(candidates, key=lambda p: p.stat().st_mtime)
        if not session_path.exists():
            print(f"Session file not found: {session_path}", file=sys.stderr)
            return 1
        usage = analyze_current_session(session_path)
        if usage.turns == 0:
            print("No token usage found in the session.", file=sys.stderr)
            return 1
        print_current_session(usage, args.format)
        return 0

    # --- Historical usage mode ---
    start, end = resolve_range(args)
    dates = date_keys(start, end)

    daily: dict[str, UsageBucket] = defaultdict(UsageBucket)
    per_session: dict[str, UsageBucket] = defaultdict(UsageBucket)
    per_model: dict[str, UsageBucket] = defaultdict(UsageBucket)
    per_agent: dict[str, UsageBucket] = defaultdict(UsageBucket)
    daily_agent: dict[str, dict[str, int]] = {}
    daily_model: dict[str, dict[str, int]] = {}
    session_infos: dict[str, SessionInfo] = {}

    copilot_scanned = copilot_counted = 0
    codex_scanned = codex_counted = 0
    claude_scanned = claude_counted = 0
    qoder_scanned = qoder_counted = 0
    codebuddy_scanned = codebuddy_counted = 0
    trae_scanned = trae_counted = 0
    opencode_scanned = opencode_counted = 0
    cloudecode_scanned = cloudecode_counted = 0
    copilot_files = 0
    codex_files = 0
    claude_files = 0

    # Copilot VS Code extension (workspace + empty-window sessions)
    if args.agent is None or args.agent == AGENT_COPILOT:
        cp_files = find_copilot_session_files(args.vscode_data)
        copilot_files = len(cp_files)
        copilot_scanned, copilot_counted = scan_copilot(
            cp_files, start, end, daily, per_session, per_model, per_agent, session_infos,
            daily_agent, daily_model
        )

    # Codex (CLI + VS Code extension — both live under ~/.codex)
    if args.agent in (None, AGENT_CODEX, AGENT_CODEX_CLI, AGENT_CODEX_VSCODE):
        codex_home = Path(args.codex_home).expanduser().resolve()
        cx_files = find_codex_session_files(codex_home, include_archived=not args.no_archived)
        codex_files = len(cx_files)
        codex_agent_filter = args.agent if args.agent in (AGENT_CODEX_CLI, AGENT_CODEX_VSCODE) else None
        codex_scanned, codex_counted = scan_codex(
            cx_files, start, end, daily, per_session, per_model, per_agent, session_infos,
            daily_agent, daily_model,
            agent_filter=codex_agent_filter,
        )

    # Claude Code (CLI + VS Code extension — both live under ~/.claude/projects)
    if args.agent in (None, AGENT_CLAUDE_CODE, AGENT_CLAUDE_CLI, AGENT_CLAUDE_VSCODE):
        claude_projects = Path(args.claude_projects_dir).expanduser().resolve()
        cc_files = find_claude_code_session_files(
            claude_projects, include_subagents=not args.no_subagents,
        )
        claude_files = len(cc_files)
        claude_agent_filter = None
        if args.agent in (AGENT_CLAUDE_CLI, AGENT_CLAUDE_VSCODE):
            claude_agent_filter = args.agent
        claude_scanned, claude_counted = scan_claude_code(
            cc_files, start, end, daily, per_session, per_model, per_agent,
            session_infos, daily_agent, daily_model,
            agent_filter=claude_agent_filter,
        )

    # Qoder / CodeBuddy / Trae / CloudCode — VS Code-derived IDEs.
    # These do not persist token usage locally; the parsers probe known paths
    # and return counts only if a parseable token store exists.
    new_agents = [
        (AGENT_QODER, scan_qoder, "qoder_scanned", "qoder_counted"),
        (AGENT_CODEBUDDY, scan_codebuddy, "codebuddy_scanned", "codebuddy_counted"),
        (AGENT_TRAE, scan_trae, "trae_scanned", "trae_counted"),
        (AGENT_CLOUDCODE, scan_cloudecode, "cloudecode_scanned", "cloudecode_counted"),
    ]
    for agent, scanner, s_key, c_key in new_agents:
        if args.agent in (None, agent):
            sc, co = scanner(
                start, end, daily, per_session, per_model, per_agent,
                session_infos, daily_agent, daily_model,
            )
            vars()[s_key] = sc
            vars()[c_key] = co

    # OpenCode — SQLite-backed, full local token data.
    if args.agent in (None, AGENT_OPENCODE):
        opencode_scanned, opencode_counted = scan_opencode(
            start, end, daily, per_session, per_model, per_agent,
            session_infos, daily_agent, daily_model,
        )

    total_scanned = (
        copilot_scanned + codex_scanned + claude_scanned
        + qoder_scanned + codebuddy_scanned + trae_scanned
        + opencode_scanned + cloudecode_scanned
    )
    total_counted = (
        copilot_counted + codex_counted + claude_counted
        + qoder_counted + codebuddy_counted + trae_counted
        + opencode_counted + cloudecode_counted
    )

    metadata = {
        "sources": ["copilot-vscode", "codex-cli", "codex-vscode",
                     "claude-cli", "claude-vscode",
                     "qoder", "codebuddy", "trae", "opencode", "cloudecode"],
        "range_start": start.date().isoformat(),
        "range_end": (end - timedelta(days=1)).date().isoformat(),
        "copilot_session_files": copilot_files,
        "codex_session_files": codex_files,
        "claude_session_files": claude_files,
        "usage_records_scanned": total_scanned,
        "usage_records_counted": total_counted,
    }

    if not daily:
        print(
            f"No usage data found between {start.date()} and {(end - timedelta(days=1)).date()}.",
            file=sys.stderr,
        )
        print(
            f"Scanned {copilot_files} copilot + {codex_files} codex + "
            f"{claude_files} claude-code session files, "
            f"{total_scanned} usage records found.",
            file=sys.stderr,
        )
        notes = availability_notes()
        if any(n["available"] == "no" for n in notes):
            print_availability_notes(notes)
        return 0

    if args.format == "table":
        print_table(
            daily, per_session, per_model, per_agent, session_infos, dates,
            show_chart=not args.no_chart,
            chart_width=args.chart_width,
            top_sessions=args.top_sessions,
            daily_agent=daily_agent,
            daily_model=daily_model,
            chart_file=args.chart_file,
        )
        print()
        print(
            f"Scanned {copilot_files} copilot + {codex_files} codex + "
            f"{claude_files} claude-code session files, "
            f"{total_scanned} usage records, {total_counted} in range."
        )
        notes = availability_notes()
        print_availability_notes(notes)
    elif args.format == "csv":
        print_csv(daily, dates)
    elif args.format == "json":
        notes = availability_notes()
        metadata["tool_availability"] = notes
        print_json(daily, per_session, per_model, per_agent, session_infos, dates,
                    args.top_sessions, metadata)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
