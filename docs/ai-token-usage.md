# ai-token-usage — Manual

Report combined AI token usage by reading local session JSONL logs from
**Copilot**, **Codex**, **Claude Code**, and **OpenCode**, then summarize
totals, per-agent and per-model breakdowns, top sessions, and a daily trend
chart.

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
| OpenCode | `~/.local/share/opencode/opencode.db` (SQLite) |

Tools without local logs (qoder, codebuddy, trae, cloudecode) report an
availability note instead of fabricated numbers; check their provider dashboard
for authoritative usage.

## What Problem It Solves

AI usage data is scattered across many local tools (Copilot, Codex, Claude Code,
OpenCode, plus other AI coding IDEs). Users need one place to understand total
usage, model usage, trends, and current-session context consumption.

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
| `--currency` | CNY | Cost display currency: `USD`, `CNY`, or `RMB` (default CNY/RMB; chart cost panel is always RMB) |
| `--output-dir` | `~/Desktop/ai-token-usage` | Directory for the saved `.md` report + trend chart PNG (created if missing). Each run gets its own per-request subfolder named `YYYY-MM-DD_HHMMSS` |
| `--no-save` | false | Do not write the `.md` report / chart image; print only |
| `--data-dir` | `<skill>/data` | Persistent raw-data CSV store (created if missing). Merged across runs so history accumulates in `data/data.csv` + per-agent `data/<group>/data.csv` |
| `--host` | local hostname | Machine label written on local rows in the data store (keeps same `session_key` from two hosts distinct) |
| `--import-data CSV [CSV ...]` | — | Merge CSV file(s) exported from OTHER machines into the store, then report across all machines |
| `--import-host` | — | Machine label for every row imported via `--import-data` (e.g. `windows`); overrides the file's host column. Defaults to the file's host / filename |
| `--no-raw-data` | false | Do not update the persistent raw-data CSV store |
| `--exclude-free` | false | Price free-tier models at $0 instead of their paid base rate (billable-only view). Default counts free models at their standard rate |

## Cost / Price Estimation

The report can estimate spend by multiplying token counts by each model's
per-1M-token price, read from the saved table **`skills/ai-token-usage/references/pricing.json`**
(no live calls at report time).

- All four parsers route token fields through the shared `unify_tokens` helper
  so cache handling is consistent; cache reads are priced at the cheaper
  cache-read rate.
- **Free-tier models are priced at their own model's rate, not at $0.** A model
  whose name carries a `free` token (e.g. `deepseek-v4-flash-free`,
  `hy3-free`, `mimo-v2.5-free`) is priced using the same model without that
  token (`deepseek-v4-flash`, `hy3`, `mimo-v2.5`), so a free promotion still
  contributes real cost to the usage assessment. Tokens for free models are
  always counted regardless. Use `--exclude-free` to zero free-tier models
  (price them at $0) for a billable-only "final cost" view.
  A model that is *explicitly* free in `pricing.json` (e.g. `glm-4.7-flash`,
  `input: 0`) keeps its $0 rate — that is its real list price. To count it at a
  paid sibling's rate instead, add `"priced_as": "<key>"` to its entry.
- **Unknown models fall back to the `auto` rates instead of being skipped.**
  A model with no entry and no substring match in `references/pricing.json` is
  priced with the table's `fallback` entry (`auto` by default: USD 0.44 / 1.32 /
  0.014 per 1M input / output / cache-read, i.e. deepseek-v4-flash rates), so
  its usage is never silently valued at $0. This includes sessions where the
  parser could not detect the model name (shown as `unknown`).
  Models priced this way are named at the end of the terminal output and in
  `report.md`'s notes; change the rate by editing the `auto` entry, or point
  `fallback` at a different key in `references/pricing.json`.
- Some models are priced from a **reseller** rather than the original vendor:
  `hy3` and `mimo-v2.5` use **Tencent Cloud TokenHub** RMB rates (converted to
  USD via `fx` so the RMB display is exact). If your DeepSeek/GLM traffic also
   goes through TokenHub, tell the skill which SKU (standard vs first-party/
   direct-supply, peak vs idle) so those rates can be aligned — they differ from
   the direct list rates.
