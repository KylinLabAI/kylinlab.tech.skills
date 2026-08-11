---
name: ai-agent-auto-approve
description: Configure AI coding agents for fully autonomous operation — auto-approve all permissions so the agent runs without user interaction. Supports GitHub Copilot (VS Code), Claude Code (CLI), OpenAI Codex (CLI), Cursor, Aider (CLI), Cline (VS Code), Roo Code (VS Code), and Windsurf (Cascade). Auto-detects which agent is active, or the user can specify. Use when the user says "auto approve", "autonomous agent", "no prompts", "agent auto approve", "skip approval", "run without confirmation", "copilot auto approve", "claude code autonomous", "codex full auto", "cursor auto approve", "aider yes always", "cline yolo mode", "roo code auto approve", "windsurf auto approve", or wants the AI agent to run without user interaction.
---

# AI Agent Auto-Approve Setup

Configure AI coding agents for fully autonomous operation — no permission prompts for running commands, editing files, or accessing external folders.

Supports: **GitHub Copilot** | **Claude Code** | **OpenAI Codex** | **Cursor** | **Aider** | **Cline** | **Roo Code** | **Windsurf**

> **Reference:** See `references/ai-agent-auto-approve-guide.md` for a comprehensive guide with detailed settings, security considerations, and comparison matrix.

## Auto-Detection

When the user asks to enable auto-approve without specifying an agent, detect the environment:

1. **Check the current editor/runtime:**
   - If running inside **VS Code** with Copilot Chat → use **GitHub Copilot** config
   - If running inside **VS Code** with Cline extension → use **Cline** config
   - If running inside **VS Code** with Roo Code extension → use **Roo Code** config
   - If running inside **Cursor** editor → use **Cursor** config
   - If running inside **Windsurf** editor → use **Windsurf** config
   - If running as **Claude Code CLI** (`claude` command) → use **Claude Code** config
   - If running as **OpenAI Codex CLI** (`codex` command) → use **Codex** config
   - If running as **Aider CLI** (`aider` command) → use **Aider** config
2. **Detection hints:**
   - `$TERM_PROGRAM` = `vscode` → VS Code (check for Copilot, Cline, or Roo Code based on extensions)
   - `$CURSOR_SESSION` or Cursor-specific env vars → Cursor
   - `$WINDSURF_SESSION` or Windsurf-specific env vars → Windsurf
   - Parent process = `claude` → Claude Code
   - Parent process = `codex` → OpenAI Codex
   - Parent process = `aider` → Aider
3. **If ambiguous**, ask the user which agent they want to configure.

> **Warning:** Auto-approve gives the agent full autonomy to run any terminal command and modify any file. Only enable in trusted environments.

---

## 1. GitHub Copilot (VS Code)

### Settings Reference

| Setting | Type | Purpose |
|---------|------|---------|
| `chat.tools.global.autoApprove` | `boolean` | **Critical** — set to `true` to auto-approve all tool invocations (terminal, file edits, etc.) globally |
| `chat.agent.autoApprove` | `boolean` | Master switch — auto-approve ALL agent actions |
| `chat.agent.autoApprove.terminalCommands` | `boolean` | Auto-approve terminal/shell command execution |
| `chat.agent.autoApprove.outsideWorkspace` | `boolean` | Allow reading/editing files outside the workspace |
| `chat.commandApproval.enabled` | `boolean` | Set to `false` to disable the command approval dialog |
| `chat.tools.terminal.autoApprove` | `object` | Per-command overrides (optional — see below) |

> **Note:** `chat.tools.global.autoApprove` is the key setting that controls whether VS Code shows approval prompts for tool invocations. Even with `chat.agent.autoApprove` set to `true`, VS Code may still show approval prompts unless `chat.tools.global.autoApprove` is explicitly set to `true`. Always include this setting.

#### About `chat.tools.terminal.autoApprove`

This optional setting provides **per-command granular control** over which terminal commands are auto-approved. It is an object where keys are command names (or regex patterns) and values are `true`/`false`.

- **If this setting is absent**, the three master switches above control everything — all commands are auto-approved when the master switches are `true`.
- **If this setting is present**, it **overrides** the master switches for specific commands. A `false` entry blocks that command even if `chat.agent.autoApprove.terminalCommands` is `true`.

