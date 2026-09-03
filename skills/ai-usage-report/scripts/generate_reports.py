# -*- coding: utf-8 -*-
"""Generate a full cross-platform report set into ONE timestamped folder.

For every platform it builds the per-vendor Markdown report, then the combined
Markdown summary, all under ``report/<run_id>/`` (run_id = a generation
timestamp by default) so the summary's per-vendor links resolve locally.

This is the recommended entry point; it replaces running build_report.py and
cross_platform_report.py by hand (which would otherwise create separate folders
and break the links between them).

Usage:
  python3 generate_reports.py                       # full cached span, timestamp folder
  python3 generate_reports.py --start 2026-08-01 --end 2026-09-30
  python3 generate_reports.py --out 2026-09-03_20-02-34   # fixed folder name
"""
import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import data_store  # noqa: E402

PLATS = ["qoder", "trae", "codebuddy", "deepseek"]


def _global_span():
    """Union of every platform/account's cached date span, or None."""
    spans = []
    for p in PLATS:
        for acc in [None] + data_store.list_accounts(p):
            spans += [(s, e) for s, e, _ in data_store.list_data_files(p, acc)]
    if not spans:
        return None, None
    return min(s for s, _ in spans), max(e for _, e in spans)


def main():
    ap = argparse.ArgumentParser(description="Generate a full cross-platform report set.")
    ap.add_argument("--start", default=None, help="yyyy-mm-dd (default: earliest cached)")
    ap.add_argument("--end", default=None, help="yyyy-mm-dd (default: latest cached)")
    ap.add_argument("--out", default=None,
                    help="report folder name (run id); default: a generation "
                         "timestamp YYYY-MM-DD_HH-MM-SS")
    ap.add_argument("--force", action="store_true",
                    help="pass --force to per-vendor builds so a verify ❌ does "
                         "not abort that vendor's report")
    args = ap.parse_args()

    run_id = args.out or datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = data_store.report_run_dir(run_id)

    # Default the data window to the full cached span so the summary and every
    # per-vendor report cover the exact same range.
    start, end = args.start, args.end
    if not (start and end):
        gstart, gend = _global_span()
        if gstart and gend:
            start = start or gstart.strftime("%Y-%m-%d")
            end = end or gend.strftime("%Y-%m-%d")

    range_args = []
    if start:
        range_args += ["--start", start]
    if end:
        range_args += ["--end", end]

    # 1) per-vendor reports
    for p in PLATS:
        cmd = [sys.executable, os.path.join(HERE, "build_report.py"),
               "--platform", p, "--account", "all",
               "--out", run_id] + range_args
        if args.force:
            cmd.append("--force")
        rc = subprocess.run(cmd).returncode
        if rc != 0:
            print(f"[gen] ⚠ {p} build failed (rc={rc}); summary still includes it.")

    # 2) combined summary (same run_id -> links resolve)
    scmd = [sys.executable, os.path.join(HERE, "cross_platform_report.py"),
            "--out", run_id] + range_args
    subprocess.run(scmd, check=True)

    print(f"\n[gen] full report set written to:\n      {run_dir}")
    print(f"[gen] open: {os.path.join(run_dir, 'summary', 'report.md')}")


if __name__ == "__main__":
    main()
