#!/usr/bin/env python3
"""Shared scanning/reporting logic for the disk-cleanup helper.

Platform-specific cleanup targets live in separate per-platform modules:
`macos_targets`, `windows_targets`, `linux_targets`. This module holds the
dataclasses, filesystem scanning, path resolution, and reporting that are
identical across platforms.
"""

from __future__ import annotations

import glob
import os
import platform as platform_module
import re
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CleanupTarget:
    key: str
    platform: str
    profile: str
    patterns: tuple[str, ...]
    description: str
    mode: str = "old-files"


@dataclass
class TargetReport:
    key: str
    profile: str
    root: str
    mode: str
    description: str
    exists: bool
    bytes_reclaimable: int = 0
    files_matched: int = 0
    items_matched: int = 0
    dirs_removed: int = 0
    skipped_recent: int = 0
    skipped_symlink: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class CleanupReport:
    platform: str
    dry_run: bool
    min_age_days: float
    active_profiles: list[str]
    generated_at: str
    total_bytes_reclaimable: int
    total_files_matched: int
    total_items_matched: int
    targets: list[TargetReport]


MAX_LISTED_TARGET_PATHS = 20


def detect_platform(value: str) -> str:
    if value != "auto":
        return value
    system = platform_module.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    if system == "linux":
        return "linux"
    raise SystemExit(f"Unsupported platform for this helper: {system or 'unknown'}")


def expand_windows_vars(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        return os.environ.get(name, os.environ.get(name.upper(), match.group(0)))

    return re.sub(r"%([^%]+)%", repl, text)


def resolve_pattern(pattern: str, target_platform: str) -> list[Path]:
    expanded = pattern
    if target_platform == "windows":
        expanded = expand_windows_vars(expanded)
    expanded = os.path.expandvars(os.path.expanduser(expanded))
    if "$" in expanded or re.search(r"%[^%]+%", expanded):
        return []
    paths = glob.glob(expanded)
    if not paths and not glob.has_magic(expanded):
        paths = [expanded]
    return [Path(path) for path in paths]


def display_path(path: Path) -> str:
    try:
        home = Path.home().resolve()
        resolved = path.resolve()
        if resolved == home:
            return "~"
        if home in resolved.parents:
            return "~/" + str(resolved.relative_to(home))
    except OSError:
        pass
    return str(path)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(path.lstat().st_mode)
    except OSError:
        return False


def scan_old_files(root: Path, target: CleanupTarget, cutoff: float, apply: bool) -> TargetReport:
    report = TargetReport(
        key=target.key,
        profile=target.profile,
        root=display_path(root),
        mode=target.mode,
        description=target.description,
        exists=root.exists(),
    )
    if not root.exists():
        return report
    if is_symlink(root):
        report.skipped_symlink += 1
        return report
    if not root.is_dir():
        report.errors.append("Target is not a directory")
        return report

    for dirpath, _, filenames in os.walk(root, topdown=False, followlinks=False):
        current_dir = Path(dirpath)
        for filename in filenames:
            path = current_dir / filename
            try:
                st = path.lstat()
            except OSError as exc:
                report.errors.append(f"{display_path(path)}: stat failed: {exc}")
                continue
            if stat.S_ISLNK(st.st_mode):
                report.skipped_symlink += 1
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            if st.st_mtime > cutoff:
                report.skipped_recent += 1
                continue
            report.bytes_reclaimable += st.st_size
            report.files_matched += 1
            report.items_matched += 1
            if apply:
                try:
                    path.unlink()
                except OSError as exc:
                    report.errors.append(f"{display_path(path)}: delete failed: {exc}")

        if apply and current_dir != root:
            try:
                current_dir.rmdir()
                report.dirs_removed += 1
            except OSError:
                pass
    return report


def tree_stats_if_old(path: Path, cutoff: float, report: TargetReport) -> tuple[int, int, bool]:
    try:
        st = path.lstat()
    except OSError as exc:
        report.errors.append(f"{display_path(path)}: stat failed: {exc}")
        return 0, 0, False
    if stat.S_ISLNK(st.st_mode):
        report.skipped_symlink += 1
        return 0, 0, False
    if st.st_mtime > cutoff:
        report.skipped_recent += 1
        return 0, 0, False
    if stat.S_ISREG(st.st_mode):
        return st.st_size, 1, True
    if not stat.S_ISDIR(st.st_mode):
        return 0, 0, False

    total_size = 0
    total_files = 0
    for dirpath, _, filenames in os.walk(path, topdown=True, followlinks=False):
        current_dir = Path(dirpath)
        try:
            dir_stat = current_dir.lstat()
        except OSError as exc:
            report.errors.append(f"{display_path(current_dir)}: stat failed: {exc}")
            return 0, 0, False
        if dir_stat.st_mtime > cutoff:
            report.skipped_recent += 1
            return 0, 0, False
        for filename in filenames:
            child = current_dir / filename
            try:
                child_stat = child.lstat()
            except OSError as exc:
                report.errors.append(f"{display_path(child)}: stat failed: {exc}")
                return 0, 0, False
            if stat.S_ISLNK(child_stat.st_mode):
                report.skipped_symlink += 1
                return 0, 0, False
            if child_stat.st_mtime > cutoff:
                report.skipped_recent += 1
                return 0, 0, False
            if stat.S_ISREG(child_stat.st_mode):
                total_size += child_stat.st_size
                total_files += 1
    return total_size, total_files, True


def scan_old_children(root: Path, target: CleanupTarget, cutoff: float, apply: bool) -> TargetReport:
    report = TargetReport(
        key=target.key,
        profile=target.profile,
        root=display_path(root),
        mode=target.mode,
        description=target.description,
        exists=root.exists(),
    )
    if not root.exists():
        return report
    if is_symlink(root):
        report.skipped_symlink += 1
        return report
    if not root.is_dir():
        report.errors.append("Target is not a directory")
        return report

    try:
        children = list(root.iterdir())
    except OSError as exc:
        report.errors.append(f"{display_path(root)}: list failed: {exc}")
        return report

    for child in children:
        size, files, safe_to_remove = tree_stats_if_old(child, cutoff, report)
        if not safe_to_remove:
            continue
        report.bytes_reclaimable += size
        report.files_matched += files
        report.items_matched += 1
        if apply:
            try:
                if child.is_dir() and not is_symlink(child):
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError as exc:
                report.errors.append(f"{display_path(child)}: delete failed: {exc}")
    return report
