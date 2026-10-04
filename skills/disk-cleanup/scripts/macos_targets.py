#!/usr/bin/env python3
"""macOS cleanup targets for the disk-cleanup helper.

Each entry is a `CleanupTarget` describing a known regenerable location on
macOS. Targets are grouped by cleanup profile. See
`references/macos-cleanup.md` for the human-facing guidance.
"""

from __future__ import annotations

from cleanup_common import CleanupTarget

TARGETS: tuple[CleanupTarget, ...] = (
    CleanupTarget(
        "macos-user-temp",
        "macos",
        "safe",
        ("$TMPDIR",),
        "Current user's macOS temporary directory.",
    ),
    CleanupTarget(
        "macos-user-caches",
        "macos",
        "safe",
        ("~/Library/Caches",),
        "Per-user application caches. Orphan folders (whose app is no longer "
        "installed) are removed entirely; caches of still-installed apps keep "
        "only files older than the age threshold.",
        mode="orphan-caches",
    ),
    CleanupTarget(
        "macos-containers-orphans",
        "macos",
        "safe",
        ("~/Library/Containers",),
        "Sandboxed-app containers. Whole containers belonging to uninstalled "
        "apps are removed; containers of still-installed apps are left untouched "
        "(they may hold user data).",
        mode="orphan-folders",
    ),
    CleanupTarget(
        "macos-user-logs",
        "macos",
        "safe",
        ("~/Library/Logs", "~/Library/Application Support/CrashReporter", "~/Library/DiagnosticReports"),
        "Per-user logs and crash diagnostics.",
    ),
    CleanupTarget(
        "macos-appsupport-logs-cache",
        "macos",
        "safe",
        ("~/Library/Application Support/*",),
        "Per-app Logs/Cache/CrashReport/CrashReporter/DiagnosticReports subfolders "
        "inside ~/Library/Application Support for every installed app. Only the "
        "well-known regenerable subfolder names are age-expired; all other app "
        "data is left untouched. CodeBuddy apps are covered by their dedicated "
        "targets and skipped here.",
        mode="appsupport-logs-cache",
    ),
    CleanupTarget(
        "macos-xcode-derived-data",
        "macos",
        "developer",
        ("~/Library/Developer/Xcode/DerivedData", "~/Library/Developer/CoreSimulator/Caches"),
        "Xcode and simulator build/cache artifacts that regenerate.",
    ),
    CleanupTarget(
        "macos-xcode-device-support",
        "macos",
        "developer",
        ("~/Library/Developer/Xcode/iOS DeviceSupport", "~/Library/Developer/CoreSimulator/Logs"),
        "Xcode iOS DeviceSupport symbol caches and simulator logs that regenerate on the next device connect or build.",
    ),
    CleanupTarget(
        "macos-xcode-archives",
        "macos",
        "developer",
        ("~/Library/Developer/Xcode/Archives",),
        "Old Xcode app archives. Deleting removes the ability to re-upload that build; only clean archives past the age threshold.",
    ),
    CleanupTarget(
        "macos-package-caches",
        "macos",
        "package-caches",
        (
            "~/.npm",
            "~/.cache/pip",
            "~/Library/Caches/pip",
            "~/Library/Caches/Homebrew",
            "~/Library/Caches/Yarn",
            "~/.cache/yarn",
            "~/.pnpm-store",
            "~/.cache/pnpm",
        ),
        "Package manager caches. Prefer manager-specific cleanup commands when available.",
    ),
    CleanupTarget(
        "macos-trash",
        "macos",
        "trash",
        ("~/.Trash",),
        "Trash items. Requires explicit user approval.",
        mode="old-children",
    ),
    CleanupTarget(
        "macos-codebuddy-extension-logs",
        "macos",
        "safe",
        ("~/Library/Application Support/CodeBuddyExtension/Logs",),
        "CodeBuddy extension (VS Code/Cursor) logs. Pure diagnostics; the app "
        "writes a fresh log each launch, so anything older than the age "
        "threshold is safe to drop.",
    ),
    CleanupTarget(
        "macos-codebuddy-extension-cache",
        "macos",
        "safe",
        ("~/Library/Application Support/CodeBuddyExtension/Cache",),
        "CodeBuddy extension cache. Regenerable; only files older than the age "
        "threshold are removed so the extension stays responsive.",
    ),
    CleanupTarget(
        "macos-codebuddy-cn-logs",
        "macos",
        "safe",
        ("~/Library/Application Support/CodeBuddy CN/logs",),
        "CodeBuddy CN (Electron app) logs. Pure diagnostics, safe to age-expire.",
    ),
    CleanupTarget(
        "macos-codebuddy-cn-crashreports",
        "macos",
        "safe",
        ("~/Library/Application Support/CodeBuddy CN/CrashReport",),
        "CodeBuddy CN crash dumps (.dmp/.dat). Always junk once a crash is "
        "past; age-limited removal keeps only the most recent crash for "
        "debugging.",
    ),
    CleanupTarget(
        "macos-codebuddy-cn-caches",
        "macos",
        "safe",
        (
            "~/Library/Application Support/CodeBuddy CN/Cache",
            "~/Library/Application Support/CodeBuddy CN/CachedData",
            "~/Library/Application Support/CodeBuddy CN/Code Cache",
            "~/Library/Application Support/CodeBuddy CN/GPUCache",
            "~/Library/Application Support/CodeBuddy CN/DawnGraphiteCache",
            "~/Library/Application Support/CodeBuddy CN/DawnWebGPUCache",
        ),
        "CodeBuddy CN regenerable Electron caches (HTTP, V8, GPU, WebGPU). Safe "
        "to age-expire; they rebuild on next launch.",
    ),
    CleanupTarget(
        "macos-codebuddy-extension-data",
        "macos",
        "app-data",
        ("~/Library/Application Support/CodeBuddyExtension/Data",),
        "CodeBuddy extension conversation history and generated artifacts "
        "(json/md/py/rs/yml). User data — only cleaned when the user explicitly "
        "opts in with --include-app-data, and even then only files older than "
        "the age threshold. Recent history is always kept. The snapshot "
        "screenshot cache (history/* /assets) is excluded here and handled "
        "wholesale by the dedicated snapshot-assets target to avoid double "
        "counting.",
        mode="old-files",
        skip_dirs_named=("assets",),
    ),
    CleanupTarget(
        "macos-codebuddy-extension-snapshot-assets",
        "macos",
        "app-data",
        ("~/Library/Application Support/CodeBuddyExtension/Data",),
        "CodeBuddy extension snapshot screenshots cached under "
        "Data/*/.../history/*/*/assets. These are captured previews, not user "
        "data, so every matching assets folder is removed wholesale. Opt-in "
        "(--include-app-data).",
        mode="nested-dirs",
        remove_dirs_named="assets",
    ),
)
