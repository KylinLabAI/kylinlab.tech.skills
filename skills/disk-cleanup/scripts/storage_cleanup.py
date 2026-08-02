#!/usr/bin/env python3
"""Dry-run first cleanup helper for macOS, Windows, and Linux.

Thin entry point. Platform-specific cleanup targets live in
`macos_targets.py`, `windows_targets.py`, and `linux_targets.py`. Shared
scanning and reporting logic lives in `cleanup_common.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict

from cleanup_common import (
    CleanupReport,
    MAX_LISTED_TARGET_PATHS,
    CleanupTarget,
    detect_platform,
    display_path,
    human_size,
    resolve_pattern,
    scan_old_children,
    scan_old_files,
)


def load_targets(target_platform: str) -> tuple[CleanupTarget, ...]:
    """Return the cleanup targets defined for the given platform."""
    if target_platform == "macos":
        from macos_targets import TARGETS
    elif target_platform == "windows":
        from windows_targets import TARGETS
    elif target_platform == "linux":
        from linux_targets import TARGETS
    else:
        raise SystemExit(f"Unsupported platform: {target_platform}")
    return TARGETS


def active_profiles(args: argparse.Namespace) -> set[str]:
    profiles = {"safe"}
    if args.include_developer:
        profiles.add("developer")
    if args.include_package_caches:
        profiles.add("package-caches")
    if args.include_trash:
        profiles.add("trash")
    return profiles


def run(args: argparse.Namespace) -> CleanupReport:
    target_platform = detect_platform(args.platform)
    profiles = active_profiles(args)
    cutoff = time.time() - (args.min_age_days * 24 * 60 * 60)
    targets = load_targets(target_platform)
    reports: list = []
    seen_roots: set[tuple[str, str]] = set()

    for target in targets:
        if target.platform != target_platform or target.profile not in profiles:
            continue
        for pattern in target.patterns:
            for root in resolve_pattern(pattern, target_platform):
                key = (target.key, str(root))
                if key in seen_roots:
                    continue
                seen_roots.add(key)
                if target.mode == "old-children":
                    reports.append(scan_old_children(root, target, cutoff, args.apply))
                else:
                    reports.append(scan_old_files(root, target, cutoff, args.apply))

    return CleanupReport(
        platform=target_platform,
        dry_run=not args.apply,
        min_age_days=args.min_age_days,
        active_profiles=sorted(profiles),
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        total_bytes_reclaimable=sum(item.bytes_reclaimable for item in reports),
        total_files_matched=sum(item.files_matched for item in reports),
        total_items_matched=sum(item.items_matched for item in reports),
        targets=reports,
    )


def print_target_list(target_platform: str, profiles: set[str]) -> None:
    print(f"Platform: {target_platform}")
    print("Active profiles: " + ", ".join(sorted(profiles)))
    for target in load_targets(target_platform):
        if target.platform != target_platform or target.profile not in profiles:
            continue
        print(f"- {target.key} [{target.profile}] {target.description}")
        for pattern in target.patterns:
            resolved = [display_path(path) for path in resolve_pattern(pattern, target_platform)]
            if resolved:
                for path in resolved[:MAX_LISTED_TARGET_PATHS]:
                    print(f"  - {path}")
                remaining = len(resolved) - MAX_LISTED_TARGET_PATHS
                if remaining > 0:
                    print(f"  - ... {remaining} more path(s) matched by {pattern}")
            else:
                print(f"  - {pattern} (not found or environment variable not set)")


def print_report(report: CleanupReport) -> None:
    action = "DRY RUN" if report.dry_run else "APPLIED"
    print(f"{action}: platform={report.platform}, min_age_days={report.min_age_days}")
    print(
        "Matched "
        f"{human_size(report.total_bytes_reclaimable)} across "
        f"{report.total_files_matched} file(s) and {report.total_items_matched} item(s)."
    )
    for item in report.targets:
        status = "exists" if item.exists else "missing"
        print(
            f"- {item.key}: {human_size(item.bytes_reclaimable)}, "
            f"files={item.files_matched}, items={item.items_matched}, "
            f"recent_skipped={item.skipped_recent}, symlink_skipped={item.skipped_symlink}, "
            f"root={item.root} ({status})"
        )
        for error in item.errors[:8]:
            print(f"  error: {error}")
        if len(item.errors) > 8:
            print(f"  error: ... {len(item.errors) - 8} more")
    if report.dry_run:
        print("No files were deleted. Rerun with --apply after reviewing the targets.")
    else:
        print("Deletion attempted for matched files/items. Review errors for skipped paths.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("auto", "macos", "windows", "linux"), default="auto")
    parser.add_argument("--min-age-days", type=float, default=7.0)
    parser.add_argument("--include-developer", action="store_true")
    parser.add_argument("--include-package-caches", action="store_true")
    parser.add_argument("--include-trash", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Delete matched files/items.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument("--list-targets", action="store_true", help="List active cleanup targets and exit.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.min_age_days < 0:
        print("--min-age-days must be >= 0", file=sys.stderr)
        return 2
    target_platform = detect_platform(args.platform)
    profiles = active_profiles(args)
    if args.list_targets:
        print_target_list(target_platform, profiles)
        return 0
    report = run(args)
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