**For full auto-approve: do NOT include `chat.tools.terminal.autoApprove`** — just use the three master switches. Adding this setting introduces per-command exceptions.

Example of granular control (approve most, block destructive commands):

```json
{
  "chat.tools.terminal.autoApprove": {
    "ls": true,
    "cat": true,
    "grep": true,
    "rm": false,
    "kill": false,
    "/^git\\s+push\\b/": false
  }
}
```

Keys can be plain command names or regex patterns wrapped in `/pattern/`. Regex patterns are matched against the full command string.

### Setup

#### Option A: Settings JSON

1. `Cmd + Shift + P` → **"Preferences: Open User Settings (JSON)"**
2. Add:

```json
{
  "chat.tools.global.autoApprove": true,
  "chat.agent.autoApprove": true,
  "chat.agent.autoApprove.terminalCommands": true,
  "chat.agent.autoApprove.outsideWorkspace": true,
  "chat.commandApproval.enabled": false
}
```

3. Save (`Cmd + S`)

#### Option B: Settings UI

1. `Cmd + ,` → search **"chat.tools.global.autoApprove"** → **check** it
2. Search **"chat.agent.autoApprove"** → check all three checkboxes
3. Search **"chat.commandApproval.enabled"** → **uncheck** it

#### Option C: Workspace-Level Only

```bash
mkdir -p .vscode
cat > .vscode/settings.json << 'EOF'
{
  "chat.tools.global.autoApprove": true,
  "chat.agent.autoApprove": true,
  "chat.agent.autoApprove.terminalCommands": true,
  "chat.agent.autoApprove.outsideWorkspace": true,
  "chat.commandApproval.enabled": false
}
EOF
```

### Verify

1. Open Copilot Chat (`Cmd + Shift + I`)
2. Switch to **Agent** mode
3. Test: *"List all files in my home directory"*
4. Confirm it runs **without** showing an approval dialog

### Granular Control (Optional)

```json
{
  "chat.agent.autoApprove": false,
  "chat.agent.autoApprove.terminalCommands": true,
  "chat.agent.autoApprove.outsideWorkspace": true
}
```

Auto-approves terminal + outside-workspace but prompts for other tools.

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Still getting prompts | Set `chat.tools.global.autoApprove` to `true` — this is the most common cause. Then reload window: `Cmd + Shift + P` → "Developer: Reload Window" |
| Setting not recognized | Update VS Code + Copilot extension to latest |
| Agent won't run commands | Ensure `terminalCommands` is `true`, not just master switch |
| Can't access external files | Set `outsideWorkspace` to `true` |
| Some commands still prompt | Remove `chat.tools.terminal.autoApprove` entirely — per-command `false` entries override the master switch |
| Auto-approve set but still shows dialog | `chat.tools.global.autoApprove` must be `true` in addition to the `chat.agent.autoApprove` settings |

---

## 2. Claude Code (Anthropic CLI)

### Overview

Claude Code is a terminal-based AI agent from Anthropic. By default it asks permission before running commands, editing files, and using tools like web search.

### Setup — Full Auto-Approve

#### Option A: Dangerously Skip Permissions (All Actions)

```bash
claude --dangerously-skip-permissions
```

This bypasses **all** permission checks for the entire session. Claude Code will execute terminal commands, edit files, and use web tools without asking.

#### Option B: Allowed Tools (Granular)

Create or edit `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Computer(*)",
      "Edit(*)",
      "MultiEdit(*)",
      "Write(*)",
      "Read(*)",
      "WebSearch(*)",
      "WebFetch(*)",
      "TodoRead(*)",
      "TodoWrite(*)",
      "Glob(*)",
      "Grep(*)",
      "LS(*)"
    ],
    "deny": []
  }
}
```

This specifically allows each tool category with wildcard patterns.

#### Option C: Project-Level Settings

Create `.claude/settings.json` in the project root:

```json
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Edit(*)",
      "MultiEdit(*)",
      "Write(*)",
      "Read(*)"
    ],
    "deny": []
  }
}
```

### Key Flags

