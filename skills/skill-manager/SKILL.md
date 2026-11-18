---
name: skill-symlink-manager
version: 1.0.0
display_name: 技能符号链接管理器
display_name_en: Skill Symlink Manager
description: Link local skill directories into agent runtimes using symlinks, and remove or update those links. Use this skill when users want to link a local skill directory, unlink an installed skill, or refresh which skills are visible to their agents. External skills from other repos are NOT handled here — they are installed separately with `npx skills`.
description_zh: 使用符号链接将本地技能目录链接到各类智能体运行时，并可移除或更新这些链接。当用户想要将本地技能目录链接到其智能体、取消已安装技能的链接，或刷新其智能体可见的技能时，使用该技能。来自其他仓库的外部技能不在此处理 —— 它们通过 `npx skills` 单独安装。
description_en: Link local skill directories into agent runtimes using symlinks, and remove or update those links. Use this skill when users want to link a local skill directory, unlink an installed skill, or refresh which skills are visible to their agents. External skills from other repos are NOT handled here — they are installed separately with `npx skills`.
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
- `~/.workbuddy/skills/`
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
