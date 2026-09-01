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

- `~/Library/Developer/Xcode/DerivedData` — Xcode build outputs (often 5–20 GB).
- `~/Library/Developer/Xcode/iOS DeviceSupport` — per-OS symbol caches regenerated on next device connect.
- `~/Library/Developer/Xcode/Archives` — app archives. Deleting an archive removes the ability to re-upload that build; only clean archives older than the age threshold and confirm the user no longer needs them.
- `~/Library/Developer/CoreSimulator/Caches` — iOS simulator caches.
- `~/Library/Developer/CoreSimulator/Logs` — simulator logs.

Community experience (mac-cleanup, cleanup, clean_my_mac projects) consistently finds Xcode artifacts to be the single largest reclaimable category for developers — commonly 10–90 GB.

Do not delete `~/Library/Developer/CoreSimulator/Devices` wholesale; simulator devices can hold user app data. Prefer `xcrun simctl delete unavailable` to remove only devices tied to unavailable runtimes.

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

Do not manually delete Time Machine local snapshots by walking system folders. macOS treats them as available space and deletes them as needed. When snapshots are large and the user explicitly approves, use the supported interfaces rather than deleting hidden files:

```bash
# List local snapshots
tmutil listlocalsnapshots / 2>/dev/null

# Delete one snapshot by its listed date
tmutil deletelocalsnapshots <date>

# Ask macOS to thin snapshots aggressively (Apple-supported, non-destructive)
tmutil thinlocalsnapshots / 999999999999999 4
```

Snapshots can also be viewed and deleted in Disk Utility (View > Show APFS Snapshots). Never disable Time Machine itself just to reclaim space.

## System Data Hotspots (Report Only)

The "System Data" bar in System Settings > General > Storage is a catch-all. These known contributors can grow to tens of GB. Do not auto-delete them — report the path and size, then let the user decide:

- `/Library/Application Support/com.apple.idleassetsd/Customer/4KSDR240FPS` — 4K aerial/screen-saver videos (10–45 GB on Sonoma and later). They re-download if a dynamic wallpaper or aerial screen saver is active; advise setting a static wallpaper first.
- `~/Library/Application Support/MobileSync/Backup` — iPhone/iPad backups; delete only via Finder or System Settings device management, never by `rm`.
- `~/Library/Containers/com.apple.mail/Data/Library/Mail Downloads` — cached mail attachments.
- Old installers in Downloads: search Finder for `.dmg`, `.pkg`, `.zip` and delete installers that can be re-downloaded.
- `~/Library/Application Support/Google/Chrome/*/Code Cache` and similar Chromium `Code Cache`/`GPUCache` folders — regenerable browser caches.

For a visual inventory of what is actually inside System Data, suggest a disk inventory tool (OmniDiskSweeper, Disk Inventory X, DaisyDisk) or `du`:

```bash
sudo du -sh /Library/Application\ Support/* 2>/dev/null | sort -h | tail -20
du -sh ~/Library/Application\ Support/* 2>/dev/null | sort -h | tail -20
```

## Do Not Delete

Unless the user explicitly selects these items:

- Photos libraries, Mail, Messages.
- iPhone/iPad backups.
- Downloads, Desktop, Documents.
- Large documents and app data.
- System folders (`/System`, `/Library`, `/usr`, etc.).

Anti-patterns seen in unsafe cleanup scripts online — never run these:

- `rm -rf ~/Library/Application\ Support/*` — wipes saved data of installed apps, not just leftovers.
- `rm -rf ~/Library/Preferences/*.plist` — resets every app's settings, including still-installed ones.
- `rm -rf ~/Library/Saved\ Application\ State/*` — discards app autosave state.
- Third-party "cleaner/optimizer" apps: Apple Communities guidance is that they generally do more harm than good; prefer built-in tools and targeted, reviewed cleanup.

## Vendor References

- Apple Support, "Free up storage space on Mac": https://support.apple.com/en-us/102624
- Apple Support, "About Time Machine local snapshots": https://support.apple.com/en-la/102154
- Apple Support, "View APFS snapshots in Disk Utility on Mac": https://support.apple.com/guide/disk-utility/view-apfs-snapshots-dskuf82354dc/mac
- Apple Community user guide, "How to free up System Data and other storage on your Mac": https://discussions.apple.com/docs/DOC-250010335
