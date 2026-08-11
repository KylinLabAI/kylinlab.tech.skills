"""Shared constants, data classes, and helper functions for ai-token-usage."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_COPILOT = "copilot"
AGENT_CODEX = "codex"
AGENT_CODEX_CLI = "codex-cli"
AGENT_CODEX_VSCODE = "codex-vscode"
AGENT_CLAUDE_CODE = "claude-code"
AGENT_CLAUDE_CLI = "claude-cli"
AGENT_CLAUDE_VSCODE = "claude-vscode"
UNKNOWN_MODEL = "unknown"

ALL_AGENTS = (
    AGENT_COPILOT, AGENT_CODEX, AGENT_CODEX_CLI, AGENT_CODEX_VSCODE,
    AGENT_CLAUDE_CODE, AGENT_CLAUDE_CLI, AGENT_CLAUDE_VSCODE,
)

# Map Codex originator field to agent label
CODEX_ORIGINATOR_MAP: dict[str, str] = {
    "codex_exec": AGENT_CODEX_CLI,
    "codex_cli_rs": AGENT_CODEX_CLI,
    "codex-tui": AGENT_CODEX_CLI,
    "codex_vscode": AGENT_CODEX_VSCODE,
    "Codex Desktop": AGENT_CODEX_VSCODE,
}

# Map Claude Code entrypoint field to agent label
CLAUDE_ENTRYPOINT_MAP: dict[str, str] = {
    "claude": AGENT_CLAUDE_CLI,
    "claude-vscode": AGENT_CLAUDE_VSCODE,
}

# Codex token fields in the raw event payload
CODEX_TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)

# Known model context windows (total tokens including output budget).
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "claude opus 4": 200_000,
    "claude sonnet 4": 200_000,
    "claude 3.5 sonnet": 200_000,
    "claude 3 opus": 200_000,
    "gpt-4o": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-4": 128_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
    "gemini 2.5 pro": 1_048_576,
    "gemini 2.0 flash": 1_048_576,
    "deepseek-v4-pro": 1_048_576,
    "deepseek-v4-flash": 1_048_576,
    "deepseek-v4": 1_048_576,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class UsageBucket:
    """Accumulator for token counts."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    turns: int = 0
    sessions: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)
    agents: set[str] = field(default_factory=set)

    def add(
        self,
        input_tok: int,
        output_tok: int,
        session_key: str,
        model: str = "",
        agent: str = "",
    ) -> None:
        self.input_tokens += input_tok
        self.output_tokens += output_tok
        self.total_tokens += input_tok + output_tok
        self.turns += 1
        self.sessions.add(session_key)
        if model:
            self.models.add(model)
        if agent:
            self.agents.add(agent)

    def to_dict(self, label: str | None = None) -> dict[str, Any]:
        row: dict[str, Any] = {}
        if label is not None:
            row["label"] = label
        row.update(
            {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "turns": self.turns,
                "sessions": len(self.sessions),
                "models": ", ".join(sorted(self.models)) if self.models else "",
                "agents": ", ".join(sorted(self.agents)) if self.agents else "",
            }
        )
        return row


@dataclass
class SessionInfo:
    """Metadata for one session."""
    session_key: str
    agent: str = ""
    model: str = ""
    task: str = ""
    started_at: str = ""
    cwd: str = ""

    def to_dict(self, bucket: UsageBucket | None = None) -> dict[str, Any]:
        row: dict[str, Any] = {
            "session_key": self.session_key,
            "agent": self.agent,
            "model": self.model,
            "task": self.task,
            "started_at": self.started_at,
        }
        if bucket:
            row["input_tokens"] = bucket.input_tokens
            row["output_tokens"] = bucket.output_tokens
            row["total_tokens"] = bucket.total_tokens
            row["turns"] = bucket.turns
            row["models"] = ", ".join(sorted(bucket.models))
        return row


