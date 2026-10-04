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

from app_probe import is_app_installed, looks_like_bundle_id


@dataclass(frozen=True)
class CleanupTarget:
    key: str
    platform: str
    profile: str
    patterns: tuple[str, ...]
    description: str
    mode: str = "old-files"
    remove_dirs_named: str | None = None
    skip_dirs_named: tuple[str, ...] = ()


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
    orphans_removed: int = 0
    skipped_unknown: int = 0
    skipped_kept: int = 0
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

    # topdown=True lets us prune excluded subtrees before descending. We collect
    # visited dirs and remove empties in a post-pass (deepest first) so that a
    # parent directory is only removed after its children are gone.
    visited_dirs: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_dir = Path(dirpath)
        # Skip whole subtrees the target asked to exclude (e.g. the snapshot
        # screenshot cache, which is handled wholesale by a dedicated target).
        if current_dir.name in target.skip_dirs_named:
            dirnames[:] = []
            continue
        visited_dirs.append(current_dir)
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

    if apply:
        for current_dir in reversed(visited_dirs):
            if current_dir == root:
                continue
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


def dir_size_no_follow(path: Path) -> int:
    """Sum size of regular files under ``path`` without following symlinks."""
    total = 0
    for dirpath, _, filenames in os.walk(path, followlinks=False):
        current_dir = Path(dirpath)
        for filename in filenames:
            child = current_dir / filename
            try:
                st = child.lstat()
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                continue
            total += st.st_size
    return total


def scan_orphan(root: Path, target: CleanupTarget, cutoff: float, apply: bool, clean_installed_by_age: bool) -> TargetReport:
    """Clean cache/container folders that belong to uninstalled apps.

    For each child folder of ``root``:

    - if the name does not look like a bundle id, it is skipped (unknown);
    - if no installed app matches the name, the whole folder is orphaned and
      removed in full (it can never regenerate — pure junk);
    - if an app is still installed and ``clean_installed_by_age`` is set, only
      files older than ``cutoff`` are removed (the existing safe behavior);
    - if an app is still installed and ``clean_installed_by_age`` is False, the
      folder is left completely untouched (e.g. a sandboxed app container that
      may hold user data).

    Never follows symlinks and never touches the ``root`` directory itself.
    """
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
        children = sorted(root.iterdir())
    except OSError as exc:
        report.errors.append(f"{display_path(root)}: list failed: {exc}")
        return report

    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not looks_like_bundle_id(child.name):
            report.skipped_unknown += 1
            continue

        if not is_app_installed(child.name):
            if is_symlink(child):
                report.skipped_symlink += 1
                continue
            report.bytes_reclaimable += dir_size_no_follow(child)
            report.items_matched += 1
            report.orphans_removed += 1
            if apply:
                try:
                    shutil.rmtree(child)
                    report.dirs_removed += 1
                except OSError as exc:
                    report.errors.append(f"{display_path(child)}: delete failed: {exc}")
        elif clean_installed_by_age:
            sub = scan_old_files(child, target, cutoff, apply)
            report.bytes_reclaimable += sub.bytes_reclaimable
            report.files_matched += sub.files_matched
            report.items_matched += sub.items_matched
            report.skipped_recent += sub.skipped_recent
            report.skipped_symlink += sub.skipped_symlink
            report.dirs_removed += sub.dirs_removed
            report.errors.extend(sub.errors)
        else:
            report.skipped_kept += 1
    return report


def scan_nested_dirs(root: Path, target: CleanupTarget, apply: bool) -> TargetReport:
    """Remove whole subdirectories by name found anywhere under ``root``.

    Used for nested cache folders that live inside a user-data tree but are
    themselves pure cache (e.g. CodeBuddy extension snapshot screenshots at
    ``Data/*/.../history/*/*/assets``). The directory name to match comes from
    ``target.remove_dirs_named`` (default ``assets``) and the match is further
    constrained to directories that sit beneath an ancestor named ``history``,
    so unrelated ``assets`` folders elsewhere in the tree are never touched.

    The whole matched directory is removed at once; no age threshold applies.
    Never follows symlinks and never removes the ``root`` itself.
    """
    dir_name = target.remove_dirs_named or "assets"
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

    for dirpath, dirnames, _ in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        if current.name != dir_name:
            continue
        if not any(parent.name == "history" for parent in current.parents):
            continue
        report.bytes_reclaimable += dir_size_no_follow(current)
        report.items_matched += 1
        if apply:
            try:
                shutil.rmtree(current)
                report.dirs_removed += 1
                # Remove now-empty ancestor directories left behind by the
                # deleted assets folder, stopping at (and not removing) the
                # `history` ancestor so other sessions are never touched.
                ancestor = current.parent
                while ancestor.name and ancestor.name != "history" and ancestor != root:
                    try:
                        ancestor.rmdir()
                        report.dirs_removed += 1
                    except OSError:
                        break
                    ancestor = ancestor.parent
            except OSError as exc:
                report.errors.append(f"{display_path(current)}: delete failed: {exc}")
        dirnames[:] = []  # do not descend into an (about-to-be) removed dir
    return report


# Top-level entries directly under ~/Library/Application Support that are not
# per-app directories (they are covered by dedicated targets such as
# macos-user-logs) and must be skipped by the generic per-app scan.
_APP_SUPPORT_NON_APP_DIRS = (
    "CrashReporter",
    "DiagnosticReports",
)


# Subfolder names that are regenerable / diagnostics when found directly under
# an app's ~/Library/Application Support/<app> directory. Anything else under
# that tree is treated as user data and never touched by this scan.
APP_SUPPORT_SAFE_SUBDIRS = (
    "Logs",
    "logs",
    "Cache",
    "Caches",
    "CrashReport",
    "CrashReporter",
    "DiagnosticReports",
)


def scan_appsupport(root: Path, target: CleanupTarget, cutoff: float, apply: bool) -> TargetReport:
    """Age-expire Logs/Cache/CrashReport subfolders of every app in root.

    ``root`` is expected to be a single app directory (the glob
    ``~/Library/Application Support/*`` feeds one app directory per call). Only
    the well-known regenerable subfolder names in ``APP_SUPPORT_SAFE_SUBDIRS``
    are scanned, and only files older than ``cutoff`` are removed — so the rest
    of an app's data is left untouched. This is app-aware and safe by
    construction: it never does a blanket ``rm -rf`` of Application Support.

    CodeBuddy apps have dedicated, more thorough targets, so they are skipped
    here to avoid double counting.
    """
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
    if root.name.startswith("CodeBuddy"):
        return report  # dedicated CodeBuddy targets handle these
    if root.name in _APP_SUPPORT_NON_APP_DIRS:
        return report  # covered by dedicated top-level targets, not an app dir

    for sub_name in APP_SUPPORT_SAFE_SUBDIRS:
        child = root / sub_name
        if is_symlink(child):
            report.skipped_symlink += 1
            continue
        sub = scan_old_files(child, target, cutoff, apply)
        report.bytes_reclaimable += sub.bytes_reclaimable
        report.files_matched += sub.files_matched
        report.items_matched += sub.items_matched
        report.skipped_recent += sub.skipped_recent
        report.skipped_symlink += sub.skipped_symlink
        report.dirs_removed += sub.dirs_removed
        report.errors.extend(sub.errors)
    return report
