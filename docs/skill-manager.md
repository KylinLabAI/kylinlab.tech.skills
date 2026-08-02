# Skill Manual: skill-manager

## What Problem It Solves

Skills live in many places — project folders, repo checkouts — and there are
multiple agent runtimes (Claude Code, CodeBuddy, Trae, etc.) that each need to
see them. Keeping a skill linked and up to date in every one of those locations
by hand is repetitive and error-prone.

## Objective

This skill links **local skill directories** into every agent runtime using
symlinks, so a single source of truth is reflected everywhere at once. Edits to
the source are visible in all agents immediately — no reinstall step.

**Scope:** skill-manager handles local skills only (symlink management).
External skills from other repositories are installed separately with
`npx skills add`; see this repo's `external-skills/README.md`.

## Core Concepts

- **Local Skills**: Skill directories that exist on disk (for example
  `kylinlab.tech.skills/skills/`).
- **Symlinks**: Symbolic links created from each agent skill directory to the
  actual skill source. Updates to the source are reflected automatically.
- **External Skills**: Not handled here — installed via `npx skills add`.

## When To Use It

- The user wants to link a local skill directory into their agents.
- The user wants to remove (unlink) a skill from their agents.
- The user wants to re-link a skill whose source path changed.

## How To Use This Skill

All operations go through the bundled `scripts/manage.py` script.

### Link a local skill

```bash
python <skill-path>/scripts/manage.py add /path/to/local/skill
```

This creates a symlink named after the skill folder in every agent skill
directory. It never deletes user data — if a target path already exists as a
real file or directory, that link is skipped and an error is reported.

### Remove a skill

```bash
python <skill-path>/scripts/manage.py remove <skill-name>
```

Removes the symlink for `<skill-name>` from every agent skill directory. Only
symlinks are removed; the skill source is never touched.

## Agent Skill Directories

The skill manager creates symlinks in these agent directories:

- `~/.trae-cn/skills/`
- `~/.claude/skills/`
- `~/.codebuddy/skills/`
- `~/.qoder/skills/`
- `~/.qoder-cn/skills/`
- `~/.lingma/skills/`
- `~/.zcode/skills/`
- `~/.agents/skills/`

## Notes

- Always use symlinks, never copy files.
- Local skills remain in their original locations; only symlinks are created.
- `create_symlink` only ever removes an existing symlink — it refuses to
  replace a real file or directory.
- Skill names are validated (letters, digits, `-`, `_`, `.`) to prevent path
  traversal.
- External skills are managed with `npx skills`, not this skill.

## Related Skill File

See [SKILL.md](../skills/skill-manager/SKILL.md) for the agent-facing execution rules.