- **Cost is computed from the real input / output / cache-read split**, not a
  blended per-token rate. Daily cost (chart panel) and per-session cost both use
  each day's/session's exact split, so the large price gap between cached
  tokens (e.g. $0.014/M) and output tokens (e.g. $1.32–4.4/M) is reflected
  correctly. Cached tokens are far cheaper, so this matters a lot.
- Refresh the price table monthly:

  ```bash
  python3 skills/ai-token-usage/scripts/fetch_pricing.py        # refresh
  python3 skills/ai-token-usage/scripts/fetch_pricing.py --check # warn if >35 days old
  ```

  The saved table also stores the USD→CNY exchange rate (`fx.USD_CNY`,
  best-effort live, embedded fallback).
- Pick the display currency:

  ```bash
  python3 skills/ai-token-usage/scripts/ai_token_usage.py --days 30 --currency CNY
  ```

Cost is an **estimate**, not an invoice: cached tokens are cheaper than the
standard input rate used in the saved table.

## Saved Report File (default)

Besides terminal output, the skill **always** writes a persisted, dated report
folder to `--output-dir` (default **`~/Desktop/ai-token-usage`**; created if
missing). **Each request gets its own folder**, named with the generation date
and time (`YYYY-MM-DD_HHMMSS`) so multiple runs never overwrite each other.
Layout:

```
<output-dir>/<YYYY-MM-DD_HHMMSS>/
  report.md            # all agents (root), fixed template
  chart.png            # 5-panel trend chart
  raw/report-data.json # full structured data for re-analysis
  <agent>/             # one folder per agent group (opencode, claudecode, copilot, ...)
    report.md
    chart.png
```

- Root `report.md` uses a fixed template (Summary → Usage by Agent → Usage by
  Model → Top N Sessions → Daily Usage → Trend Chart → Notes) so every run is
  directly comparable.
- `chart.png` (root and per-agent) has 5 panels: daily tokens **by model**
  (stacked), daily **cost (RMB)**, daily **sessions**, daily **turns**, and a
  **model usage share** pie. Needs matplotlib; skipped if unavailable. The cost
  panel is exact (see cost note above) and always in RMB.
- `raw/report-data.json` holds the complete aggregated payload for custom
  analysis, including per-session costs and these daily breakdowns (each model
  entry keeps the **`input` / `output` / `cache`** token split):
  - `daily_agent_model`: date → agent → model → `{input, output, cache}`
  - `daily_model`: date → model → `{input, output, cache}`
  - `daily_agent`: date → agent → total tokens
  - `daily`, `per_agent_model`, `by_model`, `by_agent`, `per_session`, etc.
- Per-agent folders group `claude-cli`+`claude-vscode` → `claudecode` and
  `codex-cli`+`codex-vscode` → `codex`.

Use `--no-save` for terminal-only output, or `--output-dir` to redirect.

## Raw Data Store (persistent, merged)

Beyond the per-request report folder, every run also **persists the raw
per-session data** to `--data-dir` (default **`<skill>/data`**) so the history
survives across runs and can be re-analyzed later. This is independent of
`--no-save` — the store is updated even for terminal-only reports unless you
pass `--no-raw-data`.

Each run fetches all agent-client data and **merges** it into the existing
store, keyed by `session_key` (globally unique per session, e.g.
`claude:<uuid>` / `opencode:<id>`). New sessions are appended; sessions already
present are updated in place (their source logs are append-only, so values are
stable). Re-running the report a month later therefore accumulates the full
history into the same files without duplicates.

Layout:

```
<data-dir>/
  data.csv              # combined: every agent merged into one file
  claudecode/data.csv   # one CSV per agent group
  opencode/data.csv
  copilot/data.csv
  codex/data.csv
  qoder/data.csv        # (availability-only agents still get a folder)
  ...
```

`data/data.csv` is the single merged file — the union of all per-agent CSVs and
itself merged across runs. Columns: `session_key`, `agent`, `agent_group`,
`model`, `task`, `started_at`, `cwd`, `input_tokens`, `output_tokens`,
`total_tokens`, `cache_read_tokens`, `turns`. Point any spreadsheet or analysis
tool at `data/data.csv`, or load one agent's history from
`data/<group>/data.csv`. To rebuild the store from scratch, delete
`<data-dir>` and run the report again.

### Cross-machine merging

