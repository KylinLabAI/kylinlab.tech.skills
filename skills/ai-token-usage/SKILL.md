---
name: ai-token-usage
description: Report combined AI token usage from GitHub Copilot (VS Code extension), Codex (CLI + VS Code extension), and Claude Code (CLI + VS Code extension) by reading local session JSONL logs. Shows total usage, per-agent (copilot/codex-cli/codex-vscode/claude-cli/claude-vscode) breakdown, per-model breakdown, top sessions, and daily trending chart. Also supports a current-session context usage summary showing model, context window fill percentage, and per-turn token breakdown. Use when the user asks for AI token usage, daily token usage, monthly token usage, combined copilot + codex + claude-code usage, token statistics by agent or model, top sessions by tokens, current session token usage, context window usage, how much context is left, or wants a CSV/JSON/table report of AI agent token consumption.
---

# ai-token-usage

Report combined AI token usage from **Copilot** (VS Code extension) and
**Codex** (CLI + VS Code extension) by reading local session JSONL logs.

## Initialization Contract

If the user asks to initialize, set up, or install tools for this skill, run
`python <skill>/scripts/init.py`.

For normal token-usage requests, do not preflight-check dependencies. Run the
report script directly. If Python is missing at runtime, stop and ask the user
to initialize the skill first with `python <skill>/scripts/init.py`.

## Sources

| Agent | Log location |
|-------|-------------|
| Copilot (workspace sessions) | `~/Library/Application Support/Code/User/workspaceStorage/*/chatSessions/*.jsonl` |
| Copilot (empty-window sessions) | `~/Library/Application Support/Code/User/globalStorage/emptyWindowChatSessions/*.jsonl` |
| Codex CLI (`codex-cli`) | `~/.codex/sessions/**/*.jsonl` + `~/.codex/archived_sessions/*.jsonl` |
| Codex VS Code (`codex-vscode`) | Same paths as Codex CLI (distinguished by `originator` field in session metadata) |
| Claude Code CLI (`claude-cli`) | `~/.claude/projects/<project-slug>/*.jsonl` (distinguished by `entrypoint: "claude"`) |
| Claude Code VS Code (`claude-vscode`) | Same paths as CLI (distinguished by `entrypoint: "claude-vscode"`) |
| Claude Code subagents | `~/.claude/projects/<project-slug>/*/subagents/agent-*.jsonl` |

## When to use

Use this skill when the user asks:

- "show AI token usage"
- "how many tokens did I use this week?"
- "daily token usage for the past month"
- "token usage by agent" / "copilot vs codex usage"
- "token usage by model"
- "which sessions used the most tokens?"
- "export AI usage to CSV / JSON"
- "combined copilot and codex token report"
- "what's my total AI token consumption?"
- "show current session usage"
- "how much context is left?"
- "context window usage"
- "current session token summary"

## Default behavior

- If the user does not specify a duration, report the **last 30 days**.
- Default output format is **table** with:
  - Daily token usage table
  - Usage by agent (copilot / codex) summary
  - Usage by model summary
  - Top 3 sessions by total tokens (with agent, model, task)
  - Daily trending chart

## Core command

```bash
python scripts/ai_token_usage.py --days 30
```

### Common examples

