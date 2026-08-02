#!/usr/bin/env python3
"""Linux cleanup targets for the disk-cleanup helper.

Each entry is a `CleanupTarget` describing a known regenerable location on
Linux, assuming a freedesktop.org-compliant user layout. Targets are grouped
by cleanup profile. See `references/linux-cleanup.md` for the human-facing
guidance.

Note: `$TMPDIR` resolves only when set in the environment; on most Linux
desktops it is unset and `/tmp` is used system-wide. `/tmp` is intentionally
NOT scanned by the safe profile because it is shared across users.
"""

from __future__ import annotations

from cleanup_common import CleanupTarget

TARGETS: tuple[CleanupTarget, ...] = (
    CleanupTarget(
        "linux-user-temp",
        "linux",
        "safe",
        ("$TMPDIR",),
        "Current user's Linux temporary directory (only scanned when $TMPDIR is set).",
    ),
    CleanupTarget(
        "linux-user-caches",
        "linux",
        "safe",
        ("~/.cache",),
        "Per-user application caches (regenerate on demand).",
    ),
    CleanupTarget(
        "linux-user-logs",
        "linux",
        "safe",
        ("~/.local/share/logs",),
        "Per-user logs.",
    ),
    CleanupTarget(
        "linux-developer-caches",
        "linux",
        "developer",
        (
            "~/.gradle/caches",
            "~/.m2/repository",
            "~/.nuget/packages",
            "~/.cargo/registry/cache",
        ),
        "Developer build caches. Some (e.g. Maven, NuGet) require redownloads after cleanup.",
    ),
    CleanupTarget(
        "linux-package-caches",
        "linux",
        "package-caches",
        (
            "~/.npm",
            "~/.cache/pip",
            "~/.cache/yarn",
            "~/.cache/pnpm",
            "~/.pnpm-store",
        ),
        "Package manager caches. Prefer manager-specific cleanup commands when available.",
    ),
    CleanupTarget(
        "linux-trash",
        "linux",
        "trash",
        ("~/.local/share/Trash",),
        "Trash items (freedesktop.org spec). Requires explicit user approval.",
        mode="old-children",
    ),
)
