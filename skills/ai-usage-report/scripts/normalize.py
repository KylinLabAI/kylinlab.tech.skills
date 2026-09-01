# -*- coding: utf-8 -*-
"""
normalize.py — Convert platform-native export files into the normalized CSV
schema used by build_report.py, while KEEPING the originals untouched.

Design
------
  data/<platform>/raw/                  <- default account exports
  data/<platform>/accounts/<acc>/raw/   <- per-account exports
  data/<platform>/[accounts/<acc>/]     <- generated normalized CSVs live here

Each account gets its own raw/ folder so exports from different accounts on the
same platform can never overwrite each other.

Supported exports
  - CodeBuddy: request-usage-YYYY-MM-DD.xlsx
                columns: RequestID, 积分消耗, User Prompt, 模型, 客户端, 时间
  - DeepSeek:  usage_data_YYYY-MM-DD.zip (from the web console)
                contains cost-*.csv (daily model totals) and amount-*.csv (token/request detail).
                We use cost-*.csv for normalized cost-per-day-per-model records.

For platforms without exports (Qoder / TRAE), continue using scrape_usage.py.
"""
import csv
import os
import re
import shutil
import sys
import zipfile
from datetime import date, datetime

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
sys_path_set = False
if HERE not in sys.path:
    sys.path.insert(0, HERE)
    sys_path_set = True

import data_store  # noqa: E402

DATE_FMT = "%Y-%m-%d"


def _raw_dir(platform, account=None):
    d = os.path.join(data_store.platform_data_dir(platform, account), "raw")
    os.makedirs(d, exist_ok=True)
    return d


def has_export_raw(platform, account=None):
    """Return True if this platform account has official export files in raw/."""
    raw_dir = _raw_dir(platform, account)
    if not os.path.isdir(raw_dir):
        return False
    for fn in os.listdir(raw_dir):
        if fn.lower().endswith((".xlsx", ".zip", ".csv")):
            return True
    return False


def _parse_dt(s):
    """Parse common datetime formats; return date part."""
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    # DeepSeek ISO like 2026-07-14T00:00:00+08:00
    m = re.match(r"(\d{4}-\d{2}-\d{2})T", s)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    return None


