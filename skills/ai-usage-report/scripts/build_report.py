# -*- coding: utf-8 -*-
"""
build_report.py — Build an analysis report from cached usage data.

Reads all captured CSVs for a platform from data/<platform>/ (managed by
data_store.py), merges them, and runs the full analysis pipeline
(analyze_usage.analyze) to produce a report in report/<platform>.

If a date range is requested and some days are missing, it can auto-trigger
scrape_usage.py to fill the gaps first (incremental fetch).

Usage:
    python3 build_report.py --platform qoder [--start 2026-08-01] [--end 2026-08-15]
    python3 build_report.py --platform codebuddy --all        # whole cache
    python3 build_report.py --platform deepseek --auto-fetch   # fill gaps then report
"""
import argparse
import importlib.util
import os
import subprocess
import sys
from datetime import datetime, date

HERE = os.path.dirname(os.path.abspath(__file__))


def _import_local(name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(HERE, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


data_store = _import_local("data_store")
analyze = _import_local("analyze_usage")


def _coerce(rows):
    """Coerce raw CSV string fields into the numeric types analyze() expects."""
    out = []
    for r in rows:
        r = dict(r)
        try:
            r["cost"] = float(r.get("cost") or 0)
        except (ValueError, TypeError):
            r["cost"] = 0.0
        try:
            r["free"] = bool(int(float(r.get("free") or 0)))
        except (ValueError, TypeError):
            r["free"] = (r["cost"] == 0.0)
        try:
            r["requests"] = int(float(r.get("requests") or 0))
        except (ValueError, TypeError):
            r["requests"] = 0
        out.append(r)
    return out


def _load_consolidated_rows(platform, req_start, req_end):
    """Return merged, deduped, type-coerced record dicts from the data store."""
    return _coerce(data_store.load_consolidated(platform, req_start, req_end))


def _auto_fetch(platform, req_start, req_end):
    """Trigger scrape_usage.py for missing gaps only."""
    gaps = data_store.missing_ranges(req_start, req_end, platform)
    if not gaps:
        print(f"[build] range {req_start}~{req_end} already cached, skip fetch.")
        return
    print(f"[build] missing gaps: {gaps}; fetching via scraper...")
    g0, g1 = gaps[0][0], gaps[-1][1]
    url = _platform_url(platform)
    if not url:
        print(f"[build] no URL configured for {platform}; skipping auto-fetch.")
        return
    subprocess.run([
        sys.executable, os.path.join(HERE, "scrape_usage.py"),
        "--platform", platform, "--url", url,
        "--start", g0.strftime("%Y-%m-%d"),
        "--end", g1.strftime("%Y-%m-%d"),
    ], check=True)


def _platform_url(platform):
    cfg = os.path.join(HERE, "..", "configs", "urls.json")
    try:
        import json
        with open(cfg, encoding="utf-8") as f:
            return json.load(f).get(platform.lower())
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Build report from cached usage data.")
    ap.add_argument("--platform", required=True)
    ap.add_argument("--start", default=None, help="yyyy-mm-dd; default: earliest cached")
    ap.add_argument("--end", default=None, help="yyyy-mm-dd; default: latest cached")
    ap.add_argument("--all", action="store_true", help="use the full cached range")
    ap.add_argument("--auto-fetch", action="store_true",
                    help="fetch missing date gaps before building")
    args = ap.parse_args()

    files = data_store.list_data_files(args.platform)
    if not files:
        print(f"[build] no cached data for {args.platform}. "
              f"Run scrape_usage.py first or use --auto-fetch.")
        if not args.auto_fetch:
            return
        # nothing cached: need a range to fetch
        if not (args.start and args.end):
            args.end = date.today().strftime("%Y-%m-%d")
            args.start = (date.today().replace(day=1)).strftime("%Y-%m-%d")

    req_start = req_end = None
    if args.start:
        req_start = datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end:
        req_end = datetime.strptime(args.end, "%Y-%m-%d").date()

    if args.all or (req_start is None and req_end is None):
        # use the full cached span
        if files:
            req_start = min(s for s, _e, _p in files)
            req_end = max(e for _s, e, _p in files)

    if args.auto_fetch and req_start and req_end:
        _auto_fetch(args.platform, req_start, req_end)

    rows = _load_consolidated_rows(args.platform, req_start, req_end)
    if not rows:
        print("[build] no rows after merge; nothing to report.")
        return

    # build the report under report/<platform>/<start>_<end>
    s = req_start or min(datetime.strptime(r["date"], "%Y-%m-%d").date()
                         for r in rows if r.get("date"))
    e = req_end or max(datetime.strptime(r["date"], "%Y-%m-%d").date()
                       for r in rows if r.get("date"))
    out_dir = os.path.join(data_store.platform_report_dir(args.platform),
                           f"{s.strftime('%Y-%m-%d')}_{e.strftime('%Y-%m-%d')}")
    summary = analyze.analyze(rows, args.platform, out_dir)
    print(f"[build] platform={args.platform} range={s}~{e}")
    print(f"        records={summary['total']} cost={summary['total_cost']}")
    print(f"        report  : {os.path.join(out_dir, 'report.html')}")


if __name__ == "__main__":
    main()
