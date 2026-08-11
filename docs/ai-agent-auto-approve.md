# Skill Manual: ai-agent-auto-approve

## What Problem It Solves

When you want an AI coding agent to run fully autonomously — no per-command or
per-edit approval prompts — you need the exact settings/flags for each agent.
These differ wildly between VS Code extensions, CLIs, and standalone IDEs, and
it's easy to miss the one master switch that actually suppresses prompts.

## Objective

Configure supported AI coding agents for fully autonomous ("auto-approve")
operation. The skill auto-detects the active agent or lets the user specify one,
then applies the correct configuration.

## Supported Agents

| Agent | Type |
|-------|------|
| GitHub Copilot | VS Code |
| Claude Code | Anthropic CLI |
| OpenAI Codex | CLI |
| Cursor | Standalone IDE (VS Code fork) |
| Aider | CLI |
| Cline | VS Code extension |
| Roo Code | VS Code extension |
| Windsurf (Cascade) | Standalone IDE |

## Workflow / Design

1. Detect the environment (editor, parent process, session env vars).
2. If ambiguous, ask the user which agent to configure.
3. Apply the appropriate auto-approve config — either a settings JSON edit, a
   CLI flag, or a project-level config file.
4. Provide a verify step and a troubleshooting table per agent.

## Quick Reference

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

## Safety

Auto-approve gives the agent full autonomy to run any terminal command and
modify any file. Only enable it in trusted environments. For most agents the
skill documents a **granular** alternative (per-command allow/deny lists) so you
can keep destructive commands behind a prompt. See
[`SKILL.md`](../skills/ai-agent-auto-approve/SKILL.md) and
[`references/ai-agent-auto-approve-guide.md`](../skills/ai-agent-auto-approve/references/ai-agent-auto-approve-guide.md)
for the full comparison matrix and security considerations.

## Notes

- No scripts or configs are shipped; this skill is pure instructions + a
  reference guide.
- The settings shown are examples — verify against your agent's current version,
  since setting names change between releases.
