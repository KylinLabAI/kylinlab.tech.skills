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
        ("~/Library/Caches", "~/Library/Containers/*/Data/Library/Caches"),
        "Regenerable per-user application caches.",
    ),
    CleanupTarget(
        "macos-user-logs",
        "macos",
        "safe",
        ("~/Library/Logs", "~/Library/Application Support/CrashReporter", "~/Library/DiagnosticReports"),
        "Per-user logs and crash diagnostics.",
    ),
    CleanupTarget(
        "macos-xcode-derived-data",
        "macos",
        "developer",
        ("~/Library/Developer/Xcode/DerivedData", "~/Library/Developer/CoreSimulator/Caches"),
        "Xcode and simulator build/cache artifacts that regenerate.",
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
)
