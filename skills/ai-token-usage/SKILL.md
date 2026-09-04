---
name: ai-token-usage
description: Report combined AI token usage from GitHub Copilot (VS Code extension), Codex (CLI + VS Code extension), Claude Code (CLI + VS Code extension), and OpenCode (SQLite) by reading local session logs. Also reports Qoder, CodeBuddy, TRAE, and CloudCode availability (token usage is tracked server-side for those). Shows total usage, per-agent (copilot/codex-cli/codex-vscode/claude-cli/claude-vscode/qoder/codebuddy/trae/opencode/cloudecode) breakdown, per-model breakdown, top sessions, and daily trending chart. Also supports a current-session context usage summary showing model, context window fill percentage, and per-turn token breakdown. Use when the user asks for AI token usage, daily token usage, monthly token usage, combined copilot + codex + claude-code + opencode usage, token statistics by agent or model, top sessions by tokens, current session token usage, context window usage, how much context is left, or wants a CSV/JSON/table report of AI agent token consumption.
---

# ai-token-usage

Report combined AI token usage from **Copilot** (VS Code extension),
**Codex** (CLI + VS Code extension), **Claude Code** (CLI + VS Code extension),
and **OpenCode** (SQLite) by reading local session logs. For **Qoder**,
**CodeBuddy**, **TRAE**, and **CloudCode**, the skill reports local-data
availability (these IDEs track usage server-side and do not persist token
counts locally).

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
| **OpenCode** (`opencode`) | `~/.local/share/opencode/opencode.db` (SQLite; `session` table holds per-session token counts + cost) |
| **Qoder** (`qoder`) | VS Code-derived IDE; no local token store — usage tracked server-side (Qoder web dashboard) |
| **CodeBuddy** (`codebuddy`) | VS Code-derived IDE; no local token store — usage tracked server-side (Tencent Cloud console) |
| **TRAE** (`trae`) | VS Code-derived IDE; no local token store — usage tracked server-side (TRAE web dashboard) |
| **CloudCode** (`cloudecode`) | CloudBase/CodeBuddy-family IDE; no documented local token store — usage tracked server-side (CloudBase console) |

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

# Generate chart images (multiple PNGs): chart_trend.png + one chart_pie_*.png
# per diagram, written next to the given base name (stem + _suffix.png).
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
| `--agent` | — | Filter: `copilot`, `codex` (all), `codex-cli`, `codex-vscode`, `claude-code` (all), `claude-cli`, `claude-vscode`, `qoder`, `codebuddy`, `trae`, `opencode`, or `cloudecode` |
| `--no-chart` | false | Skip the daily ASCII trend chart |
| `--chart-file PATH` | — | Save matplotlib chart images (multiple PNGs): `chart_trend.png` (4 trend panels) plus one `chart_pie_*.png` per diagram — `chart_pie_model.png`, and for the summary also `chart_pie_host_tokens/sessions/cost.png` and `chart_pie_agent_tokens/sessions/cost.png`. Files are written next to the given base name (stem + `_suffix.png`); the script prints every path |
| `--chart-width N` | 48 | Max bar width for ASCII trend chart |
| `--no-archived` | false | Skip Codex archived sessions |
| `--no-subagents` | false | Exclude Claude Code subagent sessions from token counts |
| `--current-session` | false | Show context usage for the current (most recent) Copilot, Codex, or Claude Code session |
| `--session-file` | — | Path to a specific session JSONL file (with `--current-session`) |
| `--currency` | CNY | Display currency for cost estimates: `USD`, `CNY`, or `RMB`. Default is CNY (RMB); the trend chart's cost panel is always RMB regardless. |
| `--output-dir` | `~/Desktop/ai-token-usage` | Target directory (created if missing). The data store and reports are both saved under this dir: `<output-dir>/data` and `<output-dir>/report/<timestamp>`. Resolved via CLI > env `AI_TOKEN_USAGE_ROOT` > `config.yaml` `output_dir` > built-in default. |
| `--no-save` | false | Do not write the `.md` report / chart image; print only. |
| `--data-dir` | `<output-dir>/data` | Persistent raw-data CSV store, co-located with the report under the target dir (NOT inside the skill). Merged across runs so history accumulates in `data/data.csv` + per-host/per-agent `data/<host>/<group>/data.csv`. |
| `--host` | local hostname | Machine label written on local rows in the data store. Same `session_key` from two hosts stays distinct. |
| `--import-data CSV [CSV ...]` | — | Merge one or more CSV files exported from OTHER machines into the store, then report across all machines. |
| `--import-host` | — | Machine label for every row imported via `--import-data` (e.g. `windows`). Overrides the file's own host column. Defaults to the file's host column / filename. |
| `--no-raw-data` | false | Do not update the persistent raw-data CSV store. |
| `--exclude-free` | false | Price free-tier models at $0 instead of their paid base rate (billable-only view). Default counts free models at their standard rate. |
| `--vscode-data` | auto | VS Code user-data directory |
| `--codex-home` | ~/.codex | Codex home directory |
| `--claude-projects-dir` | ~/.claude/projects | Claude Code projects directory |

