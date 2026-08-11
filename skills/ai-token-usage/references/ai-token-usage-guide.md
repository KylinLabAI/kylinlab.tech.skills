# ai-token-usage — Reference Guide

## Agents Covered

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

## Other AI Coding Tools — Token Usage Tracking

The following popular AI coding tools do **not** write parseable local token-usage logs the way Copilot and Codex do. This section documents what is known about each tool's token tracking approach.

### Claude Code (Anthropic) — ✅ NOW TRACKED

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

### TRAE (ByteDance)

| Item | Detail |
|------|--------|
| **Type** | AI IDE (VS Code fork) + TRAE SOLO (web/desktop/mobile) |
| **Platform** | Standalone IDE application; also available as a VS Code plugin |
| **Local data dir** | Not documented publicly; similar to VS Code's `~/Library/Application Support/Trae/` on macOS (when installed) |
| **Token tracking** | Usage and billing managed via the TRAE web dashboard ("Plans & billing" / "Dashboard" pages). No public documentation of local JSONL/JSON token log format. |
| **Why not parseable** | TRAE is a closed-source IDE that handles usage tracking server-side. No local session log format has been documented or discovered. |

### CodeBuddy (Tencent Cloud)

| Item | Detail |
|------|--------|
| **Type** | VS Code / JetBrains / Visual Studio extension (`Tencent-Cloud.coding-copilot`) |
| **Models** | Powered by Tencent Hunyuan + DeepSeek + GLM multi-turn models |
| **Installs** | ~465K (VS Code Marketplace) |
| **Local data dir** | Not documented publicly; extension stores data in VS Code's `globalStorage` |
| **Token tracking** | Usage managed via Tencent Cloud console. Free tier available. No public documentation of local token-usage log format. |
| **Why not parseable** | CodeBuddy is a cloud-service extension — token accounting happens server-side. No local session log files with per-turn token counts have been documented. |

### Summary: Parseable vs Non-Parseable

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

### Log Locations

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

## How Token Usage Is Calculated

### Copilot (VS Code Extension)

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

### Codex (CLI + VS Code Extension)

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

### Claude Code (CLI + VS Code Extension)

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

## Aggregation Buckets

All turns (from all agents) are aggregated into four dimensions:

| Bucket | Key | Purpose |
|--------|-----|---------|
| **Daily** | date string (`YYYY-MM-DD`) | Daily totals for trend charts |
| **Per-session** | `copilot:<sessionId>`, `codex:<filename>`, or `claude:<sessionId>` | Top-N session ranking |
| **Per-model** | model name (e.g. `claude opus 4`, `deepseek-v4-pro`) | Model breakdown |
| **Per-agent** | `copilot`, `codex-cli`, `codex-vscode`, `claude-cli`, or `claude-vscode` | Agent comparison |

Each bucket tracks: `input_tokens`, `output_tokens`, `total_tokens`, `turns`, `sessions` (set), `models` (set), `agents` (set).

---

## Current-Session Context Analysis

When `--current-session` is used, the skill analyzes the most recently modified session file and computes a context window breakdown.

### Copilot Current-Session

| Metric | Source |
|--------|--------|
| Model name | `v.inputState.selectedModel.metadata.name` |
| Max input tokens | `v.inputState.selectedModel.metadata.maxInputTokens` |
| Max output tokens | `v.inputState.selectedModel.metadata.maxOutputTokens` |
| System overhead | First turn's `promptTokens` (includes system prompt, tools, skills, instructions) |
| Messages | `last_prompt_tokens - system_overhead_tokens` |
| Free space | `max_input_tokens - last_prompt_tokens` |

### Codex Current-Session

| Metric | Source |
|--------|--------|
| Model name | `turn_context.payload.model` |
| Context window | `payload.info.model_context_window` |
| Current context | `payload.info.last_token_usage.input_tokens` |
| System overhead | Estimated from first turn's prompt delta |

Note: Codex logs do not expose exact system/tool/skill/message category counts; system and messages are estimated from prompt deltas.

### Claude Code Current-Session

| Metric | Source |
|--------|--------|
| Model name | `message.model` from first assistant record |
| Context window | Looked up from known model table (Claude Code does not persist `model_context_window` in logs) |
| Current context | Last turn's `message.usage.input_tokens` |
| System overhead | Estimated from first turn's prompt tokens |

Note: Claude Code logs do not expose exact system/tool/skill/message category counts; system overhead estimated from first turn prompt.

### Full Context Window Lookup

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

## Date Filtering

- **Default**: last 30 days
- `--since` / `--until`: custom date range (inclusive, `YYYY-MM-DD`)
- `--days N`: last N days from today
- Copilot: uses `creationDate` from the session's initial record
- Codex: uses per-event `timestamp` field
- Claude Code: uses per-record `timestamp` field from assistant records

Only turns whose timestamp falls within `[start, end)` are counted.

---

## Output Formats

| Format | Sections |
|--------|----------|
| **table** | Total summary box, usage by agent, usage by model, top N sessions, daily usage table, ASCII trend charts, optional PNG chart |
| **csv** | Daily rows + TOTAL row (date, input, output, total, turns, sessions, agents) |
| **json** | Full structured payload: metadata, daily, total, by_agent, by_model, top_sessions |
