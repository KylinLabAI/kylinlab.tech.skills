# Skill Manual: ai-token-usage

## What Problem It Solves

AI usage data is scattered across many local tools (Copilot, Codex, Claude Code, plus other AI coding IDEs). Users need one place to understand total usage, model usage, trends, and current-session context consumption.

## Objective

This skill produces token usage reports by reading local AI session logs and aggregating usage by agent, model, date, and session.

## Supported Tools

| Agent | Local logs | Notes |
| --- | --- | --- |
| `copilot` | Yes (JSONL) | GitHub Copilot session logs. |
| `codex` | Yes (JSONL) | OpenAI Codex session logs. |
| `claude` | Yes (JSONL) | Claude Code session logs. |
| `opencode` | Yes (SQLite) | Reads `~/.local/share/opencode/opencode.db`. |
| `qoder` | Server-side | No local token logs; usage is tracked on the provider dashboard. |
| `codebuddy` | Server-side | No local token logs; usage is tracked on the provider dashboard. |
| `trae` | Server-side | No local token logs; usage is tracked on the provider dashboard. |
| `cloudecode` | Server-side | No local token logs; usage is tracked on the provider dashboard. |

Tools without local logs (qoder, codebuddy, trae, cloudecode) report an
availability note instead of fabricated numbers; check their provider dashboard
for authoritative usage.

## Workflow / Design

1. Locate local session logs/DBs for each supported tool.
2. Normalize usage fields from different tools.
3. Aggregate totals by date, agent, model, and session.
4. Produce tables, top-session summaries, trends, or charts.
5. Optionally export CSV or JSON.

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

The user asks for the last 7 days. The agent reads local logs, groups usage by day and model, prints the summary table, and saves a chart when requested.

## Related Skill File

See [SKILL.md](./SKILL.md) for the agent-facing execution rules.