### Configuring the output path

The output root is **user-configurable without editing code**, via
`configs/config.yaml` (`output_dir`) or the `AI_TOKEN_USAGE_ROOT` environment
variable. Resolution precedence (highest wins):

1. `--output-dir` (CLI flag, when explicitly passed)
2. env var `AI_TOKEN_USAGE_ROOT`
3. `configs/config.yaml` `output_dir` (user-editable)
4. built-in default `~/Desktop/ai-token-usage`

`data/` is co-located under this dir unless `--data-dir` overrides it. Edit
`config.yaml`, save, and re-run — no reinstall needed. This mirrors the
`ai-usage-report` skill's `data_root` / `AI_USAGE_ROOT` mechanism.

### Saved report file (default behavior)

In addition to printing to the terminal, the skill **always** writes a
persisted, dated report folder to `--output-dir` (default
**`~/Desktop/ai-token-usage`**). The folder is created if it does not exist.
**Each request gets its own folder**, named with the generation date and time
(`YYYY-MM-DD_HH-MM-SS`) so multiple runs never overwrite each other. The data
store and reports both live under this target dir (never inside the skill):

```
<output-dir>/
  data/                         # persistent raw-data store (see below)
    data.csv
    claudecode/data.csv
    opencode/data.csv
    copilot/data.csv
    ...
  report/<YYYY-MM-DD_HH-MM-SS>/
    summary/                    # combined (all agents) report
      report.md                 # fixed template, all agents merged
      chart_trend.png           # all 4 trend panels in ONE image
      chart_pie_model.png       # model usage share (own image)
      chart_pie_host_tokens.png # Host usage by Tokens (own image)
      chart_pie_host_sessions.png
      chart_pie_host_cost.png
      chart_pie_agent_tokens.png  # AI-agent usage by Tokens (own image)
      chart_pie_agent_sessions.png
      chart_pie_agent_cost.png
      raw/report-data.json      # full structured data for re-analysis
    <agent>/                    # one folder per agent group (e.g. opencode, claudecode, copilot)
      report.md                 # that agent's report (same template)
      chart_trend.png           # that agent's 4 trend panels (one image)
      chart_pie_model.png       # that agent's model share (own image)
```

- **`summary/report.md`** — a self-contained markdown report combining **all
  agents** using a **fixed template** (Summary → Usage by Agent → Usage by
  Model → Top N Sessions → Daily Usage → Charts → Notes) so every run is
  comparable. Cost is shown in the selected `--currency`.
- **Charts** (summary and per-agent) — generated as **separate PNG images**
  (one per diagram) with matplotlib (`declared` in `configs/apps.yaml`, profile
  `ai-token-usage`, so `scripts/init.py` installs it; if unavailable, the PNGs
  are skipped and the markdown notes the absence):
  - **`chart_trend.png`** — the 4 trend panels in a **single** image:
    1. Daily token usage **by model** (stacked),
    2. Daily **cost (RMB)**,
    3. Daily **sessions**,
    4. Daily **turns**.
  - **`chart_pie_model.png`** — **Model usage share** pie (its own image).
  - Summary only — each **host** / **AI-agent client** share pie gets **its own
    image**, split by Tokens / Sessions / RMB:
    `chart_pie_host_tokens.png`, `chart_pie_host_sessions.png`,
    `chart_pie_host_cost.png`, `chart_pie_agent_tokens.png`,
    `chart_pie_agent_sessions.png`, `chart_pie_agent_cost.png`.
  Every pie is a standalone image so it can be embedded or shared individually.
- **`summary/raw/report-data.json`** — the complete aggregated payload (daily,
  per-session, per-model, per-agent, `per_agent_model`, `daily_agent_model`,
  costs, tool availability) so you can run your own analyses or rebuild a
  report without re-scanning.
- **Per-agent folders** — `claude-cli` + `claude-vscode` are grouped into
  `claudecode`; `codex-cli` + `codex-vscode` into `codex`. Each gets its own
  `report.md` + `chart.png`.

Use `--no-save` to print only (e.g. for quick terminal checks), or point
`--output-dir` elsewhere to collect reports.

## Raw data store (persistent, merged)

