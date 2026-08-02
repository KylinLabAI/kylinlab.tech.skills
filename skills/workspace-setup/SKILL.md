---
name: workspace-setup
description: Capture a workspace folder tree (git repos + their folder structure + repo-targeting symlinks) into a portable JSON config, then recreate that exact tree elsewhere by cloning. Use when the user says "scan my workspace folders", "save folder structure", "rebuild folder tree from config", "capture repo layout", "restore workspace structure", or wants to mirror a multi-repo folder hierarchy without the actual repo contents. Also trigger for backing up or recreating a folder tree that contains git repositories.
---

# Workspace Setup

Capture a workspace folder structure (git repos, their ancestor folders, and
repo-targeting symlinks) into a JSON config, then rebuild that structure on
another machine or location. Pure folders that contain no repos are
automatically excluded — only repo-containing subtrees and the repos themselves
are saved. The folder hierarchy is preserved exactly, e.g.:

```text
repo-1
app/repo-2
app/repo-3
app/tool/repo-4
```

This skill is **generic and user-driven**: it never hardcodes repo names or
paths. You pass it a workspace root, and it records whatever git repos it finds
there, with their relative paths, remotes, and branches.

## Skill Layout

- [./scripts/manage_folders.py](./scripts/manage_folders.py) - scan / rebuild CLI
- [./configs/](./configs/) - generated per-workspace JSON configs (gitignored; not committed)

## Agent Workflow

### 1. Scan — capture folder tree to config

Walk a workspace root, discover all git repos, record their ancestor folders,
capture symlinks that point to repos, and write everything to a JSON config.
Folders with no repos (directly or indirectly) are silently dropped.

When a git repo is found, its immediate children are also checked for symlinks
that point to other repos (e.g. a config symlink at a repo root). This captures
repo-root symlinks that would otherwise be missed, since the scanner does not
recurse into repo contents.

```bash
# Default output: ./configs/<workspace-name>.json
python3 <skill>/scripts/manage_folders.py scan --workspace ~/dev

# Explicit output path
python3 <skill>/scripts/manage_folders.py scan \
  --workspace ~/dev \
  --output ./configs/dev.json

# Preview without writing
python3 <skill>/scripts/manage_folders.py scan \
  --workspace ~/dev \
  --dry-run
```

**What gets saved:**

| Entry type | Example | Notes |
|---|---|---|
| `folder` | `app/tool` | Ancestor of at least one repo |
| `repo` | `app/repo-2` | Git repo root with `remote` and `branch` |
| `symlink` | `link -> ../repo-3` | Symlink whose target is a git repo |

Symlink targets are stored **relative to the workspace root** so the config
stays portable across machines. On rebuild, the workspace-relative target is
resolved against the new target directory.

**What gets excluded:**

- Folders that contain no repos at any depth.
- Standard skip dirs (`.git`, `node_modules`, `.venv`, `build`, `dist`, etc.).

Repos with **no origin remote** are still recorded but flagged in a warning,
because they cannot be cloned during rebuild.

### 2. Rebuild — recreate folder tree from config

Read the config file, create the folder structure, clone repos (or pull
existing ones), and restore symlinks.

```bash
python3 <skill>/scripts/manage_folders.py rebuild \
  --config ./configs/dev.json \
  --target ~/dev-restored
```

By default, existing repos are left untouched. To update them:

```bash
python3 <skill>/scripts/manage_folders.py rebuild \
  --config ./configs/dev.json \
  --target ~/dev-restored \
  --update-existing
```

Preview without mutating:

```bash
python3 <skill>/scripts/manage_folders.py rebuild \
  --config ./configs/dev.json \
  --target ~/dev-restored \
  --dry-run
```

### 3. Config file format

```json
{
  "schema_version": 1,
  "workspace": "~/dev",
  "generated_at": "2026-06-16T10:30:00+08:00",
  "folders": 3,
  "repos": 4,
  "symlinks": 0,
  "entries": [
    {"path": "repo-1", "type": "repo", "remote": "git@github.com:u/repo-1.git", "branch": "main"},
    {"path": "app", "type": "folder"},
    {"path": "app/repo-2", "type": "repo", "remote": "git@github.com:u/repo-2.git", "branch": "main"},
    {"path": "app/repo-3", "type": "repo", "remote": "git@github.com:u/repo-3.git", "branch": "develop"},
    {"path": "app/tool", "type": "folder"},
    {"path": "app/tool/repo-4", "type": "repo", "remote": "git@github.com:u/repo-4.git", "branch": "main"}
  ]
}
```

## Handoff Format

After running an operation, summarize:

- Command run and whether it was a dry run.
- Path to the generated config file (for scan) or target directory (for rebuild).
- Count of folders, repos, and symlinks processed.
- Any warnings — repos missing origin remotes, blocked paths, failed clones.
- Follow-up needed, such as manual conflict resolution in blocked paths.

## Notes

- The generated config contains repo remotes — treat it like any file that
  references your repositories; it is gitignored by this repo and not committed.
- `scan` is read-only against your workspace. `rebuild` only clones into empty
  paths; it never deletes or overwrites existing repos.
- This skill has no external tool dependencies beyond `git` and Python 3.