```bash
# Last 7 days
python scripts/ai_token_usage.py --days 7

# Custom date range
python scripts/ai_token_usage.py --since 2026-04-01 --until 2026-04-28

# CSV export
python scripts/ai_token_usage.py --days 30 --format csv

# JSON export
python scripts/ai_token_usage.py --days 30 --format json

# Top 5 sessions
python scripts/ai_token_usage.py --days 30 --top-sessions 5

# Only copilot usage
python scripts/ai_token_usage.py --days 30 --agent copilot

# Only codex usage (CLI + VS Code extension combined)
python scripts/ai_token_usage.py --days 30 --agent codex

# Only codex CLI usage
python scripts/ai_token_usage.py --days 30 --agent codex-cli

# Only codex VS Code extension usage
python scripts/ai_token_usage.py --days 30 --agent codex-vscode

# Only Claude Code usage (CLI + VS Code + subagents)
python scripts/ai_token_usage.py --days 30 --agent claude-code

# Only Claude Code CLI usage
python scripts/ai_token_usage.py --days 30 --agent claude-cli

# Only Claude Code VS Code extension usage
python scripts/ai_token_usage.py --days 30 --agent claude-vscode

# Exclude Claude Code subagent token usage
python scripts/ai_token_usage.py --days 30 --agent claude-code --no-subagents

# Custom Claude Code projects directory
python scripts/ai_token_usage.py --days 30 --claude-projects-dir /custom/path

# Generate chart image (PNG)
python scripts/ai_token_usage.py --days 7 --chart-file /tmp/ai_token_usage_7d.png

# No trend chart
python scripts/ai_token_usage.py --days 30 --no-chart

# Current session context usage. By default this picks the most recently
# modified Copilot or Codex session file.
python scripts/ai_token_usage.py --current-session

# Current Codex session only
python scripts/ai_token_usage.py --current-session --agent codex

# Current Copilot session only
python scripts/ai_token_usage.py --current-session --agent copilot

# Current session as JSON
python scripts/ai_token_usage.py --current-session --format json

# Specific session file
python scripts/ai_token_usage.py --current-session --session-file /path/to/session.jsonl
```

### CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--days N` | 30 | Number of days to report |
| `--since` | — | Start date (YYYY-MM-DD) |
| `--until` | — | End date (YYYY-MM-DD) |
| `--format` | table | Output: `table`, `csv`, or `json` |
| `--top-sessions N` | 3 | Show top N sessions (0 to disable) |
| `--agent` | — | Filter: `copilot`, `codex` (all), `codex-cli`, `codex-vscode`, `claude-code` (all), `claude-cli`, or `claude-vscode` |
| `--no-chart` | false | Skip the daily ASCII trend chart |
| `--chart-file PATH` | — | Save matplotlib chart image (PNG) with 3 panels: total, by-agent, by-model |
| `--chart-width N` | 48 | Max bar width for ASCII trend chart |
| `--no-archived` | false | Skip Codex archived sessions |
| `--no-subagents` | false | Exclude Claude Code subagent sessions from token counts |
| `--current-session` | false | Show context usage for the current (most recent) Copilot, Codex, or Claude Code session |
| `--session-file` | — | Path to a specific session JSONL file (with `--current-session`) |
| `--vscode-data` | auto | VS Code user-data directory |
| `--codex-home` | ~/.codex | Codex home directory |
| `--claude-projects-dir` | ~/.claude/projects | Claude Code projects directory |

## Other AI Coding Tools — Token Usage

The following tools do **not** write parseable local token-usage logs. This skill cannot report their token usage.

| Tool | Token Tracking |
|------|---------------|
| **TRAE** (ByteDance) | Usage tracked via TRAE web dashboard. No local token log format documented. |
| **CodeBuddy** (Tencent Cloud) | Usage tracked via Tencent Cloud console. No local token log format documented. |

Claude Code token usage is now tracked by this skill via `~/.claude/projects/` JSONL logs.

See `references/ai-token-usage-guide.md` § "Other AI Coding Tools" for details.

## Output sections (table format)

1. **Total summary box** — total/input/output tokens, turns, sessions (bordered with `====`)
2. **Usage by agent** — copilot vs codex totals with models used
3. **Usage by model** — per-model totals with agent info
4. **Top N sessions** — highest-token sessions with agent, model, task
5. **Daily usage table** — date, input, output, total, turns, sessions, agents
6. **Daily ASCII trend charts** — total, per-agent, per-model sub-charts
7. **Chart image** (if `--chart-file`) — 3-panel stacked bar chart (total, by-agent, by-model)

### Current session mode (`--current-session`)

Shows a Claude-style context usage summary for the active (most recent) Copilot or Codex
session. Use `--agent codex` or `--agent copilot` to force one source.

