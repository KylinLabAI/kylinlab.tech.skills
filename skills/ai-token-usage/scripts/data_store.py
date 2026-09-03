"""Persistent raw-data CSV store for ai-token-usage.

Every report run scans the agent-client logs (Copilot, Codex, Claude Code,
OpenCode, ...) and produces per-session token totals.  This module persists
those per-session rows to disk as CSV so the history survives across runs and
can be re-analyzed later — **including sessions copied from other machines**.

Store layout (under ``--data-dir``, default ``<skill>/data``):

    data/
      data.csv                       # combined: every host AND agent merged into one file
      <masked-host>/                 # a machine, labelled with its (masked) real hostname
        claudecode/data.csv          # one CSV per agent group, nested under the host
        opencode/data.csv
        copilot/data.csv
        codex/data.csv
        ...
      ky*****in/                     # e.g. another machine merged in via --import-host kylin-win
        claudecode/data.csv
        ...

Cross-machine merging
----------------------
Each row carries a ``host`` column (the machine label, default = local
hostname).  The merge/upsert key is the **composite** ``(host, session_key)``,
so a session from the Mac and an identically-named session from Windows never
collide, and the same session re-imported from the same host is updated in
place (its source logs are append-only, so values are stable).

This supports the intended workflow:

    # On machine A (e.g. Mac): capture local data, merge, report
    python3 scripts/ai_token_usage.py --days 30

    # On machine B (e.g. Windows): capture local data, copy data/data.csv to A
    python3 scripts/ai_token_usage.py --days 30

    # On machine A: merge Windows data, then report across both machines
    python3 scripts/ai_token_usage.py --import-data /tmp/win_data.csv --import-host windows --days 30

Re-running the report a month later accumulates the full history into the same
files without duplicates.
"""

from __future__ import annotations

import csv
import socket
from collections import defaultdict
from pathlib import Path
from typing import Any


def mask_host(host: str) -> str:
    """Mask a hostname for privacy: keep the first/last 2 chars, hash the middle.

    e.g. ``kylin-win`` -> ``ky#####in``.  Hosts of 4 chars or fewer keep only the
    first and last character (``mbp`` -> ``m#p``).  The transform is idempotent,
    so a value that is already masked is returned unchanged.

    The mask character is ``#`` rather than ``*`` because this label becomes a
    real directory name (``data/<masked-host>/<agent>/data.csv``) and ``*`` is
    an illegal filename character on Windows (``OSError: [WinError 123]``).
    ``#`` is portable across Windows, macOS and Linux.
    """
    host = (host or "").strip()
    if not host:
        return "unknown"
    # ``localhost`` / ``unknown`` are generic labels, not real machine names, so
    # they are left untouched (only actual hostnames get masked for privacy).
    if host.lower() in ("localhost", "unknown"):
        return host
    if len(host) <= 4:
        if len(host) <= 2:
            return host
        return host[0] + "#" * (len(host) - 2) + host[-1]
    return host[:2] + "#" * (len(host) - 4) + host[-2:]


def real_hostname() -> str:
    """Best-effort real machine name (not ``localhost``).

    Uses ``socket.gethostname()``; falls back to ``unknown`` if it is empty or
    resolves to the loopback label ``localhost``.
    """
    name = (socket.gethostname() or "").strip()
    if not name or name.lower() == "localhost":
        return "unknown"
    return name

from common import (
    AGENT_CLAUDE_CLI,
    AGENT_CLAUDE_VSCODE,
    AGENT_CLAUDE_CODE,
    AGENT_CODEX_CLI,
    AGENT_CODEX_VSCODE,
    AGENT_CODEX,
    AGENT_COPILOT,
    AGENT_OPENCODE,
    AGENT_QODER,
    AGENT_CODEBUDDY,
    AGENT_TRAE,
    AGENT_CLOUDCODE,
    SessionInfo,
    UsageBucket,
)

# Map a raw agent label to the folder/group name used in the store.
AGENT_GROUP_MAP: dict[str, str] = {
    AGENT_CLAUDE_CLI: "claudecode",
    AGENT_CLAUDE_VSCODE: "claudecode",
    AGENT_CLAUDE_CODE: "claudecode",
    AGENT_CODEX_CLI: "codex",
    AGENT_CODEX_VSCODE: "codex",
    AGENT_CODEX: "codex",
    AGENT_COPILOT: "copilot",
    AGENT_OPENCODE: "opencode",
    AGENT_QODER: "qoder",
    AGENT_CODEBUDDY: "codebuddy",
    AGENT_TRAE: "trae",
    AGENT_CLOUDCODE: "cloudecode",
}

# Column order for every data CSV.  The upsert key is the composite
# (host, session_key) — both are the first two columns.
SESSION_CSV_FIELDS: list[str] = [
    "host",
    "session_key",
    "agent",          # raw label, e.g. claude-cli
    "agent_group",    # folder name, e.g. claudecode
    "model",
    "task",
    "started_at",
    "cwd",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_tokens",
    "turns",
]

# Fields that together form the merge/upsert key.
KEY_FIELDS: tuple[str, ...] = ("host", "session_key")

_KEY_SEP = "\x01"


def _make_key(row: dict[str, Any]) -> str:
    return _KEY_SEP.join(str(row.get(k, "")) for k in KEY_FIELDS)


