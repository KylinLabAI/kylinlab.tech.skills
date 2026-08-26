# Skill Manual: ai-agent-auto-approve

## What Problem It Solves

AI coding agents often stop for repeated permission prompts. That is useful for
safety, but it slows down workflows where you intentionally want the agent to run
autonomously. To do that you need the exact per-agent settings/flags, which
differ wildly between VS Code extensions, CLIs, and standalone IDEs — and it's
easy to miss the one master switch that actually suppresses prompts.

## Objective

Configure supported AI coding agents for full or granular auto-approve. The
skill auto-detects the active agent (or lets you pick one) and applies the
correct config, keeping the choice explicit so you understand which agent is
being changed and what level of autonomy is enabled.

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
2. If ambiguous, ask you which agent to configure.
3. Apply the appropriate auto-approve config — a settings JSON edit, a CLI flag,
   or a project-level config file.
4. Provide a verify step and a troubleshooting table per agent.
5. Prefer granular allow/deny lists when you do not need full auto-approval.

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

## When To Use It

Use this skill when you ask for auto-approve, autonomous agent mode, fewer
prompts, full-auto execution, or agent permission configuration.

Do not use it for a normal one-time command, or when the workspace contains
sensitive operations that need manual approval.

## How To Use This Skill

Ask the agent to configure a specific tool, or let it detect the current agent.

Example requests:

```text
Enable full auto-approve for GitHub Copilot in this workspace.
```

```text
Configure Codex CLI to run in full-auto mode by default.
```

## Example Usage

You ask to enable Copilot auto-approval. The agent checks the VS Code settings
location, explains the implication, updates the relevant setting, and tells you
how to verify that future tool calls no longer prompt unnecessarily.

## Notes

- No scripts or configs are shipped; this skill is pure instructions + a
  reference guide.
- The settings shown are examples — verify against your agent's current version,
  since setting names change between releases.

## Related Skill File

See [`SKILL.md`](../skills/ai-agent-auto-approve/SKILL.md) for the agent-facing
execution rules.
