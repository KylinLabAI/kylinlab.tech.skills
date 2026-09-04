# -*- coding: utf-8 -*-
"""
build_report.py — Build an analysis report from cached usage data.

Reads all captured CSVs for a platform from data/<platform>/<account>/
(managed by data_store.py), merges them, and runs the full analysis pipeline
(analyze_usage.analyze) to produce a report under
report/<run_id>/<platform>/  (one folder per generation; run_id defaults to a timestamp).

If a date range is requested and some days are missing, it can auto-trigger
scrape_usage.py to fill the gaps first (incremental fetch).

Multi-account: a platform can hold several accounts, each with its own folder
(data/<platform>/<account>/). Pick one with `--account <name>` (report at
report/<start>_<end>/<platform>/<account>/), or pass `--account all` to
aggregate every account into a single vendor report
(report/<run_id>/<platform>/report.md).

Usage:
    python3 build_report.py --platform qoder [--start 2026-08-01] [--end 2026-08-15]
    python3 build_report.py --platform codebuddy --all        # whole cache
    python3 build_report.py --platform deepseek --auto-fetch   # fill gaps then report
    python3 build_report.py --platform codebuddy --account work
    python3 build_report.py --platform codebuddy --account all
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
verify = _import_local("verify_data")
normalize = _import_local("normalize")


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
            r["free"] = data_store.as_bool(r.get("free"))
        except (ValueError, TypeError):
            r["free"] = (r["cost"] == 0.0)
        try:
            r["requests"] = int(float(r.get("requests") or 0))
        except (ValueError, TypeError):
            r["requests"] = 0
        out.append(r)
    return out


ALL_ACCOUNTS = "all"


def _load_consolidated_rows(platform, req_start, req_end, account=None):
    """Return merged, deduped, type-coerced record dicts from the data store."""
    return _coerce(data_store.load_consolidated(platform, req_start, req_end,
                                                account=account))


def _load_all_accounts(platform, req_start, req_end):
    """Rows from every account, each tagged with its account name."""
    rows = []
    for acc in data_store.list_accounts(platform):
        rows.extend(_load_consolidated_rows(platform, req_start, req_end, acc))
    return rows


def _auto_fetch(platform, req_start, req_end, no_backfill=False, account=None):
    """Fill missing gaps for one account before building the report.

    - Refresh the persisted covered_range meta from real data (so the next
      coverage check is O(1)).
    - External-import accounts (account.json `source == 'import'`) can NOT be
      pulled from the platform: we never scrape them; instead we report the
      missing range and remind the user to import the external export.
    - Otherwise we trigger scrape_usage.py for the missing gaps. By default the
      previous pull's final day is force re-fetched (backfilled) because it may
      have been captured mid-day and is only partially complete.
    """
    label = platform if not account else f"{platform}/{account}"
    # Keep the coverage meta fresh for every build (covers the read-only case).
    data_store.covered_range(platform, account, persist=True)

    if data_store.is_imported(platform, account):
        gaps = data_store.missing_ranges(req_start, req_end, platform,
                                         account=account)
        if gaps:
            g0, g1 = gaps[0][0], gaps[-1][1]
            print(f"[build] {label}: 外部导入账号，无法从平台拉取。缺失区间 "
                  f"{g0}~{g1}（{len(gaps)} 段）。")
            print(f"        请获取该账号的导出文件并导入：")
            print(f"        python3 import_data.py --platform {platform} "
                  f"--account {account} --file <导出文件>")
        else:
            print(f"[build] {label}: 外部导入账号，范围内数据齐全，跳过拉取。")
        return

    force = set()
    if not no_backfill:
        prev_last = data_store.last_covered_date(platform, account)
        if prev_last is not None:
            force.add(prev_last)
    gaps = data_store.missing_ranges(req_start, req_end, platform,
                                     account=account, force_days=force)
    if not gaps:
        print(f"[build] {label}: range {req_start}~{req_end} already cached, skip fetch.")
        return
    print(f"[build] {label}: missing gaps {gaps}; fetching via scraper...")
    g0, g1 = gaps[0][0], gaps[-1][1]
    url = _platform_url(platform)
    if not url:
        print(f"[build] no URL configured for {platform}; skipping auto-fetch.")
        return
    cmd = [
        sys.executable, os.path.join(HERE, "scrape_usage.py"),
        "--platform", platform, "--url", url,
        "--start", g0.strftime("%Y-%m-%d"),
        "--end", g1.strftime("%Y-%m-%d"),
    ]
    if account:
        cmd += ["--account", account]
    subprocess.run(cmd, check=True)

    # Re-check coverage after the fetch. If a gap is still open, the platform
    # likely returned out-of-range (ignored the date range) or empty data. Do
    # NOT pretend the gap was filled — warn so the report's missing-data caveat
    # stays honest instead of silently covering a hole.
    still = data_store.missing_ranges(req_start, req_end, platform,
                                      account=account)
    if still:
        print(f"[build] ⚠ {label}: auto-fetch ran but {len(still)} gap(s) still "
              f"open (e.g. {still[0][0]}~{still[-1][1]}). The platform may have "
              f"returned out-of-range/empty data; the report will flag this as "
              f"missing, not silently cover it.")


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
                    help="(default on) explicitly enable fetching missing gaps")
    ap.add_argument("--no-fetch", dest="no_fetch", action="store_true",
                    help="disable auto-fetch; build the report from the existing "
                         "cache only (never scrape the platform)")
    ap.add_argument("--force", action="store_true",
                    help="skip the integrity-verify gate (use with caution)")
    ap.add_argument("--no-backfill", action="store_true",
                    help="do not force re-fetch of the previous pull's final day "
                         "(set only if you are certain that day is complete)")
    ap.add_argument("--account", default=None,
                    help="account to report on; use 'all' to aggregate every "
                         "account of this platform")
    ap.add_argument("--out", default=None,
                    help="report folder name (run id); default: a generation "
                         "timestamp YYYY-MM-DD_HH-MM-SS. Use the same value as "
                         "cross_platform_report.py so the summary links resolve.")
    args = ap.parse_args()
    do_fetch = args.auto_fetch or (not args.no_fetch)

    platform = args.platform
    all_accounts = str(args.account or "").lower() == ALL_ACCOUNTS
    account = None if all_accounts else args.account

    files = data_store.list_data_files(platform, account)
    if all_accounts:
        files = files or [f for acc in data_store.list_accounts(platform)
                          for f in data_store.list_data_files(platform, acc)]
    if not files:
        print(f"[build] no cached data for {platform}.")
        if not do_fetch:
            print(f"        (auto-fetch disabled; run scrape_usage.py or "
                  f"import_data.py first.)")
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

    if do_fetch and req_start and req_end:
        accounts = data_store.list_accounts(platform) if all_accounts else [account]
        for acc in accounts:
            _auto_fetch(platform, req_start, req_end,
                        no_backfill=args.no_backfill, account=acc)

    # If the platform has exported raw files, re-normalize them first so the
    # report is always based on the latest official export.
    if all_accounts:
        print("[build] normalizing exports for every account...")
        normalize.normalize_all(platform)
    elif normalize.has_export_raw(platform, account):
        print("[build] detected official export files; normalizing first...")
        normalize.normalize_all(platform, account)

    if all_accounts:
        rows = _load_all_accounts(platform, req_start, req_end)
    else:
        rows = _load_consolidated_rows(platform, req_start, req_end, account)
    if not rows:
        print("[build] no rows after merge; nothing to report.")
        return

    # Integrity gate: refuse to publish a report on obviously incomplete data.
    if all_accounts:
        errors, warnings, _ = verify.verify_all_accounts(platform, req_start, req_end)
    else:
        errors, warnings, _ = verify.verify(platform, req_start, req_end, account)
    if errors:
        print("\n[build] ❌ 数据校验未通过，已中止生成报告，避免产出错误结论。")
        print("        请先用 scrape_usage.py 补齐缺失范围，再重新 build。")
        print("        如确需基于现有数据出报告，可加 --force 跳过校验。\n")
        if not getattr(args, "force", False):
            sys.exit(2)
    elif warnings:
        print("[build] ⚠ 校验有警告，仍会生成报告（请人工确认）。\n")

    # Cost is unified to RMB at analysis time (configs/units.json converts each
    # platform's native unit), so the report always shows comparable ¥.
    unit = "元(RMB)"
    label = platform if not account else (
        f"{platform} (all accounts)" if all_accounts else f"{platform}/{account}")
    print(f"[build] 平台 {label} 费用已折算为 RMB（元）；"
          f"跨平台可直接相加。")

    # Build the report under report/<run_id>/<platform>[/<account>].
    # run_id defaults to a generation timestamp; pass --out to fix the name so
    # the summary (cross_platform_report.py, same --out) links to this file.
    if all_accounts:
        out_dir = data_store.platform_report_dir(platform, None, run_id=args.out)
    elif account:
        out_dir = data_store.platform_report_dir(platform, account, run_id=args.out)
    else:
        out_dir = data_store.platform_report_dir(platform, None, run_id=args.out)
    summary = analyze.analyze(rows, platform, out_dir, unit=unit)
    print(f"[build] platform={label} range={req_start}~{req_end}")
    print(f"        records={summary['total']} cost={summary['total_cost']}")
    print(f"        report  : {os.path.join(out_dir, 'report.md')}")

    # Help discover multi-account data instead of silently reporting one store.
    if not args.account:
        named = [a for a in data_store.list_accounts(platform) if a]
        if named:
            print(f"[build] 该平台还有账号：{', '.join(named)}；"
                  f"单独出报告用 --account <name>，汇总用 --account all。")


if __name__ == "__main__":
    main()
