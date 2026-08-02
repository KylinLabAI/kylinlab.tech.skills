#!/usr/bin/env python3
"""Windows cleanup targets for the disk-cleanup helper.

Each entry is a `CleanupTarget` describing a known regenerable location on
Windows. Targets are grouped by cleanup profile. See
`references/windows-cleanup.md` for the human-facing guidance.
"""

from __future__ import annotations

from cleanup_common import CleanupTarget

TARGETS: tuple[CleanupTarget, ...] = (
    CleanupTarget(
        "windows-user-temp",
        "windows",
        "safe",
        ("%TEMP%", "%LOCALAPPDATA%\\Temp"),
        "Current user's Windows temporary folders.",
    ),
    CleanupTarget(
        "windows-user-caches",
        "windows",
        "safe",
        (
            "%LOCALAPPDATA%\\Microsoft\\Windows\\INetCache",
            "%LOCALAPPDATA%\\Microsoft\\Windows\\Explorer",
            "%LOCALAPPDATA%\\Microsoft\\Windows\\Caches",
        ),
        "Per-user Windows and shell cache folders.",
    ),
    CleanupTarget(
        "windows-error-reports",
        "windows",
        "safe",
        (
            "%LOCALAPPDATA%\\CrashDumps",
            "%LOCALAPPDATA%\\Microsoft\\Windows\\WER\\ReportArchive",
            "%LOCALAPPDATA%\\Microsoft\\Windows\\WER\\ReportQueue",
        ),
        "Crash dumps and Windows Error Reporting archives for the current user.",
    ),
    CleanupTarget(
        "windows-visual-studio-caches",
        "windows",
        "developer",
        (
            "%LOCALAPPDATA%\\Microsoft\\VisualStudio\\*\\ComponentModelCache",
            "%LOCALAPPDATA%\\Microsoft\\VisualStudio\\*\\Designer\\ShadowCache",
        ),
        "Visual Studio caches that regenerate.",
    ),
    CleanupTarget(
        "windows-package-caches",
        "windows",
        "package-caches",
        (
            "%LOCALAPPDATA%\\npm-cache",
            "%LOCALAPPDATA%\\pip\\Cache",
            "%LOCALAPPDATA%\\Yarn\\Cache",
            "%LOCALAPPDATA%\\pnpm\\store",
            "%USERPROFILE%\\.npm",
            "%USERPROFILE%\\.cache\\pip",
            "%USERPROFILE%\\.pnpm-store",
        ),
        "Package manager caches. Prefer manager-specific cleanup commands when available.",
    ),
)