- **Model name** and full context window size (e.g. 200K for Claude Opus 4)
- **ASCII bar diagram** — proportional segments: `S`=System, `M`=Messages, `░`=Free, `O`=Output reserved
- **Estimated usage by category** — system prompt (tools+skills), messages, free space, output reserved
- **Token totals** — cumulative prompt/output/total tokens across all turns
- **Per-turn breakdown** — prompt and output tokens for each turn with context %

The full model context window is used as the denominator (e.g. 200K for Claude Opus 4).
The output reserved portion (full window minus maxInputTokens) is shown separately.
System overhead is estimated from the first turn's prompt tokens (system prompt, tool
definitions, skill descriptions, and instructions). Messages = latest prompt − system overhead.

For Codex current-session mode, cumulative totals are computed from positive
deltas of `total_token_usage`; current context fill uses
`last_token_usage.input_tokens` and `model_context_window` when present.

## Workflow

1. For normal human-facing historical reports, run the script in table mode
   with `--chart-file /tmp/ai_token_usage_<range>.png`. Do this for requests
   like "last 30 days", "past week", "this month", "by model", or "top
   sessions" unless the user explicitly asks for machine-readable output.
2. Open or report the chart file path after generation: `open /tmp/ai_token_usage_<range>.png`.
3. For machine-readable output, use `--format csv` or `--format json`.
4. To investigate a specific agent, use `--agent copilot` or `--agent codex`.
5. To see more session detail, increase `--top-sessions`.
6. For current-session chat answers, prefer `--current-session --format json`
   and present the fields as an ASCII context diagram plus compact Markdown
   tables. Use raw terminal output only when the user asks to see the full
   report or per-turn breakdown.

## Chat presentation format

When presenting a historical usage report in chat, always use this consistent
format:

1. **Summary line**: "N-day summary (date range): NM tokens, N sessions, N turns."
2. **Usage by Agent** table — columns: Agent, Tokens, %, Models
3. **Usage by Model** table — columns: Model, Tokens, Agent
4. **Top 3 sessions** table — columns: #, Total Tokens, Turns, Agent, Model, Task
5. **Peak day** line: "Peak day: date at NM (agents)"
6. **Chart saved** line: "Chart saved to <filename>." If the chart was opened
   locally, also mention that it was opened. Do not include a "Command Used"
   section for normal historical reports.

Historical reports should match this shape whether the requester is Codex,
Copilot, or another agent using this skill. Avoid switching to a JSON-derived
summary unless the user asks for JSON or machine-readable output.

When presenting a current-session report in chat, always use this format
instead of prose-only summaries:

1. **Context Usage** ASCII diagram in a fenced `text` block:
   - Include agent and model.
   - Include `<used>/<window> tokens used (<percent>%)`.
   - Include the proportional bar with `S`, `M`, `░`, and `O` segments.
   - Include the legend: `S=System  M=Messages  ░=Free  O=Output reserved`.
2. **Context Usage** table — columns: Metric, Value
   - Agent
   - Model
   - Context used
   - Context used %
   - Free space
   - Context window
3. **Estimated Usage By Category** table — columns: Category, Tokens, Percent
   - System prompt/tools/skills
   - Messages
   - Free space
   - Output reserved
4. **Session Totals** table — columns: Metric, Value
   - Total session tokens
   - Prompt/input tokens
   - Output tokens
   - Token updates/turns
   - Session created

For Codex current-session reports, include one short note after the category
table: Codex logs do not expose exact system/tool/skill/message category
counts, so system and messages are estimated from prompt deltas. Do not include
a "Command Used" section and do not paste the full per-turn breakdown unless the
user explicitly asks for it.

## Notes

- Token fields are normalized: Copilot reports `promptTokens`/`completionTokens`,
  Codex reports `input_tokens`/`output_tokens`/`reasoning_output_tokens`. The
  script maps both to unified `input_tokens` and `output_tokens`.
- Codex `reasoning_output_tokens` are included in `output_tokens` in the
  unified report.
- Session keys are prefixed with `copilot:` or `codex:` to avoid collisions.
- This skill replaces the separate `copilot-token-usage` and `codex-token-usage`
  skills with a single unified report.
