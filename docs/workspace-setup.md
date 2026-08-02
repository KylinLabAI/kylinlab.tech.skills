# Skill Manual: workspace-setup

## What Problem It Solves

Developers keep many git repositories spread across nested folders — for
example a `~/dev` tree containing personal projects, work repos, and tools,
each in its own subfolder. When you move to a new machine, reinstall, or just
want a backup of *how your folders are laid out* (not the code itself), it's
tedious to recreate that exact hierarchy by hand.

## Objective

This skill saves the **structure** of a workspace — which folders hold git
repos, how those folders are nested, and the repos' remotes — into a small
config file. Later, it can recreate that same folder tree on another machine by
cloning the repos, keeping the original layout:

```text
repo-1
app/repo-2
app/repo-3
app/tool/repo-4
```

It does **not** copy repo contents — only the structure and where to clone from.

## When To Use It

Use this skill when the user says things like:

- "Scan my workspace folders"
- "Save my folder structure" / "back up my repo layout"
- "Rebuild my folder tree from a config"
- "Restore my workspace structure on the new machine"

Do not use it to back up file *contents* or to manage a single repository.

## How To Use This Skill

All operations go through one helper. You give it a folder to scan, or a config
to rebuild from.

### Capture a workspace

```text
Scan my ~/dev folder and save its structure.
```

The agent runs the scan and produces a config file (by default under the
skill's `configs/` folder). Folders without any git repo inside are skipped
automatically.

Preview first if you like:

```text
Dry-run a scan of ~/dev so I can see what it would capture.
```

### Rebuild a workspace elsewhere

```text
Rebuild my workspace from the saved config into ~/dev-new.
```

The agent recreates the folders and clones each repo into its original
relative location. Existing repos are left alone unless you ask to update them.

## Example Usage

The user asks to migrate to a new laptop. The agent scans `~/dev`, produces a
config capturing `repo-1`, `app/repo-2`, `app/repo-3`, and `app/tool/repo-4`
with their remotes, then rebuilds the same tree on the new machine by cloning.
The nested `app/tool/` folders are recreated exactly.

## Notes

- The saved config records repo remotes, so keep it private like any file that
  points at your repositories. In this repo the skill's `configs/` folder
  (generated per-workspace JSON) is gitignored and not committed.
- Scanning is read-only. Rebuilding only clones into empty paths — it never
  deletes or overwrites your existing repositories.
- You don't need to understand the config format; the agent handles it.

## Related Skill File

See [SKILL.md](../skills/workspace-setup/SKILL.md) for the agent-facing
execution rules.
