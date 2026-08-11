# Skill Manual: ai-agent-auto-approve

## What Problem It Solves

AI coding agents often stop for repeated permission prompts. That is useful for safety, but it slows down workflows where the user intentionally wants the agent to run autonomously.

## Objective

This skill helps configure supported AI agents for full or granular auto-approve behavior. It keeps the setup explicit so the user understands which agent is being configured and what level of autonomy is enabled.

## Workflow / Design

1. Detect the active agent or ask the user which agent to configure.
2. Explain the safety impact of auto-approval.
3. Apply the agent-specific setting, command flag, or config file change.
4. Prefer granular allow/deny lists when the user does not need full auto-approval.
5. Verify the configuration and report how to use it.

## When To Use It

Use this skill when the user asks for auto approve, autonomous agent mode, fewer prompts, full-auto execution, or agent permission configuration.

Do not use it when the user only wants a normal one-time command or when the workspace contains sensitive operations that need manual approval.

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

The user asks to enable Copilot auto-approval. The agent checks the VS Code settings location, explains the implication, updates the relevant setting, and tells the user how to verify that future tool calls no longer prompt unnecessarily.

## Related Skill File

See [SKILL.md](../../skills/ai-agent-auto-approve/SKILL.md) for the agent-facing execution rules.