If you use several machines (e.g. a Mac and a Windows laptop), each keeps its
own local logs. To get one report covering **all** of them, export one
machine's store CSV and merge it into the other. The store's merge key is the
composite `(host, session_key)`, and every row carries a `host` column (default
local hostname; override with `--host` / `--import-host`), so the same
`session_key` from two machines never collides.

```bash
# 1) On each machine, capture its own local data (store merged + report saved)
python3 scripts/ai_token_usage.py --days 30

# 2) Copy the Windows machine's combined store to the Mac, e.g.
#    <skill>/data/data.csv  ->  /tmp/win_data.csv  (USB / cloud / ssh)

# 3) On the Mac, merge the Windows data, then report across BOTH machines
python3 scripts/ai_token_usage.py --import-data /tmp/win_data.csv --import-host windows --days 30
```

On step 3 every row from `/tmp/win_data.csv` is merged into the Mac's
`data/data.csv` (and per-agent CSVs) tagged `host=windows`; re-importing the
same file is idempotent (updated in place, not duplicated). Windows rows inside
the range are folded into the aggregation so the report's totals, by-agent,
by-model, and **by host** sections include every machine. The report shows a
**Usage by host** table; JSON output and `raw/report-data.json` include a
`by_host` array. For more than one foreign machine, run `--import-data` once per
host (e.g. `--import-host windows`, then `--import-host linux`).

## When To Use It

Use this skill when the user asks for AI token usage, Copilot usage, Codex usage,
Claude Code usage, OpenCode usage, daily or monthly trends, model breakdowns, or
current context usage.

Do not use it for billing guarantees; it reads local logs and may not match
provider billing exactly.

## How To Use This Skill

Ask for a time range, agent filter, output format, or current-session report.

Example requests:

```text
Show my AI token usage for the last 30 days.
```

```text
Export Copilot vs Codex token usage to CSV for the past week.
```

```text
Show my current opencode session context usage.
```

## Example Usage

The user asks for the last 7 days. The agent reads local logs, groups usage by
day and model, prints the summary table, and saves a chart when requested.

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


## Reference Guide (merged from skill references)

### Agents Covered

The skill collects token usage from five products across four agent categories:

| Agent Label | Source | Description |
|-------------|--------|-------------|
| **copilot** | GitHub Copilot VS Code extension | Chat sessions inside VS Code — workspace sessions and empty-window sessions |
| **copilot** | Copilot CLI (`copilot` command) | A shim into the VS Code Copilot extension — shares the same session logs, so reported under `copilot` |
| **codex-cli** | Codex CLI (`codex_exec`, `codex_cli_rs`, `codex-tui`) | Terminal-based Codex sessions launched from the command line |
| **codex-vscode** | Codex VS Code extension (`codex_vscode`) | Codex sessions launched from the VS Code sidebar/panel |
| **codex-vscode** | Codex Desktop app (`Codex Desktop`) | Standalone Codex desktop application — shares log path with Codex VS Code extension |
| **codex** | (filter alias) | When used with `--agent codex`, includes both `codex-cli` and `codex-vscode` |
| **claude-cli** | Claude Code CLI | Terminal-based Claude Code sessions launched via `claude` command (`entrypoint: "claude"`) |
| **claude-vscode** | Claude Code VS Code extension | Claude Code sessions launched from the VS Code sidebar/panel (`entrypoint: "claude-vscode"`) |
| **claude-code** | (filter alias) | When used with `--agent claude-code`, includes both `claude-cli` and `claude-vscode` (including subagents by default) |

### Other AI Coding Tools — Token Usage Tracking

The following popular AI coding tools do **not** write parseable local token-usage logs the way Copilot and Codex do. This section documents what is known about each tool's token tracking approach.

#### Claude Code (Anthropic) — ✅ NOW TRACKED

| Item | Detail |
|------|--------|
| **Type** | CLI + VS Code extension (`claude`, `claude-vscode`) |
| **Local data dir** | `~/.claude/projects/` |
| **Session files** | `~/.claude/projects/<project-slug>/<uuid>.jsonl` — per-turn token usage in `type: "assistant"` records |
| **Subagent files** | `~/.claude/projects/<project-slug>/<uuid>/subagents/agent-<id>.jsonl` — subagent token usage |
| **Token format** | Per-turn (non-cumulative) `message.usage.input_tokens` / `message.usage.output_tokens` |
| **Entrypoint** | `entrypoint` field: `"claude"` (CLI) or `"claude-vscode"` (VS Code) |
| **Model** | `message.model` field in assistant records |
| **Session cleanup** | `cleanupPeriodDays` setting (default 30) deletes old session files |

