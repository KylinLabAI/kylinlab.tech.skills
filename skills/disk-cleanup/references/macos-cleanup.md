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

These are scanned by the bundled helper under the `safe` profile. The helper is
**app-aware**, so it never runs a blanket `rm -rf ~/Library/Caches/*`:

- `~/Library/Caches` — per-user application caches.
  - **Orphan subfolders** (the cache's owning app is no longer installed) are
    removed in full — they can never regenerate, so they are pure junk. This is
    usually the biggest silent reclaim from apps you uninstalled long ago.
  - Subfolders whose app is **still installed** keep only files older than the
    age threshold (default 7 days); recent cache is preserved so the app keeps working.
  - Folders whose name can't be matched to an installed app are skipped, never deleted.
- `~/Library/Containers` — sandboxed-app containers.
  - **Whole containers of uninstalled apps** are removed (per Apple guidance,
    leftover data from uninstalled apps is safe to delete).
  - Containers of still-installed apps are left untouched — they may hold user data.
- `~/Library/Logs` — per-user logs. Only entries **older than 7 days** are
  removed; recent logs are always kept (the helper never does `rm -rf ~/Library/Logs/*`).
- `~/Library/Application Support/CrashReporter` — crash reports (age-limited).
- `~/Library/DiagnosticReports` — diagnostic reports (age-limited).
- `$TMPDIR` — current user's temporary directory (age-limited).

## Per-App Logs and Caches Under Application Support

In addition to the named paths above, the helper scans **every** app directory
under `~/Library/Application Support/*` for the well-known regenerable
subfolders and age-expires (default 7 days) the files inside them:

- `Logs`, `logs`
- `Cache`, `Caches`
- `CrashReport`, `CrashReporter`, `DiagnosticReports`

This is app-aware and safe by construction: only those specific subfolder names
are descended into, so an app's other data (settings, `Data`, databases,
`sessions.vscdb`, `Cookies`, `Local Storage`, etc.) is never touched. It never
runs a blanket `rm -rf ~/Library/Application Support/*`. CodeBuddy apps are
handled by their dedicated, more thorough targets (see below) and are skipped by
this generic scan to avoid double counting.

```bash
python3 ./scripts/storage_cleanup.py --min-age-days 7
python3 ./scripts/storage_cleanup.py --min-age-days 7 --apply
```

If a scan reports an unexpected app folder, review the matched subpaths before
applying — a handful of apps misuse these names for non-cache data, and the
age limit (recent files kept) is the safety net.

## CodeBuddy App Logs, Crash Dumps, and Caches

CodeBuddy ships two data areas under `~/Library/Application Support`: a VS
Code/Cursor **extension** (`CodeBuddyExtension`) and the standalone **CN Electron
app** (`CodeBuddy CN`). Of their subfolders, only a few are safe to clean and
they fall into clear groups. The helper covers the safe ones under the `safe`
profile (default run, age-limited); the user-data folder is opt-in only
(`--include-app-data`).

### Safe — remove by age (covered by the `safe` profile)

| Path | What it is | Why safe |
| --- | --- | --- |
| `CodeBuddyExtension/Logs` | Extension `.log` files | Pure diagnostics; a fresh log is written each launch. |
| `CodeBuddyExtension/Cache` | Extension cache | Regenerable; keeps only recent files by age. |
| `CodeBuddy CN/logs` | CN app `.log` files | Pure diagnostics. |
| `CodeBuddy CN/CrashReport` | `.dmp`/`.dat` crash dumps | Always junk once a crash is past; age-limited keeps the newest for debugging. |
| `CodeBuddy CN/Cache`, `CachedData`, `Code Cache`, `GPUCache`, `DawnGraphiteCache`, `DawnWebGPUCache` | Electron HTTP / V8 / GPU / WebGPU caches | Regenerable; rebuild on next launch. |

```bash
python3 ./scripts/storage_cleanup.py --min-age-days 7
python3 ./scripts/storage_cleanup.py --min-age-days 7 --apply
```

### Keep — user data (never auto-deleted)