Beyond the per-request report folder, every run also **persists the raw
per-session data** to `--data-dir` (default **`<output-dir>/data`**, i.e.
co-located with the report under the target dir — never inside the skill) so the
history survives across runs and can be re-analyzed later. This is independent of
`--no-save` — the store is updated even for terminal-only reports unless you
pass `--no-raw-data`.

Each run fetches all agent-client data and **merges** it into the existing
store, keyed by the composite `(host, session_key)` — `host` is the machine
label (default local hostname; override with `--host`), `session_key` is the
globally unique per-session id (e.g. `claude:<uuid>` / `opencode:<id>`). New
rows are appended; rows already present (same host + session) are updated in
place (their source logs are append-only, so values are stable). Re-running the
report a month later therefore accumulates the full history into the same files
without duplicates — and the same `session_key` from two different machines
never collides because the `host` column keeps them distinct.

Layout:

```
<data-dir>/
  data.csv                       # combined: every host AND agent merged into one file
  <masked-host>/                 # a machine, labelled with its (masked) real hostname
    claudecode/data.csv          # one CSV per agent group, nested under the host
    opencode/data.csv
    copilot/data.csv
    codex/data.csv
    ...
  ky#####in/                     # e.g. another machine merged in via --import-host kylin-win
    claudecode/data.csv
    ...
```

`data/data.csv` is the single merged file the request describes — it is the
union of all per-agent CSVs and is itself merged across runs. Columns
(`host` is first; the upsert key is `(host, session_key)`):

| Column | Meaning |
|--------|---------|
| `host` | Machine label (default local hostname; `--host` / `--import-host`) |
| `session_key` | Unique session id (part of the merge/upsert key) |
| `agent` | Raw agent label (e.g. `claude-cli`, `opencode`) |
| `agent_group` | Folder/group name (e.g. `claudecode`, `opencode`) |
| `model` | Model used by the session |
| `task` | First user task / title |
| `started_at` | Session start timestamp (ISO 8601) |
| `cwd` | Working directory of the session |
| `input_tokens` | Input tokens (incl. cache reads, full consumption) |
| `output_tokens` | Output tokens (incl. reasoning) |
| `total_tokens` | `input_tokens + output_tokens` |
| `cache_read_tokens` | Cache-read tokens (priced cheaper) |
| `turns` | Number of turns in the session |

You can point any spreadsheet or analysis tool at `data/data.csv`, or load a
single agent's history from `data/<group>/data.csv`. To rebuild the store from
scratch, delete `<data-dir>` and run the report again.

### Cross-machine merging

If you use several machines (e.g. a Mac and a Windows laptop), each machine
keeps its own local logs. To get one report that covers **all** of them, export
one machine's store CSV and merge it into the other:

```bash
# 1) On each machine, capture its own local data (store is merged + report saved)
python3 scripts/ai_token_usage.py --days 30

# 2) On the Windows laptop, copy its combined store to the Mac, e.g.
#    copy  <output-dir>/data/data.csv  ->  /tmp/win_data.csv  (via USB/cloud/ssh)

# 3) On the Mac, merge the Windows data, then report across BOTH machines
python3 scripts/ai_token_usage.py --import-data /tmp/win_data.csv --import-host windows --days 30
```

What happens on step 3:

- Every row from `/tmp/win_data.csv` is merged into the Mac's
  `<output-dir>/data/data.csv` (and its per-agent CSVs), tagged `host=windows`
  (`--import-host` overrides the file's own host column so you control the
  label). The merge key is `(host, session_key)`, so a session that happens to
  share an id across machines stays separate, and re-importing the same file is
  idempotent (updated in place, not duplicated).
- The Windows rows that fall inside the requested range are folded into the
  in-memory aggregation, so the report's totals, by-agent, by-model, and **by
  host** sections include every machine — not just the Mac.
- To label more than one foreign machine, run `--import-data` once per host
  (e.g. `--import-host windows`, then `--import-host linux`). Each contributes
  its own `host` value and rows.

The report shows a **Usage by host** table (table/chart/markdown/JSON) so you
can see per-machine token consumption at a glance. The `by_host` array is also
included in the JSON output and in `raw/report-data.json`.

```bash
# Default: prints table AND saves dated folder to ~/Desktop/ai-token-usage
python3 scripts/ai_token_usage.py --days 30

# Include opencode, claude-code, and copilot (default already scans all)
python3 scripts/ai_token_usage.py --days 30

# Save to a custom folder, no terminal chart
python3 scripts/ai_token_usage.py --days 30 --output-dir ~/reports --no-chart

# Print only, do not save
python3 scripts/ai_token_usage.py --days 7 --no-save
```

## Cost / Price estimation

The report estimates spend by multiplying token counts by each model's
per-1M-token price. Prices come from a **saved table**
(`references/pricing.json`), not from live calls at report time, so reports
stay offline and fast.

