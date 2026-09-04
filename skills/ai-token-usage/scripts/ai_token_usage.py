#!/usr/bin/env python3
"""Report combined AI token usage from Copilot (VS Code) and Codex (CLI).

This is the entry-point script.  Agent-specific parsers live in separate
modules (copilot.py, codex.py) and shared types/helpers in common.py.
Output formatting lives in output.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import sys
from collections import defaultdict
from datetime import datetime, timedelta
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
    add_usage,
    parse_timestamp,
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
    generate_chart_images,
    render_markdown_report,
    build_agent_view,
    compute_model_rates,
    compute_costs,
    fx_rate,
    build_payload,
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
from data_store import (
    update_data_store,
    merge_rows_into_store,
    load_imported_csv,
    load_store_csv,
    AGENT_GROUP_MAP,
    mask_host,
    real_hostname,
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


def default_data_dir() -> str:
    """Persistent raw-data CSV store, co-located with the skill (``data/``)."""
    return str(Path(__file__).resolve().parent.parent / "data")


def default_host() -> str:
    """Local machine label for the raw-data store.

    The local machine is labelled with its **real** hostname (via
    ``socket.gethostname()``), masked for privacy — e.g. ``kylin-win`` becomes
    ``ky#####in``.  This keeps each machine distinct in the store
    (``data/<masked-host>/<agent>/data.csv``) instead of every machine writing
    the same ``localhost`` label.  Other machines are merged in with an explicit
    ``--import-host`` label (also masked).
    """
    return mask_host(real_hostname())


def _load_user_config() -> dict:
    """Load the user-editable ``configs/config.yaml`` (sibling of this script's
    parent dir). Returns ``{}`` when missing or unreadable so callers fall back
    to the env var / built-in default.  Mirrors ``ai-usage-report``."""
    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "configs", "config.yaml",
    )
    if not os.path.exists(cfg_path):
        return {}
    try:
        import yaml
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_CONFIG = _load_user_config()


def resolve_output_dir(cli_value: str | None) -> str:
    """Resolve the report output root with precedence (highest wins):

        1. CLI ``--output-dir`` (when explicitly passed)
        2. env  ``AI_TOKEN_USAGE_ROOT``
        3. ``config.yaml`` ``output_dir``   (user-editable, no code change)
        4. built-in ``~/Desktop/ai-token-usage``

    ``data/`` is co-located under this dir unless ``--data-dir`` overrides it.
    """
    root = cli_value
    if not root:
        root = os.environ.get("AI_TOKEN_USAGE_ROOT")
    if not root:
        root = _CONFIG.get("output_dir")
    if not root:
        root = os.path.join(os.path.expanduser("~/Desktop"), "ai-token-usage")
    return os.path.expanduser(root)


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
    parser.add_argument(
        "--currency",
        choices=("USD", "CNY", "RMB"),
        default="CNY",
        help="Display currency for cost estimates (default: CNY/RMB). USD uses the "
             "USD->CNY rate in references/pricing.json. The trend chart's cost "
             "panel is always rendered in RMB.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for the saved .md report and trend chart image. "
             "Resolved with precedence: this flag > env AI_TOKEN_USAGE_ROOT > "
             "config.yaml output_dir > built-in ~/Desktop/ai-token-usage. "
             "Created if missing.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not write the .md report / chart image to --output-dir; print only.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory for the persistent raw-data CSV store. Default: "
             "<output-dir>/data (co-located with the report under the target "
             "dir, NOT inside the skill). Created if missing; merged across runs "
             "so history accumulates in data/data.csv + per-agent "
             "data/<group>/data.csv.",
    )
    parser.add_argument(
        "--host",
        default=default_host(),
        help="Machine label for local sessions written to the data store "
             "(default: the real hostname, masked for privacy, e.g. "
             "kylin-win -> ky*****in). Used so the same session_key from two "
             "machines stays distinct (stored as data/<host>/<agent>/data.csv).",
    )
    parser.add_argument(
        "--import-data",
        nargs="+",
        metavar="CSV",
        help="Merge one or more CSV files exported from OTHER machines into the "
             "data store, then report across all machines. Each file is a "
             "`data/data.csv` produced by this skill on another host. Pair with "
             "--import-host to label the source machine (e.g. windows).",
    )
    parser.add_argument(
        "--import-host",
        help="Machine label applied to every row imported via --import-data "
             "(e.g. windows). Overrides the host column in the imported file. "
             "If omitted, the file's own host column (or its filename) is used.",
    )
    parser.add_argument(
        "--no-raw-data",
        action="store_true",
        help="Do not update the persistent raw-data CSV store.",
    )
    parser.add_argument(
        "--exclude-free",
        action="store_true",
        help="Price free-tier models at $0 instead of their paid base rate "
             "(for a billable-only assessment). Default counts free models at "
             "their standard rate.",
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
# Store-as-source-of-truth aggregation
# ---------------------------------------------------------------------------

def _row_in_agent_filter(row: dict, agent_filter: str | None) -> bool:
    """Match a store row against the ``--agent`` filter (raw agent or group)."""
    if agent_filter is None:
        return True
    raw = (row.get("agent") or "").strip()
    grp = (row.get("agent_group") or "").strip() or AGENT_GROUP_MAP.get(raw, raw or "unknown")
    if agent_filter == "codex":
        return grp == "codex"
    if agent_filter == "claude-code":
        return grp == "claudecode"
    return raw == agent_filter


def aggregate_store(data_dir, start, end, agent_filter: str | None = None) -> dict:
    """Build the report aggregation by reading the persistent store for [start, end).

    The store (``data/data.csv``) is the single source of truth: every machine's
    sessions — this host's scans plus any imported machines — live there, so
    reading it back makes the report cover all of them without re-passing
    ``--import-data``. The ``--agent`` filter is applied at read time so per-agent
    reports stay correct even though the store is cumulative.
    """
    daily = defaultdict(UsageBucket)
    per_session = defaultdict(UsageBucket)
    per_model = defaultdict(UsageBucket)
    per_agent = defaultdict(UsageBucket)
    daily_agent: dict[str, dict[str, int]] = {}
    daily_model: dict[str, dict] = {}
    per_agent_model: dict[str, dict[str, UsageBucket]] = {}
    daily_agent_model: dict[str, dict[str, dict[str, int]]] = {}
    session_infos: dict[str, SessionInfo] = {}

    for r in load_store_csv(data_dir):
        if agent_filter is not None and not _row_in_agent_filter(r, agent_filter):
            continue
        ts = parse_timestamp(r.get("started_at"))
        if ts is None or ts < start or ts >= end:
            continue
        sk = (r.get("session_key") or "").strip()
        if not sk:
            continue
        model = (r.get("model") or "").strip()
        agent = (r.get("agent") or "").strip()
        add_usage(
            daily, per_session, per_model, per_agent,
            int(r.get("input_tokens") or 0), int(r.get("output_tokens") or 0),
            sk, model, agent, ts,
            daily_agent, daily_model, per_agent_model, daily_agent_model,
            turns=int(r.get("turns") or 0),
            cache_read=int(r.get("cache_read_tokens") or 0),
        )
        if sk not in session_infos:
            session_infos[sk] = SessionInfo(
                session_key=sk, agent=agent, model=model,
                task=(r.get("task") or "").strip(),
                started_at=(r.get("started_at") or "").strip(),
                cwd=(r.get("cwd") or "").strip(),
                host=(r.get("host") or "").strip() or "unknown",
            )
    return {
        "daily": daily,
        "per_session": per_session,
        "per_model": per_model,
        "per_agent": per_agent,
        "daily_agent": daily_agent,
        "daily_model": daily_model,
        "per_agent_model": per_agent_model,
        "daily_agent_model": daily_agent_model,
        "session_infos": session_infos,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    # Resolve the report output dir from CLI > env > config.yaml > built-in
    # default, then co-locate the persistent raw-data store under it (unless
    # --data-dir overrides explicitly).
    output_root = Path(resolve_output_dir(args.output_dir)).resolve()
    args.data_dir = args.data_dir or str(output_root / "data")

    # Force UTF-8 output streams. On Windows the default console encoding (e.g.
    # gbk) cannot encode symbols such as the cost "¥", which otherwise crashes
    # any piped/redirected run. Safe no-op when already UTF-8.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass

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
    per_agent_model: dict[str, dict[str, UsageBucket]] = {}
    daily_agent_model: dict[str, dict[str, dict[str, int]]] = {}
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
            daily_agent, daily_model, per_agent_model, daily_agent_model
        )

    # Codex (CLI + VS Code extension — both live under ~/.codex)
    if args.agent in (None, AGENT_CODEX, AGENT_CODEX_CLI, AGENT_CODEX_VSCODE):
        codex_home = Path(args.codex_home).expanduser().resolve()
        cx_files = find_codex_session_files(codex_home, include_archived=not args.no_archived)
        codex_files = len(cx_files)
        codex_agent_filter = args.agent if args.agent in (AGENT_CODEX_CLI, AGENT_CODEX_VSCODE) else None
        codex_scanned, codex_counted = scan_codex(
            cx_files, start, end, daily, per_session, per_model, per_agent, session_infos,
            daily_agent, daily_model, per_agent_model, daily_agent_model,
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
            session_infos, daily_agent, daily_model, per_agent_model, daily_agent_model,
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
            per_agent_model, daily_agent_model,
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

    # --- Tag local sessions with the machine label (masked for privacy) ---
    local_host = mask_host(args.host)
    for _info in session_infos.values():
        _info.host = local_host

    # --- Import data from other machines (merge into store + in-memory) ---
    # This is the second half of the cross-machine workflow: a CSV exported by
    # this skill on another host (e.g. Windows) is merged into the shared store
    # and folded into the in-memory aggregation so the report covers every
    # machine, not just this one.
    if args.import_data:
        imported_rows: list[dict[str, Any]] = []
        for _fp in args.import_data:
            imported_rows.extend(load_imported_csv(_fp, args.import_host, local_host))
        if imported_rows and not args.no_raw_data:
            _ires = merge_rows_into_store(args.data_dir, imported_rows)
            _icb = _ires["combined"]
            if _icb:
                print(
                    f"\nImported {len(imported_rows)} row(s) from "
                    f"{len(args.import_data)} file(s) "
                    f"(host={args.import_host or 'file'}): {_icb['new']} new, "
                    f"{_icb['updated']} updated -> {_icb['path']}"
                )
        # Fold in-range imported rows into the in-memory aggregation. This is
        # only needed as a fallback for --no-raw-data runs (where the store is
        # NOT written and we report the in-memory result instead). For normal
        # runs the store is the source of truth and is read back below.
        for _r in imported_rows:
            _ts = parse_timestamp(_r["started_at"])
            if _ts is None or _ts < start or _ts >= end:
                continue
            _sk = _r["session_key"]
            session_infos[_sk] = SessionInfo(
                session_key=_sk, agent=_r["agent"], model=_r["model"],
                task=_r["task"], started_at=_r["started_at"], cwd=_r["cwd"],
                host=_r["host"],
            )
            add_usage(
                daily, per_session, per_model, per_agent,
                _r["input_tokens"], _r["output_tokens"], _sk, _r["model"],
                _r["agent"], _ts, daily_agent, daily_model,
                per_agent_model, daily_agent_model,
                turns=_r["turns"], cache_read=_r["cache_read_tokens"],
            )

    # --- Persistent raw-data store (merged across runs) ---
    # Every in-range session scanned locally is upserted into data/data.csv.
    # This store is the SINGLE SOURCE OF TRUTH for the report: the analysis
    # below reads it back, so any machine previously merged in (e.g.
    # ky########in) appears in every later report without re-passing --import-data.
    if not args.no_raw_data:
        store_result = update_data_store(
            args.data_dir, session_infos, per_session, host=local_host
        )
        cb = store_result["combined"]
        if cb:
            print(
                f"\nRaw data store updated: {cb['new']} new, "
                f"{cb['updated']} updated session(s) -> {cb['path']}"
            )
            print(f"  Per-agent CSVs under: {args.data_dir}")

    # --- Build the report aggregation FROM the store (single source of truth) ---
    if args.no_raw_data:
        # Store untouched this run: report the in-memory scan (+ imported) result.
        report = {
            "daily": daily, "per_session": per_session, "per_model": per_model,
            "per_agent": per_agent, "daily_agent": daily_agent,
            "daily_model": daily_model, "per_agent_model": per_agent_model,
            "daily_agent_model": daily_agent_model, "session_infos": session_infos,
        }
    else:
        # Read the store back so all merged machines are covered; the --agent
        # filter is applied at read time to keep per-agent reports correct.
        report = aggregate_store(args.data_dir, start, end, agent_filter=args.agent)
    daily = report["daily"]
    per_session = report["per_session"]
    per_model = report["per_model"]
    per_agent = report["per_agent"]
    daily_agent = report["daily_agent"]
    daily_model = report["daily_model"]
    per_agent_model = report["per_agent_model"]
    daily_agent_model = report["daily_agent_model"]
    session_infos = report["session_infos"]

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

    import pricing as _pricing
    _pricing.set_currency(args.currency)
    _pricing.set_exclude_free(args.exclude_free)

    # Resolve every model up-front so models priced at the fallback ("auto")
    # rates are known before any renderer runs — they are annotated in the
    # terminal output and in report.md's notes for every output format.
    for _m in per_model:
        _pricing.lookup(_m)

    notes = availability_notes()

    # Per-host aggregation (one bucket per machine) for the report.
    per_host: dict[str, UsageBucket] = {}
    for _sk, _b in per_session.items():
        _h = (session_infos.get(_sk).host if session_infos.get(_sk) else "") or "unknown"
        _pb = per_host.setdefault(_h, UsageBucket())
        _pb.input_tokens += _b.input_tokens
        _pb.output_tokens += _b.output_tokens
        _pb.total_tokens += _b.total_tokens
        _pb.cache_read_tokens += _b.cache_read_tokens
        _pb.turns += _b.turns
        _pb.sessions.add(_sk)
        _pb.models.update(_b.models)
        _pb.agents.update(_b.agents)

    if args.format == "table":
        print_table(
            daily, per_session, per_model, per_agent, session_infos, dates,
            show_chart=not args.no_chart,
            chart_width=args.chart_width,
            top_sessions=args.top_sessions,
            daily_agent=daily_agent,
            daily_model=daily_model,
            chart_file=args.chart_file,
            per_host=per_host,
        )
        print()
        print(
            f"Scanned {copilot_files} copilot + {codex_files} codex + "
            f"{claude_files} claude-code session files, "
            f"{total_scanned} usage records, {total_counted} in range."
        )
        print_availability_notes(notes)
        fb = _pricing.fallback_models()
        if fb:
            print()
            print(
                f"Priced at fallback '{_pricing.FALLBACK_KEY}' rates "
                f"(model not in pricing.json): {', '.join(fb)}"
            )
    elif args.format == "csv":
        print_csv(daily, dates)
    elif args.format == "json":
        metadata["tool_availability"] = notes
        print_json(
            daily, per_session, per_model, per_agent, session_infos, dates,
            args.top_sessions, metadata, per_agent_model, daily_agent_model,
            per_host=per_host,
        )

    # Default behavior: persist a dated report folder under <output-dir>/report.
    # Layout:
    #   report/<stamp>/summary/   -> combined (all agents) report + chart + raw
    #   report/<stamp>/<agent>/   -> per-agent report + chart (one per agent)
    # The folder name includes the time so every request gets its own folder.
    if not args.current_session and not args.no_save:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_dir = output_root / "report" / stamp
        report_dir.mkdir(parents=True, exist_ok=True)
        if args.since and args.until:
            range_desc = f"{args.since} .. {args.until}"
        elif args.days:
            range_desc = f"last {args.days} days ({dates[0]} .. {dates[-1]})"
        else:
            range_desc = f"{dates[0]} .. {dates[-1]}"
        notes_list = [
            f"{n['agent']}: not available locally ({n['detail']} See {n['dashboard']} for usage.)"
            for n in notes if n["available"] == "no"
        ]
        fb_models = _pricing.fallback_models()
        if fb_models:
            notes_list.append(
                f"Models not in pricing.json were priced at the fallback "
                f"'{_pricing.FALLBACK_KEY}' rates: {', '.join(fb_models)}."
            )

        # --- Summary (all agents combined) report + chart + raw ---
        summary_dir = report_dir / "summary"
        summary_dir.mkdir(parents=True, exist_ok=True)
        summary_md = summary_dir / "report.md"
        summary_png = summary_dir / "chart.png"
        rates_root = compute_model_rates(per_model)
        try:
            # Build host / agent-group share data (tokens, sessions, RMB) for
            # the two extra pie-diagram rows in the summary chart.
            _, agent_cost, session_cost, _, _ = compute_costs(
                per_model, per_session, session_infos
            )
            fx = fx_rate()
            host_tokens: dict[str, int] = {}
            host_sessions: dict[str, int] = {}
            host_cost: dict[str, float] = {}
            for _h, _b in per_host.items():
                host_tokens[_h] = _b.total_tokens
                host_sessions[_h] = len(_b.sessions)
                host_cost[_h] = 0.0
            agent_tokens: dict[str, int] = {}
            agent_sessions: dict[str, int] = {}
            agent_cost_g: dict[str, float] = {}
            for _a, _b in per_agent.items():
                _g = AGENT_GROUP_MAP.get(_a, _a or "unknown")
                agent_tokens[_g] = agent_tokens.get(_g, 0) + _b.total_tokens
                agent_sessions[_g] = agent_sessions.get(_g, 0) + len(_b.sessions)
                agent_cost_g[_g] = agent_cost_g.get(_g, 0.0) + agent_cost.get(_a, 0.0) * fx
            for _sk, _c in session_cost.items():
                _h = (
                    session_infos.get(_sk).host
                    if session_infos.get(_sk) else ""
                ) or "unknown"
                host_cost[_h] = host_cost.get(_h, 0.0) + _c * fx
            pie_data = {
                "host": {
                    "tokens": host_tokens,
                    "sessions": host_sessions,
                    "cost": host_cost,
                },
                "agent": {
                    "tokens": agent_tokens,
                    "sessions": agent_sessions,
                    "cost": agent_cost_g,
                },
            }
            charts = generate_chart_images(
                daily, dates, daily_model, rates_root, str(summary_png),
                verbose=False, pie_data=pie_data,
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(f"Chart images skipped: {exc}", file=sys.stderr)
        chart_files = [Path(p).name for p in charts]
        render_markdown_report(
            str(summary_md),
            daily=daily, per_session=per_session, per_model=per_model,
            per_agent=per_agent, session_infos=session_infos, dates=dates,
            top_sessions=args.top_sessions, daily_agent=daily_agent,
            daily_model=daily_model, chart_files=chart_files,
            per_host=per_host,
            meta={
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "range": range_desc,
                "agent": args.agent or "all (combined)",
                "currency": _pricing.cost_label(),
                "notes": notes_list,
            },
        )
        print(f"\nSummary report saved to: {summary_md}")
        for cf in chart_files:
            print(f"Summary chart saved to: {summary_dir / cf}")

        # --- Raw data for re-analysis ---
        raw_dir = summary_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_payload = build_payload(
            daily, per_session, per_model, per_agent, session_infos, dates,
            args.top_sessions, metadata, per_agent_model, daily_agent_model,
            per_host=per_host,
        )
        (raw_dir / "report-data.json").write_text(
            json.dumps(raw_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Raw data saved to: {raw_dir / 'report-data.json'}")

        # --- Per-agent subfolders ---
        agent_groups = {
            AGENT_CLAUDE_CLI: "claude-code",
            AGENT_CLAUDE_VSCODE: "claude-code",
            AGENT_CODEX_CLI: "codex",
            AGENT_CODEX_VSCODE: "codex",
        }
        groups: dict[str, list[str]] = {}
        for a in per_agent:
            g = agent_groups.get(a, a)
            groups.setdefault(g, []).append(a)
        for g, members in groups.items():
            view = build_agent_view(
                members, g,
                per_session=per_session, per_agent=per_agent,
                per_agent_model=per_agent_model, session_infos=session_infos,
                dates=dates, daily_agent_model=daily_agent_model,
            )
            # Per-host aggregation scoped to this agent's sessions, so a
            # multi-machine agent report can show host share pies.
            view_per_host: dict[str, UsageBucket] = {}
            for _sk, _b in view["per_session"].items():
                _h = (
                    session_infos.get(_sk).host
                    if session_infos.get(_sk) else ""
                ) or "unknown"
                _pb = view_per_host.setdefault(_h, UsageBucket())
                _pb.input_tokens += _b.input_tokens
                _pb.output_tokens += _b.output_tokens
                _pb.total_tokens += _b.total_tokens
                _pb.cache_read_tokens += _b.cache_read_tokens
                _pb.turns += _b.turns
                _pb.sessions.add(_sk)
                _pb.models.update(_b.models)
                _pb.agents.update(_b.agents)

            # Host usage-share pies for this agent (only when more than one
            # host; drawing is additionally guarded inside generate_chart_images).
            pie_data_a = None
            if len(view_per_host) > 1:
                _, _, session_cost_a, _, _ = compute_costs(
                    view["per_model"], view["per_session"], session_infos
                )
                fx = fx_rate()
                host_tokens_a = {_h: _b.total_tokens for _h, _b in view_per_host.items()}
                host_sessions_a = {_h: len(_b.sessions) for _h, _b in view_per_host.items()}
                host_cost_a = {_h: 0.0 for _h in view_per_host}
                for _sk, _c in session_cost_a.items():
                    _h = (
                        session_infos.get(_sk).host
                        if session_infos.get(_sk) else ""
                    ) or "unknown"
                    host_cost_a[_h] = host_cost_a.get(_h, 0.0) + _c * fx
                pie_data_a = {
                    "host": {
                        "tokens": host_tokens_a,
                        "sessions": host_sessions_a,
                        "cost": host_cost_a,
                    }
                }

            adir = report_dir / g.replace("-", "")
            adir.mkdir(parents=True, exist_ok=True)
            ampng = adir / "chart.png"
            amd = adir / "report.md"
            rates_a = compute_model_rates(view["per_model"])
            try:
                charts_a = generate_chart_images(
                    view["daily"], dates, view["daily_model"], rates_a,
                    str(ampng), verbose=False, pie_data=pie_data_a,
                )
            except Exception as exc:  # pragma: no cover - defensive
                print(f"Chart images skipped for {g}: {exc}", file=sys.stderr)
            chart_files_a = [Path(p).name for p in charts_a]
            render_markdown_report(
                str(amd),
                daily=view["daily"], per_session=view["per_session"],
                per_model=view["per_model"], per_agent=view["per_agent"],
                session_infos=session_infos, dates=dates,
                top_sessions=args.top_sessions, daily_agent=view["daily_agent"],
                daily_model=view["daily_model"], chart_files=chart_files_a,
                per_host=view_per_host,
                meta={
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "range": range_desc,
                    "agent": g,
                    "currency": _pricing.cost_label(),
                    "notes": notes_list,
                },
            )
            print(f"Agent report saved to: {amd}")
            for cf in chart_files_a:
                print(f"Agent chart saved to: {adir / cf}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
