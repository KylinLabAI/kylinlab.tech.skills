# Skill Manual: disk-cleanup

## What Problem It Solves

Local disks fill with temporary files, caches, logs, trash, and build artifacts. Users need a safe way to understand what can be deleted before anything is removed.

## Objective

This skill finds reclaimable disk space on macOS, Windows, or Linux and uses dry-run reporting plus explicit approval before cleanup.

## Workflow / Design

1. Detect the operating system and common cleanup targets.
2. Run a dry-run scan and estimate reclaimable space.
3. Present cleanup levels and risks clearly.
4. Delete only approved targets.
5. Report reclaimed space and remaining large areas to review.

## When To Use It

Use this skill when the user says disk is full, storage is low, the C drive is filling up, or they want to clean temporary files and developer caches.

Do not use it to delete personal files without explicit user direction.

## How To Use This Skill

Ask for a scan first, then approve a cleanup level after reviewing the report.

Example requests:

```text
Dry-run cleanup and show what can be safely deleted on Windows.
```

```text
Apply safe cleanup for developer caches older than 30 days.
```

## Example Usage

The user asks to free space. The agent runs a dry-run, shows cache/log categories and estimated sizes, asks for approval, then cleans only the selected targets.

## Related Skill File

See [SKILL.md](../skills/disk-cleanup/SKILL.md) for the agent-facing execution rules.