### Refreshing the price table (monthly)

`scripts/fetch_pricing.py` pulls the latest rates from each provider's
official pricing page and rewrites `references/pricing.json`. Schedule it
monthly, e.g.:

```bash
# cron: 0 9 1 * *  cd /path/to/skills/ai-token-usage && python3 scripts/fetch_pricing.py
python3 scripts/fetch_pricing.py            # refresh + write file
python3 scripts/fetch_pricing.py --check    # warn if file older than 35 days
python3 scripts/fetch_pricing.py --dry-run  # print, don't write
```

The saved table also stores the **USD→CNY exchange rate** (`fx.USD_CNY`),
best-effort fetched live and falling back to an embedded default.

### How cost is computed

- `opencode.py` / `codex.py` / `claude_code.py` route raw token fields through
  the shared `unify_tokens` helper so all clients count cache identically.
  Cache reads are tracked **separately** so they are priced at the cheaper
  cache-read rate instead of the standard input rate.
- `scripts/pricing.py` matches each model name (case-insensitive) against the
  saved table and returns an estimate. Resolution order:
  1. exact key in `references/pricing.json`;
  2. name contains a `free` token -> the same model without that token
     (`hy3-free` -> `hy3`, `deepseek-v4-flash-free` -> `deepseek-v4-flash`);
     a free model is therefore priced at its own model's rate, never at $0;
  3. longest substring match (`z-ai/glm-5.2` -> `glm-5.2`);
  4. **unknown model** -> the table's `fallback` entry (`auto` by default:
     USD 0.44 / 1.32 / 0.014 per 1M input / output / cache-read). Unknown
     usage is never silently valued at $0. Models priced this way are listed
     at the end of the terminal output and in `report.md`'s notes.
- A model that is explicitly free in the table (e.g. `glm-4.7-flash`,
  `input: 0`) keeps its $0 rate — that is its real list price. To count such a
  model at a paid sibling's rate, add `"priced_as": "<key>"` to its entry in
  `references/pricing.json` (e.g. `"priced_as": "glm-4.7-flashx"`).
- Point `fallback` at another key in `references/pricing.json` to change the
  rate used for unknown models.
- Default is `--currency CNY` (RMB); use `--currency USD` for US dollars.

```bash
python3 scripts/ai_token_usage.py --days 30 --currency CNY
python3 scripts/ai_token_usage.py --days 30 --format json --agent opencode
```

Cost is an **estimate**: providers bill cached tokens cheaper, and the saved
table's `input` rate is the standard (non-cached) list rate. Treat it as a
close approximation, not an invoice. Models that are not in the price table
are estimated at the `auto` fallback rates, so they contribute to the total
instead of being dropped.

## Other AI Coding Tools — Token UsageOpenCode token usage **is** tracked locally via its SQLite database. The other
VS Code-derived IDEs do not persist token counts in local files; this skill
reports their availability and points to the server-side dashboard.

| Tool | Local token logs? | Where usage is tracked |
|------|-------------------|------------------------|
| **OpenCode** | Yes — `~/.local/share/opencode/opencode.db` | Local SQLite (`session` table) — fully reported |
| **TRAE** (ByteDance) | No | TRAE web dashboard |
| **CodeBuddy** (Tencent Cloud) | No | Tencent Cloud console |
| **Qoder** (Alibaba) | No | Qoder web dashboard |
| **CloudCode** (CloudBase) | No | CloudBase console |

When you run a report, these IDEs appear under **Local token data
availability** at the bottom of the table output (and in the `tool_availability`
field of JSON output). Counts for them are `0` because no local token records
exist — that is expected, not a bug.

Claude Code token usage is tracked by this skill via `~/.claude/projects/` JSONL logs.

See the human manual [`docs/ai-token-usage.md`](../../../docs/ai-token-usage.md) § "Reference Guide" for details on
non-parseable tools (TRAE, CodeBuddy) and per-agent token calculation.

## Output sections (table format)

1. **Total summary box** — total/input/output tokens, turns, sessions (bordered with `====`)
2. **Usage by agent** — copilot vs codex totals with models used
3. **Usage by model** — per-model totals with agent info
4. **Top N sessions** — highest-token sessions with agent, model, task
5. **Daily usage table** — date, input, output, total, turns, sessions, agents
6. **Daily ASCII trend charts** — total, per-agent, per-model sub-charts
7. **Chart images** (if `--chart-file`) — `chart_trend.png` (4 trend panels) plus one `chart_pie_*.png` per diagram

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
2. After generation, the script prints every chart path. Open whichever
   image you want, e.g. `open /tmp/ai_token_usage_<range>_trend.png` (the
   combined trend panels) or any `chart_pie_*.png` (a single pie diagram).
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