#### TRAE (ByteDance)

| Item | Detail |
|------|--------|
| **Type** | AI IDE (VS Code fork) + TRAE SOLO (web/desktop/mobile) |
| **Platform** | Standalone IDE application; also available as a VS Code plugin |
| **Local data dir** | Not documented publicly; similar to VS Code's `~/Library/Application Support/Trae/` on macOS (when installed) |
| **Token tracking** | Usage and billing managed via the TRAE web dashboard ("Plans & billing" / "Dashboard" pages). No public documentation of local JSONL/JSON token log format. |
| **Why not parseable** | TRAE is a closed-source IDE that handles usage tracking server-side. No local session log format has been documented or discovered. |

#### CodeBuddy (Tencent Cloud)

| Item | Detail |
|------|--------|
| **Type** | VS Code / JetBrains / Visual Studio extension (`Tencent-Cloud.coding-copilot`) |
| **Models** | Powered by Tencent Hunyuan + DeepSeek + GLM multi-turn models |
| **Installs** | ~465K (VS Code Marketplace) |
| **Local data dir** | Not documented publicly; extension stores data in VS Code's `globalStorage` |
| **Token tracking** | Usage managed via Tencent Cloud console. Free tier available. No public documentation of local token-usage log format. |
| **Why not parseable** | CodeBuddy is a cloud-service extension — token accounting happens server-side. No local session log files with per-turn token counts have been documented. |

#### Summary: Parseable vs Non-Parseable

| Tool | Local Token Logs | Tracking Method |
|------|-----------------|-----------------|
| GitHub Copilot | ✅ JSONL with per-turn `usage`/`metadata` | Local log files (this skill) |
| Codex (CLI + VS Code) | ✅ JSONL with cumulative `token_count` events | Local log files (this skill) |
| Claude Code (CLI + VS Code) | ✅ JSONL with per-turn `assistant` records | Local log files (this skill) |
| TRAE | ❌ No local token data | Web dashboard |
| CodeBuddy | ❌ No local token data | Tencent Cloud console |

---

The Codex sub-agent is determined by the `originator` field in the `session_meta` event:

| `originator` value | Agent label |
|--------------------|-------------|
| `codex_exec` | codex-cli |
| `codex_cli_rs` | codex-cli |
| `codex-tui` | codex-cli |
| `codex_vscode` | codex-vscode |
| `Codex Desktop` | codex-vscode |

#### Log Locations

| Agent | Platform | Path |
|-------|----------|------|
| Copilot (workspace) | macOS | `~/Library/Application Support/Code/User/workspaceStorage/*/chatSessions/*.jsonl` |
| Copilot (workspace) | Linux | `~/.config/Code/User/workspaceStorage/*/chatSessions/*.jsonl` |
| Copilot (workspace) | Windows | `%APPDATA%/Code/User/workspaceStorage/*/chatSessions/*.jsonl` |
| Copilot (empty window) | macOS | `~/Library/Application Support/Code/User/globalStorage/emptyWindowChatSessions/*.jsonl` |
| Copilot (empty window) | Linux | `~/.config/Code/User/globalStorage/emptyWindowChatSessions/*.jsonl` |
| Copilot (empty window) | Windows | `%APPDATA%/Code/User/globalStorage/emptyWindowChatSessions/*.jsonl` |
| Codex CLI + VS Code (active) | All | `~/.codex/sessions/**/*.jsonl` |
| Codex CLI + VS Code (archived) | All | `~/.codex/archived_sessions/*.jsonl` |
| Claude Code CLI + VS Code | All | `~/.claude/projects/<project-slug>/*.jsonl` |
| Claude Code subagents | All | `~/.claude/projects/<project-slug>/*/subagents/agent-*.jsonl` |

---

### How Token Usage Is Calculated

#### Copilot (VS Code Extension)

Each Copilot session is stored as a JSONL file with an initial full-state record followed by incremental update records.