@dataclass
class CurrentSessionUsage:
    """Token usage summary for a single active session."""
    session_id: str = ""
    agent: str = ""
    model_name: str = ""
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    current_context_tokens: int = 0
    turns: int = 0
    per_turn: list[dict[str, int]] = field(default_factory=list)
    total_prompt: int = 0
    total_output: int = 0
    creation_date: str = ""
    system_overhead_tokens: int = 0
    category_note: str = ""

    @property
    def total_tokens(self) -> int:
        return self.total_prompt + self.total_output

    @property
    def last_prompt(self) -> int:
        if self.current_context_tokens > 0:
            return self.current_context_tokens
        return self.per_turn[-1]["prompt"] if self.per_turn else 0

    @property
    def context_pct(self) -> float:
        if self.max_input_tokens <= 0:
            return 0.0
        return (self.last_prompt / self.max_input_tokens) * 100

    @property
    def full_context_window(self) -> int:
        known = lookup_model_context_window(self.model_name)
        if known:
            return known
        if self.max_output_tokens > 0:
            return self.max_input_tokens + self.max_output_tokens
        return self.max_input_tokens

    @property
    def output_reserved(self) -> int:
        return max(0, self.full_context_window - self.max_input_tokens)

    @property
    def messages_tokens(self) -> int:
        return max(0, self.last_prompt - self.system_overhead_tokens)

    @property
    def free_space_tokens(self) -> int:
        return max(0, self.max_input_tokens - self.last_prompt)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lookup_model_context_window(model_name: str) -> int:
    """Return the known full context window for a model, or 0 if unknown."""
    if not model_name:
        return 0
    name_lower = model_name.lower()
    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if key in name_lower:
            return window
    return 0


def compact_text(value: str, limit: int = 96) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit - 3]}..."


def format_compact(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def total_bucket(buckets: dict[str, UsageBucket]) -> UsageBucket:
    total = UsageBucket()
    for bucket in buckets.values():
        total.input_tokens += bucket.input_tokens
        total.output_tokens += bucket.output_tokens
        total.total_tokens += bucket.total_tokens
        total.turns += bucket.turns
        total.sessions.update(bucket.sessions)
        total.models.update(bucket.models)
        total.agents.update(bucket.agents)
    return total


def add_usage(
    daily: dict[str, UsageBucket],
    per_session: dict[str, UsageBucket],
    per_model: dict[str, UsageBucket],
    per_agent: dict[str, UsageBucket],
    input_tok: int,
    output_tok: int,
    session_key: str,
    model: str,
    agent: str,
    dt: datetime,
    daily_agent: dict[str, dict[str, int]] | None = None,
    daily_model: dict[str, dict[str, int]] | None = None,
) -> None:
    date_key = dt.astimezone().strftime("%Y-%m-%d")
    total_tok = input_tok + output_tok
    daily[date_key].add(input_tok, output_tok, session_key, model, agent)
    per_session[session_key].add(input_tok, output_tok, session_key, model, agent)
    per_model[model].add(input_tok, output_tok, session_key, model, agent)
    per_agent[agent].add(input_tok, output_tok, session_key, model, agent)
    if daily_agent is not None:
        daily_agent.setdefault(date_key, defaultdict(int))
        daily_agent[date_key][agent] += total_tok
    if daily_model is not None:
        daily_model.setdefault(date_key, defaultdict(int))
        daily_model[date_key][model] += total_tok


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_date(value: str, name: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise SystemExit(f"error: {name} must use YYYY-MM-DD format: {value}")
    return parsed.replace(tzinfo=timezone.utc)


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolve_range(args: Any) -> tuple[datetime, datetime]:
    if args.days <= 0:
        raise SystemExit("error: --days must be greater than 0")
    now = datetime.now(timezone.utc)
    if args.since:
        start = parse_date(args.since, "--since")
    else:
        start = datetime.combine(
            (now - timedelta(days=args.days - 1)).date(),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
    if args.until:
        until_date = parse_date(args.until, "--until").date()
    else:
        until_date = now.date()
    end = datetime.combine(until_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    if end <= start:
        raise SystemExit("error: --until must be on or after --since")
    return start, end


def date_keys(start: datetime, end: datetime) -> list[str]:
    keys: list[str] = []
    current = start.date()
    last = (end - timedelta(days=1)).date()
    while current <= last:
        keys.append(current.isoformat())
        current += timedelta(days=1)
    return keys