| Flag/Setting | Purpose |
|-------------|---------|
| `--dangerously-skip-permissions` | Skip ALL permission prompts |
| `--allowedTools` | Specify allowed tools via CLI |
| `~/.claude/settings.json` | Global default permissions |
| `.claude/settings.json` | Project-level permissions |

### Verify

```bash
claude --dangerously-skip-permissions -p "list files in home directory"
```

Confirm it runs `ls ~` without asking for approval.

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Still prompting | Ensure `--dangerously-skip-permissions` flag is used or settings file is valid JSON |
| Settings not applied | Check file path: `~/.claude/settings.json` for global, `.claude/settings.json` for project |
| Tool not recognized | Update Claude Code: `claude update` or reinstall with `npm install -g @anthropic-ai/claude-code` |
| Permission denied on file | This is an OS permission issue, not Claude Code — check file ownership |

---

## 3. OpenAI Codex (CLI)

### Overview

Codex is OpenAI's CLI coding agent. It has three operating modes with increasing autonomy.

### Setup — Full Auto-Approve

#### Option A: Full-Auto Mode (CLI Flag)

```bash
codex --full-auto "your task here"
```

In `full-auto` mode, Codex reads, writes, and executes commands without any approval prompts.

#### Option B: Set Default Mode in Config

Create or edit `~/.codex/config.yaml`:

```yaml
model: o4-mini
approval_mode: full-auto
```

Now every `codex` invocation defaults to full-auto mode.

#### Option C: Auto-Edit Mode (Partial Auto)

```bash
codex --auto-edit "your task here"
```

This auto-approves file edits but still asks before running terminal commands.

### Mode Reference

| Mode | File Read | File Write | Terminal Commands |
|------|-----------|------------|-------------------|
| `suggest` | Auto | Prompt | Prompt |
| `auto-edit` | Auto | Auto | Prompt |
| `full-auto` | Auto | Auto | Auto |

### Sandbox & Safety

Codex runs commands in a sandboxed environment by default:
- **macOS**: Uses Apple Seatbelt sandbox
- **Linux**: Uses Docker containers

To disable sandbox (not recommended):
```bash
codex --full-auto --disable-sandbox "your task here"
```

### Verify

```bash
codex --full-auto "list all files in the current directory"
```

Confirm it runs without prompting.

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Still prompting in full-auto | Check config: `cat ~/.codex/config.yaml` — ensure `approval_mode: full-auto` |
| Command not found | Install: `npm install -g @openai/codex` |
| Sandbox errors | Try `--disable-sandbox` or ensure Docker is running (Linux) |
| API key issues | Set `OPENAI_API_KEY` environment variable |

---

## 4. Cursor

### Overview

Cursor is a VS Code fork with built-in AI. Its agent mode (Composer Agent) has its own auto-approve settings.

### Setup

#### Option A: Settings UI

1. Open Settings: `Cmd + ,` (macOS) or `Ctrl + ,`
2. Search for **"auto-run"** or navigate to **Cursor Settings > Features > Chat**
3. Enable **"Auto-run mode"** — this allows the agent to execute commands without approval
4. Or go to: **Cursor > Settings > Cursor Settings > Features** and toggle the auto-run option

#### Option B: Yolo Mode

1. Open **Cursor Settings** (not VS Code settings): `Cmd + Shift + J` or via the gear icon
2. Navigate to **Features > Chat**
3. Enable **"Auto-Run Mode"** (also nicknamed "YOLO mode")
4. Optionally add a blocklist of commands that should still require approval

#### Option C: Rules-Based

Create `.cursor/rules` or `.cursorrules` in the project root to define agent behavior:

```
When running terminal commands, proceed without asking for confirmation.
Auto-approve all file edits.
```

### Settings Reference

| Setting | Location | Purpose |
|---------|----------|---------|
| Auto-Run Mode | Cursor Settings > Features > Chat | Auto-approve terminal commands |
| Command Blocklist | Cursor Settings > Features > Chat | Block specific commands from auto-running |
| `.cursorrules` | Project root | Project-level agent behavior rules |
| `.cursor/rules` | Project folder | Alternative rules location |

### Verify

1. Open Composer: `Cmd + I`
2. Switch to **Agent** mode
3. Test: *"List all files in the current directory"*
4. Confirm it runs the command without prompting

