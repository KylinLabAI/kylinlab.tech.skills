# ai-token-usage — Manual

Report combined AI token usage by reading local session JSONL logs from
**Copilot**, **Codex**, and **Claude Code**, then summarize totals, per-agent
and per-model breakdowns, top sessions, and a daily trend chart.

## What it reads

| Agent | Log location |
|-------|-------------|
| Copilot (workspace sessions) | `~/Library/Application Support/Code/User/workspaceStorage/*/chatSessions/*.jsonl` |
| Copilot (empty-window sessions) | `~/Library/Application Support/Code/User/globalStorage/emptyWindowChatSessions/*.jsonl` |
| Codex CLI (`codex-cli`) | `~/.codex/sessions/**/*.jsonl` + `~/.codex/archived_sessions/*.jsonl` |
| Codex VS Code (`codex-vscode`) | Same paths as Codex CLI (distinguished by `originator` field) |
| Claude Code CLI (`claude-cli`) | `~/.claude/projects/<project-slug>/*.jsonl` (entrypoint `claude`) |
| Claude Code VS Code (`claude-vscode`) | Same paths (entrypoint `claude-vscode`) |
| Claude Code subagents | `~/.claude/projects/<project-slug>/*/subagents/agent-*.jsonl` |

## Install / initialize

This skill uses Python 3 (and matplotlib for chart images). It depends on the
`laptop-setup` skill to provision Python, because its `configs/apps.yaml` is a
drop-in extension of `laptop-setup`'s registry:

```bash
# One-time setup (installs Python 3 via laptop-setup)
python3 skills/ai-token-usage/scripts/init.py
```

For normal reports you do **not** need to initialize again — just run the
report script. If Python is missing at runtime, stop and run `init.py` first.

## Usage

```bash
# Last 30 days (default), table output
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30

# Last 7 days
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 7

# Custom date range
python3 skills/ai-token-usage/scripts/ai_token_usage.py --since 2026-04-01 --until 2026-04-28

# CSV / JSON export
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --format csv
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --format json

# Top 5 sessions
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --top-sessions 5

# Filter by agent
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --agent copilot
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --agent codex
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --agent claude-code
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --agent claude-cli
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --agent codex-cli

# Exclude Claude Code subagent tokens
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --agent claude-code --no-subagents

# Generate a 3-panel PNG chart
python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 7 --chart-file /tmp/ai_token_usage_7d.png

# Current session context usage (most recent Copilot/Codex/Claude Code session)
python3 skills/ai-token-usage/scripts/ai_token_usage.py --current-session
python3 skills/ai-token-usage/scripts/ai_token_usage.py --current-session --agent codex --format json
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--days N` | 30 | Number of days to report |
| `--since` / `--until` | — | Date range (YYYY-MM-DD) |
| `--format` | table | `table`, `csv`, or `json` |
| `--top-sessions N` | 3 | Show top N sessions (0 to disable) |
| `--agent` | — | `copilot`, `codex`, `codex-cli`, `codex-vscode`, `claude-code`, `claude-cli`, `claude-vscode` |
| `--no-chart` | false | Skip the ASCII trend chart |
| `--chart-file PATH` | — | Save a 3-panel PNG (total / by-agent / by-model) |
| `--no-archived` | false | Skip Codex archived sessions |
| `--no-subagents` | false | Exclude Claude Code subagent sessions |
| `--current-session` | false | Show context usage of the most recent session |
| `--session-file` | — | Specific session JSONL (with `--current-session`) |
| `--claude-projects-dir` | ~/.claude/projects | Claude Code projects directory |

## Notes

- Token fields are normalized: Copilot `promptTokens`/`completionTokens` and
  Codex `input_tokens`/`output_tokens`/`reasoning_output_tokens` both map to
  unified `input_tokens` / `output_tokens`.
- Session keys are prefixed `copilot:` / `codex:` / `claude:` to avoid collisions.
- This skill replaces the older separate `copilot-token-usage` and
  `codex-token-usage` skills with one unified report.

## Limitations

TRAE and CodeBuddy do not write parseable local token logs, so their usage
cannot be reported by this skill.
