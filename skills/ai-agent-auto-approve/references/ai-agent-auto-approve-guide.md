# AI Agent Auto-Approve — Reference Guide

Comprehensive reference for configuring AI coding agents for fully autonomous operation (no permission prompts). Covers 8 agents across IDE extensions and CLI tools.

---

## Table of Contents

1. [Overview](#overview)
2. [GitHub Copilot (VS Code)](#1-github-copilot-vs-code)
3. [Claude Code (CLI)](#2-claude-code-cli)
4. [OpenAI Codex (CLI)](#3-openai-codex-cli)
5. [Cursor](#4-cursor)
6. [Aider (CLI)](#5-aider-cli)
7. [Cline (VS Code Extension)](#6-cline-vs-code-extension)
8. [Roo Code (VS Code Extension)](#7-roo-code-vs-code-extension)
9. [Windsurf (Cascade)](#8-windsurf-cascade)
10. [Security Considerations](#security-considerations)
11. [Quick Comparison Matrix](#quick-comparison-matrix)

---

## Overview

AI coding agents typically require user approval before performing actions like editing files, running terminal commands, or accessing external resources. "Auto-approve" eliminates these prompts, letting the agent operate autonomously.

**Risk levels:**
- **Low**: Reading files, listing directories
- **Medium**: Editing files within workspace, browser access
- **High**: Running terminal commands, editing files outside workspace
- **Critical**: Full system access, destructive commands (`rm -rf`, `sudo`, etc.)

---

## 1. GitHub Copilot (VS Code)

**Type:** IDE Extension (VS Code)
**Docs:** VS Code Settings → `chat.agent.autoApprove`

### Key Settings

| Setting | Type | Purpose |
|---------|------|---------|
| `chat.tools.global.autoApprove` | `boolean` | Master switch — auto-approve ALL tool invocations globally |
| `chat.agent.autoApprove` | `boolean` | Auto-approve all agent actions |
| `chat.agent.autoApprove.terminalCommands` | `boolean` | Auto-approve terminal command execution |
| `chat.agent.autoApprove.outsideWorkspace` | `boolean` | Allow file access outside workspace |
| `chat.commandApproval.enabled` | `boolean` | Set `false` to disable command approval dialog |
| `chat.tools.terminal.autoApprove` | `object` | Per-command granular overrides (regex supported) |

### Full Auto-Approve Config

```json
{
  "chat.tools.global.autoApprove": true,
  "chat.agent.autoApprove": true,
  "chat.agent.autoApprove.terminalCommands": true,
  "chat.agent.autoApprove.outsideWorkspace": true,
  "chat.commandApproval.enabled": false
}
```

### Per-Command Granular Control

```json
{
  "chat.tools.terminal.autoApprove": {
    "ls": true,
    "cat": true,
    "rm": false,
    "kill": false,
    "/^git\\s+push\\b/": false
  }
}
```

Keys support plain command names or `/regex/` patterns matched against the full command string.

### Setup Methods
- **Settings JSON**: `Cmd+Shift+P` → "Preferences: Open User Settings (JSON)"
- **Settings UI**: `Cmd+,` → search each setting name
- **Workspace-level**: Create `.vscode/settings.json` in project root

### Notes
- `chat.tools.global.autoApprove` is the critical setting — even with `chat.agent.autoApprove = true`, VS Code may still prompt without it.
- If `chat.tools.terminal.autoApprove` is absent, the master switches control everything. Adding it introduces per-command exceptions.

---

## 2. Claude Code (CLI)

**Type:** CLI Tool
**Docs:** https://docs.anthropic.com/en/docs/claude-code

### Full Auto-Approve

```bash
claude --dangerously-skip-permissions
```

Bypasses ALL permission checks for the session.

### Granular — Allowed Tools

Global config (`~/.claude/settings.json`):

```json
{
  "permissions": {
    "allow": [
      "Bash(*)", "Computer(*)", "Edit(*)", "MultiEdit(*)",
      "Write(*)", "Read(*)", "WebSearch(*)", "WebFetch(*)",
      "TodoRead(*)", "TodoWrite(*)", "Glob(*)", "Grep(*)", "LS(*)"
    ],
    "deny": []
  }
}
```

Project-level config (`.claude/settings.json` in project root):

```json
{
  "permissions": {
    "allow": ["Bash(*)", "Edit(*)", "MultiEdit(*)", "Write(*)", "Read(*)"],
    "deny": []
  }
}
```

### Key References

| Item | Purpose |
|------|---------|
| `--dangerously-skip-permissions` | Skip ALL permission prompts |
| `--allowedTools` | Specify allowed tools via CLI |
| `~/.claude/settings.json` | Global default permissions |
| `.claude/settings.json` | Project-level permissions |

---

## 3. OpenAI Codex (CLI)

**Type:** CLI Tool
**Docs:** https://github.com/openai/codex

### Operating Modes

| Mode | File Read | File Write | Terminal Commands |
|------|-----------|------------|-------------------|
| `suggest` | Auto | Prompt | Prompt |
| `auto-edit` | Auto | Auto | Prompt |
| `full-auto` | Auto | Auto | Auto |

### Full Auto-Approve

```bash
codex --full-auto "your task here"
```

Or set as default in `~/.codex/config.yaml`:

```yaml
model: o4-mini
approval_mode: full-auto
```

### Sandbox

Codex runs commands in a sandboxed environment by default:
- **macOS**: Apple Seatbelt sandbox
- **Linux**: Docker containers
- Disable with `--disable-sandbox` (not recommended)

---

## 4. Cursor

**Type:** IDE (VS Code fork)
**Docs:** Cursor Settings > Features > Chat

### Setup

1. **Cursor Settings** (`Cmd+Shift+J`) → Features → Chat → Enable **"Auto-Run Mode"**
2. Optionally add a **command blocklist** for commands that should still require approval
3. Alternatively, create `.cursorrules` or `.cursor/rules` in the project root for rules-based config

### Settings Reference

| Setting | Location | Purpose |
|---------|----------|---------|
| Auto-Run Mode | Cursor Settings > Features > Chat | Auto-approve terminal commands |
| Command Blocklist | Cursor Settings > Features > Chat | Block specific commands |
| `.cursorrules` | Project root | Project-level agent behavior rules |
| `.cursor/rules` | Project folder | Alternative rules location |

---

## 5. Aider (CLI)

**Type:** CLI Tool (terminal-based AI pair programming)
**Docs:** https://aider.chat/docs/config/options.html

### Full Auto-Approve

```bash
aider --yes-always
```

The `--yes-always` flag makes Aider automatically say "yes" to every confirmation prompt, including file edits and command execution.

### Configuration Methods

| Method | Syntax | Scope |
|--------|--------|-------|
| CLI flag | `aider --yes-always` | Session |
| Environment variable | `AIDER_YES_ALWAYS=true` | Session/Shell |
| Config file | `yes-always: true` in `.aider.conf.yml` | Project/Global |

### Config File Locations

Aider searches for `.aider.conf.yml` in this order:
1. Git root directory
2. Current working directory
3. Home directory (`~`)

### Example `.aider.conf.yml`

```yaml
yes-always: true
auto-commits: true
auto-lint: true
auto-test: false
suggest-shell-commands: true
```

### Related Auto Settings

| Flag | Default | Purpose |
|------|---------|---------|
| `--yes-always` | `false` | Always say yes to every confirmation |
| `--auto-commits` | `true` | Auto-commit LLM changes to git |
| `--auto-lint` | `true` | Auto-lint after changes |
| `--auto-test` | `false` | Auto-run tests after changes |
| `--auto-accept-architect` | `true` | Auto-accept architect mode changes |
| `--suggest-shell-commands` | `true` | Allow suggesting shell commands |

### Notes
- Aider doesn't have a sandbox — commands execute directly in your shell
- Use `--no-auto-commits` to prevent automatic git commits
- The `--dry-run` flag can be used for testing without modifying files

---

## 6. Cline (VS Code Extension)

**Type:** VS Code Extension
**Docs:** https://docs.cline.bot/features/auto-approve

### Per-Category Auto-Approve

Cline provides per-category toggles in the extension settings:

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
| Enable notifications | OS notifications for approvals and long-running commands | Low |

### YOLO Mode (Full Auto-Approve)

YOLO Mode enables ALL auto-approve categories at once:
- All file operations (anywhere on system)
- All terminal commands (including destructive)
- Browser actions
- MCP server tools
- Mode transitions (Plan to Act)

**To enable:**
1. Open Cline extension settings
2. Navigate to **Features**
3. Check **"YOLO Mode"**

### Safe vs Approval-Required Commands

Cline does NOT use a fixed allowlist. The model flags each command with `requires_approval` based on context.

**Commonly safe:** `npm run build`, `npm test`, `git status`, `ls -la`, `cat package.json`
**Commonly requires approval:** `npm install <pkg>`, `rm -rf <path>`, `mv <a> <b>`, `sed -i ...`

### Notes
- All configuration is via the VS Code extension UI — no config files
- "Read all files" and "Edit all files" only extend the base toggle; they do nothing if the base is off
- Use Checkpoints to roll back quickly if auto-approve edits go wrong

---

## 7. Roo Code (VS Code Extension)

**Type:** VS Code Extension (fork of Cline)
**Docs:** https://docs.roocode.com/features/auto-approving-actions

### Quick Start

1. Open the **Auto-Approve dropdown** next to the chat input
2. Toggle **"Enabled"** at the bottom-right to activate
3. Use **All/None** chips to bulk-select or clear permissions
4. Click the **gear icon** to open advanced settings

### Keyboard Shortcut

- **macOS**: `Cmd+Alt+A`
- **Windows/Linux**: `Ctrl+Alt+A`
- Command Palette: `roo-cline.toggleAutoApprove`

### Permissions

| Permission | Description | Risk |
|------------|-------------|------|
| Read files and directories | Access files without asking | Medium |
| Edit files | Modify files without asking | High |
| Execute approved commands | Run whitelisted terminal commands | High |
| Use the browser | Headless browser interaction | Medium |
| Use MCP servers | Use configured MCP services | Medium-High |
| Switch modes | Change between Code/Architect/etc. modes | Low |
| Create & complete subtasks | Manage subtasks without confirmation | Low |
| Answer follow-up questions | Auto-select default answer after timeout | Low |

### Command Execution — Allowlist/Denylist

Roo Code uses prefix-based allow/deny lists with longest-prefix-wins precedence.

**Settings JSON:**
```json
{
  "roo-cline.allowedCommands": ["git", "npm run", "echo"],
  "roo-cline.deniedCommands": ["git push", "npm publish", "rm", "sudo", "*"]
}
```

**Deny rules take precedence** when their matching prefix is equally or more specific.

### Advanced Features

- **Write delay**: Configurable delay (0-2000ms+) after writes for diagnostics integration
- **Workspace boundary protection**: Separate toggles for outside-workspace reads/writes
- **Protected files**: Blocks modification of `.roo/` directory and `.rooignore` by default
- **MCP dual permission**: Requires both global "Always approve MCP tools" AND each tool's individual "Always allow" checkbox
- **Follow-up auto-answer**: Configurable timeout (1-300s, default 60s) to auto-select first suggestion
- **Dangerous substitution guard**: Blocks auto-approve for commands with dangerous parameter/process substitutions

### Recommended Deny List

Unix/macOS: `rm`, `sudo`, `dd`, `mkfs`, `shutdown`, `reboot`, `chmod -R`, `chown -R`, `kill -9`, `curl | sh`, `wget | sh`
Git/Package: `git push`, `npm publish`, `yarn publish`, `pnpm publish`

---

## 8. Windsurf (Cascade)

**Type:** IDE (standalone, by Codeium)
**Docs:** https://docs.windsurf.com/windsurf/cascade

### Overview

Windsurf's AI agent "Cascade" operates in Code and Chat modes. Cascade's approval model is primarily accept/reject for individual actions rather than a single "full auto" toggle.

### Key Features

- **Auto-Continue**: Cascade can automatically continue its response if it hits the 20-tool-call limit per prompt
- **Auto-fix lint**: Automatically fixes linting errors on generated code (enabled by default)
- **Checkpoints**: Named snapshots for easy revert if changes go wrong
- **Real-time awareness**: Cascade is aware of your real-time actions

### Configuration

Windsurf's auto-approve is configured through the IDE settings:
1. Open Windsurf Settings
2. Navigate to Cascade settings
3. Configure auto-accept preferences for terminal commands and file edits

### Notes
- Windsurf uses a credit-based system — each prompt and tool call consumes credits
- Cascade can make up to 20 tool calls per prompt
- `.codeiumignore` at workspace root prevents Cascade from viewing/editing/creating specified files
- Multiple simultaneous Cascades are supported but may conflict on shared files

---

## Security Considerations

### Before Enabling Auto-Approve

1. **Use version control** — Always have `git init` and make commits before enabling auto-approve
2. **Sandbox when possible** — Codex (sandbox), Docker containers, VMs
3. **Start with read-only** — Enable read auto-approve first, then gradually add write/execute
4. **Use deny lists** — Block destructive commands: `rm -rf`, `sudo`, `git push --force`, etc.
5. **Workspace boundaries** — Keep auto-approve within workspace; avoid enabling outside-workspace access
6. **Review after sessions** — Always `git diff` to review changes made during auto-approve sessions

### Risk Matrix

| Action | Risk | Agents with Granular Control |
|--------|------|------------------------------|
| Read files (workspace) | Low | Copilot, Cline, Roo Code |
| Read files (system-wide) | Medium | Copilot, Cline, Roo Code |
| Edit files (workspace) | Medium-High | Copilot, Cline, Roo Code, Cursor |
| Edit files (system-wide) | High | Copilot, Cline, Roo Code |
| Run terminal commands | High | Copilot, Cline, Roo Code, Cursor |
| Full autonomy (everything) | Critical | All agents support this |

### Commands to Always Block

```
rm -rf, sudo, dd, mkfs, shutdown, reboot
git push --force, git reset --hard
npm publish, yarn publish
chmod -R 777, chown -R
curl | sh, wget | sh
kill -9, killall
```

---

## Quick Comparison Matrix

| Agent | Type | Full Auto Method | Granular Control | Sandbox | Config File |
|-------|------|-----------------|------------------|---------|-------------|
| **GitHub Copilot** | VS Code Extension | `chat.tools.global.autoApprove` + `chat.agent.autoApprove` | Per-command regex | No | `.vscode/settings.json` |
| **Claude Code** | CLI | `--dangerously-skip-permissions` | Per-tool allow/deny | No | `~/.claude/settings.json` |
| **OpenAI Codex** | CLI | `--full-auto` | 3 modes (suggest/auto-edit/full-auto) | Yes (Seatbelt/Docker) | `~/.codex/config.yaml` |
| **Cursor** | IDE | Auto-Run Mode | Command blocklist | No | `.cursorrules` |
| **Aider** | CLI | `--yes-always` | Per-feature flags | No | `.aider.conf.yml` |
| **Cline** | VS Code Extension | YOLO Mode | Per-category toggles | No | Extension UI only |
| **Roo Code** | VS Code Extension | All + Enabled toggle | Per-category + allowlist/denylist | No | Extension UI + `roo-cline.*` settings |
| **Windsurf** | IDE | Cascade settings | Auto-continue, auto-fix | No | IDE Settings |