### Troubleshooting

| Issue | Solution |
|-------|----------|
| No auto-run option | Update Cursor to the latest version |
| Agent still prompts | Ensure you're in **Agent** mode in Composer, not Edit or Chat mode |
| Commands blocked | Check the blocklist in Cursor Settings > Features > Chat |
| Rules file not working | Ensure the file is in the project root and Cursor is restarted |

---

## 5. Aider (CLI)

### Overview

Aider is a terminal-based AI pair programming tool. By default it prompts for confirmation before applying changes. The `--yes-always` flag enables full autonomy.

### Setup — Full Auto-Approve

#### Option A: CLI Flag

```bash
aider --yes-always
```

Always says "yes" to every confirmation prompt.

#### Option B: Environment Variable

```bash
export AIDER_YES_ALWAYS=true
aider
```

#### Option C: Config File

Create `.aider.conf.yml` in the project root (or git root, or `~`):

```yaml
yes-always: true
auto-commits: true
auto-lint: true
auto-test: false
```

### Related Auto Settings

| Flag | Default | Purpose |
|------|---------|---------|
| `--yes-always` | `false` | Always say yes to every confirmation |
| `--auto-commits` | `true` | Auto-commit LLM changes to git |
| `--auto-lint` | `true` | Auto-lint after changes |
| `--auto-test` | `false` | Auto-run tests after changes |
| `--auto-accept-architect` | `true` | Auto-accept architect mode changes |

### Verify

```bash
aider --yes-always --message "list files in the current directory"
```

Confirm it runs without prompting.

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Still prompting | Ensure `--yes-always` flag is used or config file has `yes-always: true` |
| Config not loaded | Check `.aider.conf.yml` is in git root, cwd, or `~` |
| Command not found | Install: `pip install aider-chat` |
| Unwanted auto-commits | Add `--no-auto-commits` or set `auto-commits: false` in config |

---

## 6. Cline (VS Code Extension)

### Overview

Cline is a VS Code extension that provides per-category auto-approve toggles and a "YOLO Mode" for full autonomy.

### Setup — Full Auto-Approve (YOLO Mode)

1. Open Cline extension settings in VS Code
2. Navigate to **Features**
3. Check **"YOLO Mode"**

YOLO Mode auto-approves everything: file operations, terminal commands, browser actions, MCP tools, and mode transitions.

### Setup — Granular Auto-Approve

Configure individual categories in Cline Settings:

| Permission | Description | Risk |
|------------|-------------|------|
| Read project files | Read files, list files, search in workspace | Medium |
| Read all files | Read files outside workspace (requires base toggle) | Medium-High |
| Edit project files | Create and edit files in workspace | High |
| Edit all files | Edit files outside workspace (requires base toggle) | High |
| Execute safe commands | Run commands the model marks as safe | High |
| Execute all commands | Run all commands including destructive ones | Critical |
| Use the browser | Browser tool for web fetching/searching | Medium |
| Use MCP servers | MCP tools and resources | Medium-High |

### Verify

1. Open Cline panel in VS Code
2. Test: *"List all files in the current directory"*
3. Confirm it runs without showing an approval dialog

### Troubleshooting

| Issue | Solution |
|-------|----------|
| YOLO mode not available | Update Cline extension to latest version |
| Still prompting with categories enabled | "Read/Edit all files" only extends the base toggle — enable the base first |
| Commands still requiring approval | The model decides `requires_approval` per command — enable "Execute all commands" for full auto |
| Want to roll back changes | Use Cline's Checkpoints feature |

---

## 7. Roo Code (VS Code Extension)

### Overview

Roo Code (fork of Cline) provides detailed auto-approve with allowlist/denylist for commands, a global enable switch, and per-category permissions.

### Setup — Full Auto-Approve

1. Open the **Auto-Approve dropdown** next to the chat input
2. Click **"All"** to select all permission tiles
3. Toggle **"Enabled"** at the bottom-right

**Keyboard shortcut:** `Cmd+Alt+A` (macOS) / `Ctrl+Alt+A` (Windows/Linux)

### Permissions

