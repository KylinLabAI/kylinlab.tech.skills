# macOS Cleanup Guidance

How to clean up useless files and folders on macOS safely. Prefer built-in OS tools and an allowlisted dry-run scan before removing anything.

## Inspect Free Space First

- Apple Menu > System Settings > General > Storage — shows categories and recommendations.
- `df -h /` — quick free-space check on the boot volume.
- `du -sh ~/Library/Caches ~/Library/Logs 2>/dev/null` — size of common regenerable folders.

## Built-in Tools To Use First

- Start with the Storage panel and its recommendations (empty Trash, reduce clutter, optimize storage).
- Empty Trash only with explicit user approval — files may still be expected for recovery.
- Safe mode is an Apple-supported way to clear some system caches for short-term free space. Use only when needed.

## Safe To Clean (Regenerable)

These are scanned by the bundled helper under the `safe` profile:

- `$TMPDIR` — current user's temporary directory.
- `~/Library/Caches` — per-user application caches (regenerate on demand).
- `~/Library/Containers/*/Data/Library/Caches` — sandboxed app caches.
- `~/Library/Logs` — per-user logs.
- `~/Library/Application Support/CrashReporter` — crash reports.
- `~/Library/DiagnosticReports` — diagnostic reports.

## Developer Caches

Scanned under the `developer` profile (`--include-developer`). Expect first builds or IDE startup to be slower after cleanup:

- `~/Library/Developer/Xcode/DerivedData` — Xcode build outputs.
- `~/Library/Developer/CoreSimulator/Caches` — iOS simulator caches.

## Package Caches

Scanned under the `package-caches` profile (`--include-package-caches`). Prefer manager-specific commands first — see [public-cleanup-guidance.md](./public-cleanup-guidance.md) for npm, pip, pnpm, Yarn, conda, and Homebrew commands.

Helper-scanned locations:

- `~/.npm`, `~/.cache/pip`, `~/Library/Caches/pip`
- `~/Library/Caches/Homebrew`, `~/Library/Caches/Yarn`, `~/.cache/yarn`
- `~/.pnpm-store`, `~/.cache/pnpm`

Homebrew-specific (macOS only):

```bash
brew cleanup --dry-run
brew cleanup
```

## Trash

Scanned under the `trash` profile (`--include-trash`). Requires explicit approval — emptying Trash permanently removes files the user may still expect to recover:

- `~/.Trash`

## Time Machine Local Snapshots

Do not manually delete Time Machine local snapshots by walking system folders. macOS treats them as available space and deletes them as needed. If the user insists, guide them through Time Machine settings rather than deleting hidden files.

Useful command to list local snapshots:

```bash
tmutil listlocalsnapshots / 2>/dev/null
```

## Do Not Delete

Unless the user explicitly selects these items:

- Photos libraries, Mail, Messages.
- iPhone/iPad backups.
- Downloads, Desktop, Documents.
- Large documents and app data.
- System folders (`/System`, `/Library`, `/usr`, etc.).

## Useful Commands

```bash
df -h /
du -sh ~/Library/Caches ~/Library/Logs 2>/dev/null
tmutil listlocalsnapshots / 2>/dev/null
```

## Vendor References

- Apple Support, "Free up storage space on Mac": https://support.apple.com/en-us/102624
- Apple Support, "About Time Machine local snapshots": https://support.apple.com/en-la/102154