def build_session_rows(
    session_infos: dict[str, SessionInfo],
    per_session: dict[str, UsageBucket],
    host: str = "",
) -> list[dict[str, Any]]:
    """Convert the in-range scan result into ordered session-row dicts."""
    rows: list[dict[str, Any]] = []
    for sk, bucket in per_session.items():
        info = session_infos.get(sk)
        if info is None:
            continue
        agent = info.agent or ""
        group = AGENT_GROUP_MAP.get(agent, agent or "unknown")
        rows.append(
            {
                "host": host,
                "session_key": sk,
                "agent": agent,
                "agent_group": group,
                "model": info.model or "",
                "task": info.task or "",
                "started_at": info.started_at or "",
                "cwd": info.cwd or "",
                "input_tokens": bucket.input_tokens,
                "output_tokens": bucket.output_tokens,
                "total_tokens": bucket.total_tokens,
                "cache_read_tokens": bucket.cache_read_tokens,
                "turns": bucket.turns,
            }
        )
    return rows


def merge_csv(
    path: Path,
    rows: list[dict[str, Any]],
    key_fields: tuple[str, ...] = KEY_FIELDS,
) -> tuple[int, int]:
    """Upsert ``rows`` into the CSV at ``path`` keyed by ``key_fields``.

    Returns ``(n_new, n_updated)`` — how many keys were added vs overwritten
    from the existing file.
    """
    path = Path(path)
    keyfn = lambda r: _KEY_SEP.join(str(r.get(k, "")) for k in key_fields)  # noqa: E731

    existing: dict[str, dict[str, Any]] = {}
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                k = keyfn(r)
                if k:
                    existing[k] = r

    incoming_keys = {keyfn(r) for r in rows}
    n_new = sum(1 for k in incoming_keys if k not in existing)
    n_updated = sum(1 for k in incoming_keys if k in existing)

    for r in rows:
        existing[keyfn(r)] = r

    merged = sorted(
        existing.values(),
        key=lambda r: (r.get("started_at", "") or "", r.get("session_key", "") or ""),
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SESSION_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in merged:
            writer.writerow(r)

    return n_new, n_updated


def merge_rows_into_store(
    data_dir: str | Path,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge an explicit list of session rows into the store.

    Used both by the normal scan path (via ``update_data_store``) and by the
    ``--import-data`` path, which merges raw rows read from another machine's
    exported CSV.  Returns a summary dict (paths + new/updated counts).
    """
    data_dir = Path(data_dir)
    if not rows:
        return {"combined": None, "groups": {}, "total_new": 0, "total_updated": 0}

    combined_path = data_dir / "data.csv"
    n_new, n_updated = merge_csv(combined_path, rows)

    # Per-host / per-agent-group CSVs, nested as data/<host>/<group>/data.csv so
    # sessions from different machines stay in separate folders (the combined
    # data.csv already carries both host + agent_group columns for cross-analysis).
    by_host_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        host = (r.get("host") or "localhost").strip() or "localhost"
        group = (r.get("agent_group") or "unknown").strip() or "unknown"
        by_host_group[(host, group)].append(r)

    groups: dict[str, dict[str, Any]] = {}
    for (host, group), grows in sorted(by_host_group.items()):
        gpath = data_dir / host / group / "data.csv"
        gn, gu = merge_csv(gpath, grows)
        key = f"{host}/{group}"
        groups[key] = {"path": str(gpath), "new": gn, "updated": gu}

    return {
        "combined": {"path": str(combined_path), "new": n_new, "updated": n_updated},
        "groups": groups,
        "total_new": n_new,
        "total_updated": n_updated,
    }


def update_data_store(
    data_dir: str | Path,
    session_infos: dict[str, SessionInfo],
    per_session: dict[str, UsageBucket],
    host: str = "",
) -> dict[str, Any]:
    """Write/merge the persistent raw-data store from a local scan result."""
    rows = build_session_rows(session_infos, per_session, host=host)
    return merge_rows_into_store(data_dir, rows)


def load_imported_csv(
    path: str | Path,
    import_host: str | None = None,
    fallback_host: str = "",
) -> list[dict[str, Any]]:
    """Read a CSV exported from another machine into session-row dicts.

    ``import_host`` (if given) overrides the ``host`` column for every row, so
    the caller controls the machine label (e.g. ``windows``).  If omitted, the
    row's existing ``host`` is kept, falling back to the file stem.
    """
    path = Path(path)
    stem = path.stem
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            sk = (r.get("session_key") or "").strip()
            if not sk:
                continue
            agent = (r.get("agent") or "").strip()
            group = (r.get("agent_group") or "").strip() or AGENT_GROUP_MAP.get(agent, agent or "unknown")
            host = mask_host(import_host or (r.get("host") or "").strip() or stem)
            rows.append(
                {
                    "host": host,
                    "session_key": sk,
                    "agent": agent,
                    "agent_group": group,
                    "model": (r.get("model") or "").strip(),
                    "task": (r.get("task") or "").strip(),
                    "started_at": (r.get("started_at") or "").strip(),
                    "cwd": (r.get("cwd") or "").strip(),
                    "input_tokens": int(r.get("input_tokens") or 0),
                    "output_tokens": int(r.get("output_tokens") or 0),
                    "total_tokens": int(r.get("total_tokens") or 0),
                    "cache_read_tokens": int(r.get("cache_read_tokens") or 0),
                    "turns": int(r.get("turns") or 0),
                }
            )
    return rows
