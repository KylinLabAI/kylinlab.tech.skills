---
name: skill-manager
description: Link local skill directories into agent runtimes using symlinks, and remove or update those links. Use this skill when users want to link a local skill directory, unlink an installed skill, or refresh which skills are visible to their agents. External skills from other repos are NOT handled here — they are installed separately with `npx skills`.
---

# Skill Manager

A skill for linking local skill directories into agent runtimes using symlinks.
A single source of truth (the skill's real location) is reflected in every
agent directory that uses it; edits to the source are reflected immediately.

**Scope:** skill-manager handles **local skills only** (symlink management).
External skills from other repositories are installed separately with
`npx skills add` — see this repo's `external-skills/README.md`.

## When to Use This Skill

- Link a local skill directory into your agent runtimes.
- Remove (unlink) a skill from your agent runtimes.
- Re-link a skill whose source path changed.

## Core Concepts

- **Local Skills**: Skill directories that exist on disk (for example
  `kylinlab.tech.skills/skills/`).
- **Symlinks**: Symbolic links created from each agent skill directory to the
  actual skill source. Updates to the source are reflected automatically.
- **External Skills**: Not handled here — installed via `npx skills add`.

## Usage

Use the bundled `scripts/manage.py` (argparse CLI).

### Add — link a local skill

```bash
python <skill-path>/scripts/manage.py add /path/to/local/skill
```

Creates a symlink named after the skill folder in every agent skill directory.
Never deletes user data: if a target path already exists as a real file or
directory, the link is skipped and an error is reported.

### Remove — unlink a skill

```bash
python <skill-path>/scripts/manage.py remove <skill-name>
```

Removes the symlink for `<skill-name>` from every agent skill directory. Only
symlinks are removed; the skill source is never touched.

## Agent Skill Directories

The skill manager creates symlinks in the following agent directories:

- `~/.trae-cn/skills/`
- `~/.claude/skills/`
- `~/.codebuddy/skills/`
- `~/.qoder/skills/`
- `~/.qoder-cn/skills/`
- `~/.lingma/skills/`
- `~/.zcode/skills/`
- `~/.agents/skills/`

## Workflow

### Linking a Local Skill

1. Verify the source directory contains a `SKILL.md` with valid frontmatter.
2. Run `python <skill-path>/scripts/manage.py add <source>`.
3. Confirm a symlink appears in each agent skill directory.

### Removing a Skill

1. Run `python <skill-path>/scripts/manage.py remove <skill-name>`.
2. Symlinks are removed from all agent directories; the source stays intact.

### Updating a Skill

- **Local skills**: nothing to do — changes are reflected via symlinks.
- **External skills**: managed with `npx skills`, not this skill.

## Notes

- Always use symlinks, never copy files.
- `create_symlink` refuses to replace a real file/directory at the target — it
  only ever removes an existing symlink.
- Skill names are validated to contain only letters, digits, `-`, `_`, and `.`
  (no path separators), preventing path traversal.