**Step 1 — Session metadata extraction:**
- The first line (`kind: 0` or `kind: "v"`) contains the initial record.
- Extracts: `sessionId`, `creationDate` (epoch ms), and `selectedModel` metadata (model name, `maxInputTokens`, `maxOutputTokens`).

**Step 2 — Token extraction from the initial record:**
- Iterates over `v.requests[].result` objects in the first line.
- For each result, looks for tokens in two places (in order):
  1. `result.usage.promptTokens` / `result.usage.completionTokens`
  2. `result.metadata.promptTokens` / `result.metadata.outputTokens` (fallback)
- Each result with non-zero tokens counts as one **turn**.

**Step 3 — Token extraction from incremental records:**
- Subsequent JSONL lines (`kind: 1`) with `k = ["requests", ..., "result"]` contain per-turn usage.
- Same two-step extraction as above (`usage` then `metadata` fallback).
- Model changes are tracked via records where `k` contains `"selectedModel"`.

**Calculation formula per turn:**
```
input_tokens  = promptTokens
output_tokens = completionTokens (or outputTokens from metadata)
total_tokens  = input_tokens + output_tokens
```

#### Codex (CLI + VS Code Extension)

Both Codex CLI and Codex VS Code extension write to the same `~/.codex/sessions/` directory using the same JSONL event format. They are distinguished by the `originator` field in the `session_meta` event.

Each Codex session is a JSONL file containing structured events.

**Step 1 — Session metadata extraction:**
- `type: "session_meta"` → session ID, timestamp, working directory, **`originator`** (used to classify as `codex-cli` or `codex-vscode`)
- `type: "turn_context"` → model name

**Step 2 — Token extraction via cumulative totals with delta calculation:**
- Codex logs cumulative token counts in `type: "event_msg"` events where `payload.type = "token_count"`.
- Each such event contains `payload.info.total_token_usage` with fields:
  - `input_tokens`
  - `cached_input_tokens`
  - `output_tokens`
  - `reasoning_output_tokens`
  - `total_tokens`
- To avoid double-counting, the script computes **positive deltas** between consecutive `total_token_usage` snapshots.

**Calculation formula per turn:**
```
delta = current_total_token_usage - previous_total_token_usage  (per field, clamped to ≥ 0)

input_tokens  = delta.input_tokens
output_tokens = delta.output_tokens + delta.reasoning_output_tokens
total_tokens  = input_tokens + output_tokens
```

**Task extraction:**
- From `event_msg` with `payload.type = "user_message"` → `payload.message`
- From `response_item` with `role = "user"` → concatenated `input_text` content parts
- Strips Codex-internal markers like `## My request for Codex:` and environment context blocks.

---

#### Claude Code (CLI + VS Code Extension)

Claude Code stores per-turn (non-cumulative) token usage in `~/.claude/projects/`.

**Step 1 — Session identity:**
- `sessionId` (UUID) ties all records in a session together.
- `entrypoint` distinguishes CLI (`"claude"`) from VS Code (`"claude-vscode"`).
- Subagents identified by `attributionAgent` field (e.g., "Explore", "Plan") and file location.

**Step 2 — Token extraction (per-turn):**
- Each `type: "assistant"` record contains `message.usage` with `input_tokens` and `output_tokens`.
- Unlike Codex, Claude Code records are per-turn (not cumulative), so no delta calculation is needed.

**Calculation formula per turn:**
```
input_tokens  = message.usage.input_tokens
output_tokens = message.usage.output_tokens
total_tokens  = input_tokens + output_tokens
```

**Task extraction:**
- Main sessions: join all `message.content[].text` from the first `type: "user"` record.
- Subagents: join single-character strings from `message.content[]` of the first user record.
- Prefix with `[<attributionAgent>]` for subagent tasks.

**Session key format:**
- Main: `claude:<sessionId>`
- Subagent: `claude:<sessionId>/<agent_id>`

**Agent label mapping:**
| `entrypoint` value | Agent label |
|--------------------|-------------|
| `claude` | claude-cli |
| `claude-vscode` | claude-vscode |

---

### Aggregation Buckets

All turns (from all agents) are aggregated into four dimensions:

