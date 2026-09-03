---
name: disk-cleanup
description: Recover local disk space by safely finding and cleaning temporary files, caches, logs, trash, developer build artifacts, and package-manager caches on macOS, Windows, or Linux. Use this skill whenever the user says disk, storage, startup disk, C drive, temp files, cache, logs, cleanup, clean useless files, system says storage is almost full, or asks what can be deleted safely to save local storage.
compatibility: Requires only shell access and Python 3 for the bundled helper. Supports macOS, Windows, and Linux workflows with dry-run first and explicit apply before deletion.
---

# Storage Cleanup

Recover local storage without silently deleting user data. Favor built-in OS cleanup tools and an allowlisted dry-run scan before removing anything.

## Initialization Contract

If the user asks to initialize, set up, or install tools for this skill, run
`python <skill>/scripts/init.py`.

For normal cleanup requests, do not preflight-check dependencies. Run the
bundled helper directly. If Python is missing at runtime, stop and ask the user
to initialize the skill first with `python <skill>/scripts/init.py`.

## Workflow

1. Identify the host platform and list the targets that will be scanned.

```bash
python3 ./scripts/storage_cleanup.py --list-targets
```

2. Check free space and large categories first using the built-in OS tools. See the per-platform reference doc for the exact tools and commands:
   - [macOS](./references/macos-cleanup.md)
   - [Windows](./references/windows-cleanup.md)
   - [Linux](./references/linux-cleanup.md)

3. Run the bundled helper in dry-run mode. It scans only known temporary/cache/log locations for files older than the age threshold.

```bash
python3 ./scripts/storage_cleanup.py --min-age-days 7
```

On Windows, use `py -3` or `python` instead of `python3` if that is how Python is installed.

4. Review the report with the user. Explain what will be removed, what will regenerate, and what will only be suggested.
5. Delete only after explicit user approval. Use the smallest set of options that matches the approved cleanup.

```bash
python3 ./scripts/storage_cleanup.py --min-age-days 7 --apply
```

6. Recheck free space and report:
   - space before and after;
   - targets cleaned;
   - skipped paths or permission errors;
   - follow-up manual actions if built-in OS cleanup can reclaim more.

## Cleanup Levels

Use conservative levels. Do not jump to broad deletion just because the disk is low.

### Safe Default

Run without extra include flags. This covers user temp folders, user caches, app logs, crash reports, and browser/system cache folders that are safe to regenerate.

Cache cleanup is **app-aware and safe by construction** — it never does a blanket
`rm -rf ~/Library/Caches/*`:

- **Orphan caches** (a cache/container folder whose owning app is no longer
  installed) are removed in full. These can never regenerate, so they are pure
  junk — this is usually the biggest silent reclaim from long-ago uninstalled apps.
- **Caches of still-installed apps** keep only files older than the age threshold
  (default 7 days); recent cache is left so the app doesn't misbehave.
- **Logs** keep only entries older than 7 days (`--min-age-days 7` default); the
  helper never deletes recent logs or does `rm -rf ~/Library/Logs/*`.
- Folders whose name can't be matched to an installed app are skipped, not deleted.

```bash
python3 ./scripts/storage_cleanup.py --min-age-days 7
python3 ./scripts/storage_cleanup.py --min-age-days 7 --apply
```

### Developer Caches

Use when the user is a developer or the dry-run shows Xcode, Visual Studio, Gradle, Maven, or Cargo caches are large. Expect first builds or IDE startup to be slower after cleanup.

```bash
python3 ./scripts/storage_cleanup.py --include-developer --min-age-days 7
python3 ./scripts/storage_cleanup.py --include-developer --min-age-days 7 --apply
```

### Package Caches

Prefer package-manager commands because they understand their own cache layout (see [public-cleanup-guidance.md](./references/public-cleanup-guidance.md)):

```bash
# npm
npm cache verify
npm cache clean --force

# Python pip
python -m pip cache info
python -m pip cache purge

# pnpm and Yarn
pnpm store prune
yarn cache clean

# Conda
conda clean --all --dry-run
conda clean --all --yes

# Homebrew (macOS)
brew cleanup --dry-run
brew cleanup
```

Use the helper's package cache scan only when command-specific cleanup is unavailable or the user approves direct cache deletion.

```bash
python3 ./scripts/storage_cleanup.py --include-package-caches --min-age-days 30
python3 ./scripts/storage_cleanup.py --include-package-caches --min-age-days 30 --apply
```

### Trash Or Recycle Bin

Emptying trash can permanently remove files the user may still expect to recover. Ask explicitly before using this level.

```bash
python3 ./scripts/storage_cleanup.py --include-trash --min-age-days 30
python3 ./scripts/storage_cleanup.py --include-trash --min-age-days 30 --apply
```

For OS-specific trash/recycle handling (Storage Sense on Windows, Trash on macOS/Linux), see the per-platform reference docs.

## Safety Rules

- Always run dry-run first unless the user already gave a precise delete command.
- Never use broad commands such as `rm -rf ~/Library/Caches/*`, `rm -rf ~/Library/*`, `rm -rf %LOCALAPPDATA%`, `rm -rf ~/.cache/*`, `del /s C:\Windows\Temp`, or recursive delete from a drive root.
- macOS cache cleanup is app-aware: only **orphan** cache/container folders (whose app is no longer installed) are removed entirely. Caches of still-installed apps are never bulk-removed — only files older than the age threshold are cleaned.
- Login/session safety: cookies (`~/Library/Cookies`, browser `Application Support`), Keychain (`~/Library/Keychains`), and app sign-in tokens (`~/Library/Application Support`, installed `Containers`) are never touched. Deleting `~/Library/Caches` does **not** log the user out. On a freshly set-up laptop, caches are recent (kept by the 7-day rule) and orphans are rare, so cleanup will not force re-authentication.
- Do not follow symlinks or junctions while cleaning.
- Avoid deleting files modified recently; default to 7 days for OS temp/cache/logs and 30 days for package caches or trash. Logs are limited to 7+ days and recent logs are always kept.
- Treat cloud-synced folders, Downloads, Desktop, Documents, media libraries, virtual machines, databases, Docker volumes, and local Git worktrees as user data.
- For Docker, avoid `--volumes` unless the user confirms containers do not rely on those volumes for data.

## Platform References

Read the matching platform doc for built-in OS tools, safe-to-clean locations, developer and package cache paths, what not to delete, useful commands, and vendor links:

- [macOS cleanup guidance](./references/macos-cleanup.md)
- [Windows cleanup guidance](./references/windows-cleanup.md)
- [Linux cleanup guidance](./references/linux-cleanup.md)
- [Public cleanup guidance](./references/public-cleanup-guidance.md) — cross-platform package-manager commands (npm, pip, pnpm, Yarn, conda, Homebrew) and Docker pruning.