def normalize_codebuddy(xlsx_path, out_dir, account=None):
    """Convert CodeBuddy export xlsx to normalized CSV."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb.active
    rows = []
    for i, raw in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # header
        if not raw or not raw[0]:
            continue
        rid, cost, prompt, model, client, dt = raw[:6]
        d = _parse_dt(dt)
        if not d:
            continue
        rows.append({
            "date": d.strftime(DATE_FMT),
            "model": str(model or "").strip(),
            "cost": float(cost or 0),
            "free": 1 if float(cost or 0) == 0 else 0,
            "prompt": str(prompt or "").strip(),
            "platform": "codebuddy",
            "account": data_store.safe_account(account),
            "requests": 1,
            # `request_id` (not raw_request_id) is what the store dedups on:
            # without it, two requests with the same day/model/cost collapse
            # into one and the report under-counts.
            "request_id": str(rid or ""),
            "raw_client": str(client or ""),
        })
    if rows:
        dates = sorted({r["date"] for r in rows})
        base = f"{dates[0]}_{dates[-1]}"
    else:
        base = os.path.splitext(os.path.basename(xlsx_path))[0]
    out = os.path.join(out_dir, f"{base}.csv")
    n = _write(rows, out)
    return out, n


def normalize_deepseek(zip_path, out_dir, account=None):
    """Convert DeepSeek export zip to normalized CSV(s)."""
    tmp = os.path.join(out_dir, ".tmp_unzip")
    os.makedirs(tmp, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp)

        cost_files = [f for f in os.listdir(tmp) if f.startswith("cost-") and f.endswith(".csv")]
        written = []
        for cf in cost_files:
            rows = []
            with open(os.path.join(tmp, cf), "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    d = _parse_dt(row.get("start_time_iso", ""))
                    if not d:
                        continue
                    rows.append({
                        "date": d.strftime(DATE_FMT),
                        "model": row.get("model", "").strip(),
                        "cost": float(row.get("cost", 0) or 0),
                        "free": 1 if float(row.get("cost", 0) or 0) == 0 else 0,
                        "prompt": "",
                        "platform": "deepseek",
                        "account": data_store.safe_account(account),
                        "requests": 1,
                        "raw_wallet_type": row.get("wallet_type", ""),
                        "raw_currency": row.get("currency", ""),
                        "raw_end_time_iso": row.get("end_time_iso", ""),
                    })
            if rows:
                dates = sorted({r["date"] for r in rows})
                out_name = f"{dates[0]}_{dates[-1]}.csv"
            else:
                out_name = cf
            out = os.path.join(out_dir, out_name)
            n = _write(rows, out)
            written.append((out, n))
        return written
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _migrate_row(r):
    """Backfill fields that older normalized CSVs stored under other names.

    Exports used to write `raw_request_id`; the store dedups on `request_id`,
    so old rows had an empty identity id and collapsed against each other.
    """
    if not str(r.get("request_id") or "") and str(r.get("raw_request_id") or ""):
        r["request_id"] = str(r.get("raw_request_id"))
    if r.get("account") is None:
        r["account"] = ""
    return r


def _dedup_rows(rows):
    """Collapse rows that share a store identity, keeping the best copy."""
    best, order = {}, []
    for r in rows:
        key = data_store._dedup_key(r)
        if key in best:
            if not data_store._more_complete(r, best[key]):
                continue
        else:
            order.append(key)
        best[key] = r
    return [best[k] for k in order]


def _write(rows, path):
    """Write normalized rows, MERGING with whatever is already in `path`.

    Overwriting would silently drop data: two exports that cover the same date
    window (e.g. two accounts, or a re-export) map to the same file name.
    """
    if not rows:
        return
    existing = []
    if os.path.exists(path):
        existing = [_migrate_row(r) for r in data_store._read_rows(path)]
    merged = _dedup_rows([_migrate_row(r) for r in rows] + existing)
    merged.sort(key=lambda r: (r.get("date", ""), str(r.get("model", ""))))
    fieldnames = list(data_store.FIELDS) + sorted(
        {k for r in merged for k in r if k not in data_store.FIELDS}
    )
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(merged)
    return len(merged)


def normalize_all(platform=None, account=None):
    """Scan raw/ folders (default account + every named account) and
    regenerate normalized CSVs."""
    results = []
    targets = [platform] if platform else ["codebuddy", "deepseek"]
    for p in targets:
        accounts = [account] if account else [None] + data_store.list_account_dirs(p)
        for acc in accounts:
            results.extend(_normalize_account(p, acc))
    return results


def _normalize_account(platform, account):
    """Normalize every export file in one account's raw/ folder."""
    results = []
    raw = _raw_dir(platform, account)
    out_dir = data_store.platform_data_dir(platform, account)
    if not os.path.isdir(raw):
        return results
    label = platform if not account else f"{platform}/{account}"
    for fn in sorted(os.listdir(raw)):
        src = os.path.join(raw, fn)
        if platform == "codebuddy" and fn.lower().endswith(".xlsx"):
            out, n = normalize_codebuddy(src, out_dir, account)
            results.append((label, fn, out, n))
        elif platform == "deepseek" and fn.lower().endswith(".zip"):
            for out, n in normalize_deepseek(src, out_dir, account):
                results.append((label, fn, out, n))
    return results


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Normalize exported platform usage files.")
    ap.add_argument("--platform", choices=["codebuddy", "deepseek"],
                    help="Only normalize one platform")
    ap.add_argument("--account", default=None,
                    help="Only normalize this account (default: every account)")
    args = ap.parse_args()
    results = normalize_all(args.platform, args.account)
    if not results:
        print("[normalize] no raw export files found in "
              "data/<platform>/raw/ (nor in data/<platform>/accounts/<acc>/raw/)")
        return
    for p, src, out, n in results:
        print(f"[normalize] {p}: {src} -> {out} ({n} rows)")


if __name__ == "__main__":
    main()