| Bucket | Key | Purpose |
|--------|-----|---------|
| **Daily** | date string (`YYYY-MM-DD`) | Daily totals for trend charts |
| **Per-session** | `copilot:<sessionId>`, `codex:<filename>`, or `claude:<sessionId>` | Top-N session ranking |
| **Per-model** | model name (e.g. `claude opus 4`, `deepseek-v4-pro`) | Model breakdown |
| **Per-agent** | `copilot`, `codex-cli`, `codex-vscode`, `claude-cli`, or `claude-vscode` | Agent comparison |

Each bucket tracks: `input_tokens`, `output_tokens`, `total_tokens`, `turns`, `sessions` (set), `models` (set), `agents` (set).

---

### Current-Session Context Analysis

When `--current-session` is used, the skill analyzes the most recently modified session file and computes a context window breakdown.

#### Copilot Current-Session

| Metric | Source |
|--------|--------|
| Model name | `v.inputState.selectedModel.metadata.name` |
| Max input tokens | `v.inputState.selectedModel.metadata.maxInputTokens` |
| Max output tokens | `v.inputState.selectedModel.metadata.maxOutputTokens` |
| System overhead | First turn's `promptTokens` (includes system prompt, tools, skills, instructions) |
| Messages | `last_prompt_tokens - system_overhead_tokens` |
| Free space | `max_input_tokens - last_prompt_tokens` |

#### Codex Current-Session

| Metric | Source |
|--------|--------|
| Model name | `turn_context.payload.model` |
| Context window | `payload.info.model_context_window` |
| Current context | `payload.info.last_token_usage.input_tokens` |
| System overhead | Estimated from first turn's prompt delta |

Note: Codex logs do not expose exact system/tool/skill/message category counts; system and messages are estimated from prompt deltas.

#### Claude Code Current-Session

| Metric | Source |
|--------|--------|
| Model name | `message.model` from first assistant record |
| Context window | Looked up from known model table (Claude Code does not persist `model_context_window` in logs) |
| Current context | Last turn's `message.usage.input_tokens` |
| System overhead | Estimated from first turn's prompt tokens |

Note: Claude Code logs do not expose exact system/tool/skill/message category counts; system overhead estimated from first turn prompt.

#### Full Context Window Lookup

The script maintains a lookup table for known model context windows:

| Model | Full Context Window |
|-------|-------------------|
| Claude Opus 4 | 200,000 |
| Claude Sonnet 4 | 200,000 |
| Claude 3.5 Sonnet | 200,000 |
| Claude 3 Opus | 200,000 |
| GPT-4o | 128,000 |
| GPT-4.1 | 1,047,576 |
| GPT-4 | 128,000 |
| o3-mini | 200,000 |
| o4-mini | 200,000 |
| Gemini 2.5 Pro | 1,048,576 |
| Gemini 2.0 Flash | 1,048,576 |
| DeepSeek-V4-Pro | 1,048,576 |
| DeepSeek-V4-Flash | 1,048,576 |

**Context breakdown formula:**
```
full_context_window = known_window OR (max_input_tokens + max_output_tokens)
output_reserved     = full_context_window - max_input_tokens
used_total          = last_prompt_tokens + output_reserved
used_pct            = used_total / full_context_window × 100
```

The ASCII bar diagram segments:
- `S` = System prompt (tools + skills + instructions)
- `M` = Messages (conversation history)
- `░` = Free space
- `O` = Output reserved

---

### Date Filtering

- **Default**: last 30 days
- `--since` / `--until`: custom date range (inclusive, `YYYY-MM-DD`)
- `--days N`: last N days from today
- Copilot: uses `creationDate` from the session's initial record
- Codex: uses per-event `timestamp` field
- Claude Code: uses per-record `timestamp` field from assistant records

Only turns whose timestamp falls within `[start, end)` are counted.

---

### Output Formats

| Format | Sections |
|--------|----------|
| **table** | Total summary box, usage by agent, usage by model, top N sessions, daily usage table, ASCII trend charts, optional PNG chart |
| **csv** | Daily rows + TOTAL row (date, input, output, total, turns, sessions, agents) |
| **json** | Full structured payload: metadata, daily, total, by_agent, by_model, top_sessions |

## Related Skill File

See [`SKILL.md`](../skills/ai-token-usage/SKILL.md) for the agent-facing
execution rules.
