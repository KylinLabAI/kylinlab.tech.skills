# kylinlab.tech.skills

A personal collection of AI agent skills for everyday engineering workflows —
laptop provisioning, disk cleanup, skill management, and workspace migration.

Each skill is a self-contained folder with a `SKILL.md` entry point (agent
instructions) and a matching `docs/<skill>.md` manual (human-facing).

- **Local skills** (authored here, under `skills/`) are linked into agent
  runtimes via `skills/skill-manager` (symlinks), so they stay up to date with
  this repo automatically.
- **External skills** (from other repos) are installed separately via `npx skills`
  and cataloged in [`external-skills/README.md`](external-skills/README.md).

## Skills

| Skill | Manual | Purpose |
|---|---|---|
| [`disk-cleanup`](skills/disk-cleanup/SKILL.md) | [manual](docs/disk-cleanup.md) | Safely recover disk space by cleaning temp files, caches, logs, trash, and package-manager caches on macOS/Windows/Linux |
| [`laptop-setup`](skills/laptop-setup/SKILL.md) | [manual](docs/laptop-setup.md) | Provision, audit, or verify a developer laptop from a YAML app registry (brew/winget/apt/dnf), with profiles and dry-runs |
| [`skill-manager`](skills/skill-manager/SKILL.md) | [manual](docs/skill-manager.md) | Link and unlink local skill directories across agent runtimes using symlinks |
| [`workspace-setup`](skills/workspace-setup/SKILL.md) | [manual](docs/workspace-setup.md) | Capture a workspace folder tree (git repos + structure) to a portable config, then recreate it by cloning |

## Install

### Local skills (this repo)

`skills/skill-manager` creates symlinks from your agent skill directories
(Copilot, Claude Code, Cursor, Codex, etc.) to the skill source in this repo, so
edits here are reflected immediately.

```bash
# Link a local skill from this repo into your agents
python skills/skill-manager/scripts/manage.py add skills/<skill-name>

# Remove a linked skill
python skills/skill-manager/scripts/manage.py remove <skill-name>
```

Local skills update automatically (the link points at the source); external
skills are updated with `npx skills update`.

### External skills (other repos)

External skills are installed with `npx skills add` and tracked in
[`external-skills/README.md`](external-skills/README.md). Example:

```bash
npx skills add https://github.com/anthropics/skills --skill skill-creator -g -y
```

Prerequisites: **Python 3** and **Git** (for `skill-manager`); `npx` for
external skills.

## Project Structure

```text
kylinlab.tech.skills/
├── README.md          # This file
├── AGENTS.md          # Guidance for AI agents editing this repo
├── docs/              # Human-facing skill manuals (one per skill)
├── external-skills/   # Installed external skills (gitignored)
└── skills/            # Local skills authored in this repo
    └── <skill-name>/
        ├── SKILL.md   # Required: agent-facing instructions
        ├── scripts/   # Automation helpers
        ├── references/
        └── configs/   # Committed config templates
```

## Using a Skill

Open the skill's `docs/<skill>.md` for the human guide, or `SKILL.md` for the
agent workflow. Skills that need extra tool dependencies ship a one-time init:

```bash
python skills/<skill-name>/scripts/init.py  # one-time setup (if present)
```

## Development

- New skills: follow the [New Skill Checklist](AGENTS.md#new-skill-checklist).
- Local skills are symlinked, so just commit edits — no separate sync step.
- `npx skills` is for **external** skills only; local repo skills use
  `skill-manager`.

## License

No `LICENSE` file is committed. Unless stated otherwise in a skill's own files,
the contents are reserved and not licensed for reuse.
