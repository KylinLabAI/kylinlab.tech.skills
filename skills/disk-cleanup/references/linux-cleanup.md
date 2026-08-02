# Linux Cleanup Guidance

How to clean up useless files and folders on Linux safely. Prefer package-manager commands and an allowlisted dry-run scan before removing anything. Paths below assume a freedesktop.org-compliant user layout (`~/.cache`, `~/.local/share`, `~/.config`).

## Inspect Free Space First

- `df -h` — free space per filesystem.
- `df -h /` — quick boot volume check.
- `du -sh ~/.cache ~/.local/share/Trash 2>/dev/null` — size of common regenerable folders.
- `ncdu /` (if installed) — interactive disk usage browser.

## Built-in Tools To Use First

- Use the distribution's package manager cleanup commands first (see below).
- Empty Trash only with explicit user approval — files may still be expected for recovery.
- Use `journalctl` to manage systemd journal logs (safe, vendor-supported).

## Safe To Clean (Regenerable)

These are scanned by the bundled helper under the `safe` profile:

- `$TMPDIR` (fallback `/tmp` for the current user) — temporary files.
- `~/.cache` — per-user application caches (regenerate on demand).
- `~/.local/share/logs` — per-user logs.
- `~/.local/share/recently-used.xbel` is NOT touched (user state).

## Developer Caches

Scanned under the `developer` profile (`--include-developer`). Expect first builds to be slower after cleanup:

- `~/.gradle/caches` — Gradle build caches.
- `~/.m2/repository` — Maven local repository (only with user approval; redownloads required).
- `~/.nuget/packages` — NuGet package cache.
- `~/.cargo/registry/cache` — Cargo registry cache.
- `~/.rustup/toolchains/*/share/doc` — Rust toolchain docs (optional).

## Package Caches

Scanned under the `package-caches` profile (`--include-package-caches`). Prefer manager-specific commands first — see [public-cleanup-guidance.md](./public-cleanup-guidance.md) for npm, pip, pnpm, Yarn, and conda commands.

Helper-scanned locations:

- `~/.npm`, `~/.cache/pip`, `~/.cache/yarn`, `~/.cache/pnpm`
- `~/.pnpm-store`

### Distribution Package Managers

```bash
# Debian / Ubuntu (apt)
sudo apt-get clean          # removes downloaded archive files from /var/cache/apt/archives
sudo apt-get autoremove     # removes auto-installed dependencies no longer needed

# Fedora / RHEL (dnf)
sudo dnf clean all
sudo dnf autoremove

# Arch Linux (pacman)
sudo pacman -Sc             # removes uninstalled packages from cache
sudo pacman -Sc --noconfirm # also removes all but installed versions

# openSUSE (zypper)
sudo zypper clean --all
```

## Trash

Scanned under the `trash` profile (`--include-trash`). Requires explicit approval — emptying Trash permanently removes files the user may still expect to recover:

- `~/.local/share/Trash` (freedesktop.org Trash spec; supported by GNOME, KDE, and most file managers).

## Systemd Journal Logs

Safe to vacuum old journal entries (vendor-supported):

```bash
journalctl --disk-usage
sudo journalctl --vacuum-time=2weeks   # keep only last 2 weeks
sudo journalctl --vacuum-size=100M     # cap journal to 100 MB
```

## Do Not Delete

Unless the user explicitly selects these items:

- `~/.config` — per-user application settings (often user-visible state, not regenerable).
- `~/.local/share` (except Trash and logs) — application data.
- Downloads, Desktop, Documents.
- System folders (`/usr`, `/var/lib`, `/boot`, `/etc`, `/proc`, `/sys`).
- Snap/Flatpak app data unless removed through the package manager.

## Useful Commands

```bash
df -h /
du -sh ~/.cache ~/.local/share/Trash 2>/dev/null
journalctl --disk-usage
```

## Vendor References

- systemd, `journalctl`: https://www.freedesktop.org/software/systemd/man/journalctl.html
- freedesktop.org Trash specification: https://specifications.freedesktop.org/trash-spec/trashspec-1.0.html
- Debian, `apt-get`: https://manpages.debian.org/apt/apt-get.8
- Fedora, `dnf clean`: https://dnf.readthedocs.io/en/latest/command_ref.html#clean-command-label
- Arch Linux, `pacman -Sc`: https://man.archlinux.org/man/pacman.8
