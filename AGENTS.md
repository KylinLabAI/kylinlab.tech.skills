# AGENTS.md

Repository guidance for agents working in `kylinlab.tech.skills`.

## Purpose

This repo stores reusable personal skills. Each skill lives under
`skills/<skill-name>/` and is centered on a `SKILL.md` entry point, with
optional helper assets (scripts, references, configs).

## Repository Layout

- `README.md`: repo overview, current skill inventory, and common usage flows
- `docs/<skill-name>.md`: human-facing manual for each skill
- `skills/<skill-name>/SKILL.md`: required entry point for a skill
- `skills/<skill-name>/scripts/`: automation helpers used by the skill
- `skills/<skill-name>/references/`: supporting docs, templates, schemas, prompts
- `skills/<skill-name>/configs/`: committed config templates (e.g. `apps.yaml`)
- `external-skills/README.md`: catalog of external skills installed via `npx skills` (the folder itself is gitignored except this file)

## Behavioral Notes

- Make the minimum change that solves the request; prefer additive edits over
  large rewrites.
- Match the existing style and don't "improve" unrelated code.
- Keep helper scripts small, deterministic, and referenced from `SKILL.md`.
- Document prerequisites and first-use setup inside the skill itself.

## Common Commands

```bash
# Link a local skill into your agent runtimes (symlink, always up to date)
python skills/skill-manager/scripts/manage.py add skills/<skill-name>

# Remove a linked skill
python skills/skill-manager/scripts/manage.py remove <skill-name>

# One-time init for skills that ship one (e.g. disk-cleanup)
python skills/<skill-name>/scripts/init.py
```

## Skill Authoring Rules

When creating or revising a skill:

- Keep the folder name, frontmatter `name`, and install path aligned.
- Put the user-facing workflow in `SKILL.md`; don't hide core instructions only in scripts.
- Commit config **templates** only — never live user config or secrets.
- If a skill needs local runtime files, make sure the live config path is gitignored.

### Initialization Contract (only for skills with extra tool dependencies)

Most skills here need only Python 3 (and Git), so they ship no init step. The
contract applies **only** to a skill that depends on extra CLI tools it cannot
assume are present. Today only `disk-cleanup` ships an `init.py` (it installs
Python via `laptop-setup`).

A skill with extra tool dependencies follows this pattern:

1. Ship `configs/apps.yaml` (laptop-setup schema) and `scripts/init.py` to install them.
2. Optionally ship `scripts/require_tools.py` — a fast pre-flight check that fails immediately if a tool is missing.
3. Include an **Initialization Contract** section in `SKILL.md` telling the agent:
   - **Initialize**: `python <skill>/scripts/init.py` (one-time setup).
   - **Normal runs**: execute task scripts directly, never re-check every tool.
   - **Missing tool at runtime**: stop immediately, tell user to run `init.py`, do NOT install ad hoc.

## New Skill Checklist

1. Create `skills/<skill-name>/SKILL.md`.
2. Add required `scripts/`, `references/`, and `configs/` template files.
3. Add a human manual at `docs/<skill-name>.md`.
4. Update `README.md` so the skill inventory stays accurate.
5. If the new skill introduces live local config files, confirm they are gitignored.

## Editing Existing Skills

- Preserve the existing trigger intent unless the change is deliberate.
- Keep relative links working from the skill directory.
- Prefer additive updates over large rewrites when only one workflow step changes.
- If a skill's capabilities materially change, update both its `SKILL.md` description and the `README.md` summary.

## Local Skill Install — Symlink, Not Copy

Local skills in this repo are installed via `skills/skill-manager` using
**symlinks**, not copies. Once a skill is linked, any change made under
`skills/<skill-name>/` is immediately reflected in the agent runtime — there is
no separate install/sync step for local skills.

- Use `python skills/skill-manager/scripts/manage.py add <path>` to link a local
  skill from this repo.
- Do **not** copy skill files into agent runtimes — always link via
  `skill-manager` so the runtime reflects repo edits immediately.

Because the link points at the repo source, the runtime is always up to date;
just commit the change.

## External Skills — Use `npx skills`

External skills (from other repos, e.g. `anthropics/skills`, `vercel-labs/skills`)
are **not** part of this repo and are installed with `npx skills add`, not
`skill-manager`. The `external-skills/README.md` catalogs them with canonical
install commands. Track additions there; the `external-skills/` folder is
gitignored except for that README.

## Validation

Before finishing a change:

- Every shipped skill directory still has a `SKILL.md`.
- `README.md` and `docs/` match the current `skills/*/` directories.
- `.gitignore` expectations are met when adding config or generated files.