- `CodeBuddyExtension/Data` — conversation history and generated artifacts
  (`.json`/`.md`/`.py`/`.rs`/`.yml`, tens of thousands of files). This is the
  user's actual work output, not cache. **Do not add it to a default scan.**
  Only offer `--include-app-data` when the user explicitly wants to purge old
  history, and even then only files older than the age threshold are removed:
  ```bash
  python3 ./scripts/storage_cleanup.py --include-app-data --min-age-days 7
  ```

### Snapshot screenshot cache — remove wholesale (opt-in)

Inside `Data`, the path `Data/<id>/CodeBuddyIDE/<id>/history/<id>/<id>/assets`
holds captured **snapshot screenshots** (e.g. `Screenshot 2026-09-23 at
….png`). These are preview thumbnails of conversation turns, not conversation
content, so they are safe to delete entirely. The helper removes every such
`assets` folder at once (no age limit) when `--include-app-data` is set:

```bash
python3 ./scripts/storage_cleanup.py --include-app-data --min-age-days 7
python3 ./scripts/storage_cleanup.py --include-app-data --min-age-days 7 --apply
```

The match is scoped to `assets` folders that sit beneath a `history` ancestor,
so unrelated `assets` directories elsewhere in `Data` are never touched.

### Keep — session state (do not touch)

Within `CodeBuddy CN`, these hold session/login state and must be left alone:
`Cookies`, `Local Storage`, `Session Storage`, `WebStorage`, `User`,
`codebuddy-sessions.vscdb`, `machineid`, `last-session.json`, `Preferences`,
`TransportSecurity`, `Trust Tokens`, `Network Persistent State`, `SharedStorage`,
and the various `*-wal`/`-journal` companions.

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

## Login & Session Safety (cookies, keychain, tokens)

The fear with aggressive cleanup is being logged out everywhere on a machine you
just set up. Understanding *where* session state lives shows why the scan above
is safe:

- **Cookies / website logins** live in `~/Library/Cookies` and per-app
  `~/Library/Containers/<id>/Data/Library/Cookies`, and browsers keep their own
  under `~/Library/Application Support/<browser>/.../Cookies` (a SQLite DB).
  They are **not** under `~/Library/Caches`, so deleting caches never logs you
  out of websites.
- **Passwords and many "remember me" tokens** live in **Keychain**
  (`~/Library/Keychains`) and iCloud Keychain — untouched by any cleanup here.
- **App sign-in state** (e.g. Slack, Spotify, mail accounts) is stored in
  `~/Library/Application Support/<app>` or inside an installed app's
  `~/Library/Containers/<id>/Data/Library` — not in Caches.

What the helper actually touches, and why it preserves sessions:

- `~/Library/Caches` — orphan subfolders (app uninstalled) removed; still-installed
  apps keep only age-thresholded files. **No cookies, keychain, or tokens here.**
- `~/Library/Logs` — age-limited. **No session data here.**
- `~/Library/Containers` — **only whole containers of uninstalled apps** are
  removed (the app and its login state are already gone). Containers of
  still-installed apps are never touched, so their cookies/tokens survive.

Because of this, running the helper on a freshly set-up laptop is low-risk:
caches are recent (kept by the 7-day rule) and there are few or no orphans, so
you will not be forced to re-authenticate.

Extra precautions worth recommending to the user:
- Before any first-time or "new laptop" cleanup, make sure Keychain and any
  needed browser profiles are backed up / synced (iCloud Keychain, browser sync).
- Never add `~/Library/Cookies`, `~/Library/Keychains`, `~/Library/Application
  Support`, or `~/Library/Preferences` to a cleanup target.
- If an app must keep its session across a manual clear, quit it first and let it
  re-cache; logins are not stored in Caches, so this is about convenience, not auth.

## Vendor References

- Apple Support, "Free up storage space on Mac": https://support.apple.com/en-us/102624
- Apple Support, "About Time Machine local snapshots": https://support.apple.com/en-la/102154
- Apple Support, "View APFS snapshots in Disk Utility on Mac": https://support.apple.com/guide/disk-utility/view-apfs-snapshots-dskuf82354dc/mac
- Apple Community user guide, "How to free up System Data and other storage on your Mac": https://discussions.apple.com/docs/DOC-250010335
