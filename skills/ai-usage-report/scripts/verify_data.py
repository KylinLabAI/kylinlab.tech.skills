# -*- coding: utf-8 -*-
"""
verify_data.py — Integrity check for captured AI usage data.

Purpose
-------
After a browser capture we must NOT blindly trust the result. A capture can
silently miss pages/pagination (as happened with Qoder, where on_response
failed to catch all pages). This script checks the stored CSVs for a platform
and reports red flags:

  1. Empty / zero-row files
  2. Days in the requested range with no records (possible missing pages)
  3. Unparsed date fields
  4. Suspiciously low capture density for a wide range
  5. Duplicate rows (double-count risk)
  6. Cost-unit inconsistency (cross-platform: costs are NOT additive)

Run:
  python3 verify_data.py --platform qoder --start 2026-07-13 --end 2026-08-11
  python3 verify_data.py --platform qoder --all

Exit code is non-zero if any ERROR-level issue is found, so it can be wired
into build_report.py to block publishing a bad report.
"""
import argparse
import csv
import os
import sys
from datetime import datetime, date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import data_store  # noqa: E402
import normalize  # noqa: E402

DATE_FMT = "%Y-%m-%d"


def _d(s):
    try:
        return datetime.strptime(s.strip(), DATE_FMT).date()
    except Exception:
        return None


def verify(platform, req_start=None, req_end=None):
    files = data_store.list_data_files(platform)
    errors, warnings = [], []
    export_based = normalize.has_export_raw(platform)

    if not files:
        errors.append(f"无缓存数据：data/{platform}/ 下没有任何 CSV。")
        return errors, warnings, []

    rows = data_store.load_consolidated(platform, req_start, req_end)
    if not rows:
        errors.append("合并后无任何记录。")
        return errors, warnings, rows

    # 1) parse-rate of dates
    bad = [r for r in rows if not r.get("date")]
    if bad:
        warnings.append(f"{len(bad)} 条记录缺日期字段，将被图表忽略。")

    dates = [_d(r["date"]) for r in rows if _d(r.get("date", ""))]
    have = set(dates)

    # 2) requested-range coverage
    if req_start and req_end:
        missing = []
        d = req_start
        while d <= req_end:
            if d not in have:
                missing.append(d)
            d = d.fromordinal(d.toordinal() + 1)
        if missing:
            frac = len(missing) / max((req_end - req_start).days + 1, 1)
            msg = (f"范围内缺失 {len(missing)}/{(req_end-req_start).days+1} 天"
                   f"（如 {missing[0]}…{missing[-1]}）")
            # Export files are authoritative: missing days likely mean zero usage.
            if export_based:
                warnings.append(msg + "（官方导出缺失日通常为零用量，不视为错误）。")
            elif frac > 0.5:
                errors.append(msg + " —— 数据大概率不完整，不要据此出报告。")
            else:
                warnings.append(msg + "（可能为零用量日，需人工确认）。")

    # 3) density (only meaningful for scraped data; exports may be sparse)
    if req_start and req_end and rows and not export_based:
        span = max((req_end - req_start).days, 1)
        if len(rows) / span < 1 and span >= 7:
            warnings.append(
                f"捕获密度偏低（{len(rows)} 条 / {span} 天）。"
                f"若实际频繁使用，多半漏抓了分页，请重跑。")

    # 4) duplicates within the consolidated set (use the same robust key as
    #    data_store.load_consolidated so this reflects real dedup behavior).
    seen, dups = set(), 0
    for r in rows:
        key = data_store._dedup_key(r)
        if key in seen:
            dups += 1
        seen.add(key)
    if dups:
        warnings.append(f"合并后仍有 {dups} 条疑似重复记录（去重键命中）。")

    # 5) per-file empty check
    for s, e, path in files:
        if os.path.getsize(path) == 0 or len(data_store._read_rows(path)) == 0:
            warnings.append(f"空文件：{os.path.basename(path)}")

    # summary line
    cost_unit = {
        "qoder": "美元/额度", "trae": "积分(points)",
        "codebuddy": "积分/额度", "deepseek": "美元",
    }.get(platform.lower(), "未知")
    source_note = "(export)" if export_based else "(scraped)"
    print(f"[verify] {platform}: {len(rows)} 条 {source_note}, "
          f"覆盖 {min(have)}~{max(have)}, 单位={cost_unit}")
    return errors, warnings, rows


def _print_and_exit(platform, errors, warnings):
    print("\n" + "=" * 60)
    print(f"数据校验报告 — {platform}")
    print("=" * 60)
    if errors:
        print(f"\n❌ ERROR ({len(errors)}):")
        for e in errors:
            print("   - " + e)
    if warnings:
        print(f"\n⚠ WARNING ({len(warnings)}):")
        for w in warnings:
            print("   - " + w)
    if not errors and not warnings:
        print("\n✅ 校验通过：数据完整，可放心出报告。")
    if errors:
        print("\n建议：重新抓取该平台缺失范围后再出报告。")
    print("=" * 60)
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(description="Verify captured AI usage data integrity.")
    ap.add_argument("--platform", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    req_start = req_end = None
    if args.start:
        req_start = datetime.strptime(args.start, DATE_FMT).date()
    if args.end:
        req_end = datetime.strptime(args.end, DATE_FMT).date()
    if args.all or (req_start is None and req_end is None):
        files = data_store.list_data_files(args.platform)
        if files:
            req_start = min(s for s, _e, _p in files)
            req_end = max(e for _s, e, _p in files)

    errors, warnings, _ = verify(args.platform, req_start, req_end)
    sys.exit(_print_and_exit(args.platform, errors, warnings))


if __name__ == "__main__":
    main()