| Permission | Description | Risk |
|------------|-------------|------|
| Read files and directories | Access files without asking | Medium |
| Edit files | Modify files without asking | High |
| Execute approved commands | Run whitelisted terminal commands | High |
| Use the browser | Headless browser interaction | Medium |
| Use MCP servers | Use configured MCP services | Medium-High |
| Switch modes | Change between Code/Architect/etc. | Low |
| Create & complete subtasks | Manage subtasks without confirmation | Low |
| Answer follow-up questions | Auto-select default answer after timeout | Low |

### Command Allowlist/Denylist

```json
{
  "roo-cline.allowedCommands": ["git", "npm run", "python -m pytest", "cargo test"],
  "roo-cline.deniedCommands": ["git push", "npm publish", "rm", "sudo"]
}
```

Deny rules take precedence when their matching prefix is equally or more specific (longest-prefix wins).

### Verify

1. Open Roo Code panel, ensure auto-approve is enabled
2. Test: *"List all files in the current directory"*
3. Confirm it runs without prompting

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Auto-approve not working | Check both "Enabled" toggle AND at least one permission is selected |
| Commands still prompting | Add command prefix to `roo-cline.allowedCommands` or use `*` to allow all |
| MCP tools not auto-approving | Need both global "Always approve MCP tools" AND individual tool's "Always allow" |
| Want write delay | Configure under Settings → Context Management → Diagnostics |

---

## 8. Windsurf (Cascade)

### Overview

Windsurf is a standalone IDE by Codeium. Its AI agent "Cascade" operates in Code and Chat modes with auto-accept for actions.

### Setup

1. Open **Windsurf Settings**
2. Navigate to **Cascade** settings
3. Configure auto-accept preferences for terminal commands and file edits
4. Enable **Auto-Continue** to let Cascade automatically continue when hitting the 20-tool-call limit

### Key Features

| Feature | Purpose |
|---------|---------|
| Auto-Continue | Automatically continue response after hitting tool call limit |
| Auto-fix lint | Automatically fix linting errors on generated code (default: on) |
| Checkpoints | Named snapshots for easy revert |
| `.codeiumignore` | Prevent Cascade from accessing specified files |

### Verify

1. Open Cascade: `Cmd+L`
2. Test: *"List all files in the current directory"*
3. Confirm it accepts and runs without manual approval

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Cascade still prompting | Check Windsurf settings for auto-accept configuration |
| Tool call limit reached | Enable Auto-Continue in settings |
| File access blocked | Check `.codeiumignore` for unintended exclusions |
| Credit consumption high | Each tool call and continue counts as a prompt credit |

---

## Quick Reference — All Agents

| Agent | Full Auto Command / Setting |
|-------|----------------------------|
| **GitHub Copilot** | `"chat.tools.global.autoApprove": true` + `"chat.agent.autoApprove": true` in VS Code settings |
| **Claude Code** | `claude --dangerously-skip-permissions` or `~/.claude/settings.json` |
| **OpenAI Codex** | `codex --full-auto` or `approval_mode: full-auto` in `~/.codex/config.yaml` |
| **Cursor** | Enable "Auto-Run Mode" in Cursor Settings > Features > Chat |
| **Aider** | `aider --yes-always` or `yes-always: true` in `.aider.conf.yml` |
| **Cline** | Enable "YOLO Mode" in Cline Settings > Features |
| **Roo Code** | Auto-Approve dropdown → "All" + "Enabled" (shortcut: `Cmd+Alt+A`) |
| **Windsurf** | Configure auto-accept in Windsurf Settings > Cascade |

## Decision Guide

```
Want full autonomy?
├── Using VS Code + Copilot?    →  Set chat.tools.global.autoApprove = true + chat.agent.autoApprove = true
├── Using VS Code + Cline?     →  Enable YOLO Mode in Cline Settings > Features
├── Using VS Code + Roo Code?  →  Auto-Approve dropdown → All + Enabled
├── Using Claude Code CLI?     →  Run with --dangerously-skip-permissions
├── Using OpenAI Codex CLI?    →  Run with --full-auto
├── Using Aider CLI?           →  Run with --yes-always
├── Using Cursor?              →  Enable Auto-Run Mode in Cursor Settings
└── Using Windsurf?            →  Configure auto-accept in Cascade settings
```
