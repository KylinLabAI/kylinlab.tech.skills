# -*- coding: utf-8 -*-
"""
import_data.py — Merge an exported usage file into the data store.

CodeBuddy / DeepSeek let you export usage (xlsx / csv / zip) from the web
portal. This command normalizes that export and merges it into the SAME
data folder the browser capture (scrape_usage.py) writes to, so the report
is always built from one consistent source regardless of origin:

    capture (browser)  ─┐
                        ├─► data/<platform>/<account>/  ─► build_report.py
    export (import)     ─┘

Usage:
  # DeepSeek official export is a .zip of cost-*.csv + amount-*.csv
  python3 import_data.py --platform deepseek --account deepseek-kylinlab \
      --file ~/Desktop/ai-account-export/deepseek-kylinlab/usage_data_*.zip

  # CodeBuddy export is an .xlsx ("Usage Details" sheet)
  python3 import_data.py --platform codebuddy --account codebuddy-kylinlab \
      --file ~/Desktop/ai-account-export/codebuddy-kylinlab/request-usage-*.xlsx

  # Or import every file in a folder
  python3 import_data.py --platform codebuddy --account codebuddy-zq \
      --dir ~/Desktop/ai-account-export/codebuddy-zq
"""
import argparse
import csv
import io
import os
import re
import sys
import zipfile
from datetime import datetime, date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data_store  # persistent store root + helpers

PLATFORM_NAMES = {
    "deepseek": "DeepSeek",
    "codebuddy": "CodeBuddy",
    "qoder": "Qoder",
    "trae": "TRAE",
}

_DATE_RE = re.compile(r"(\d{4})[-/](\d{2})[-/](\d{2})")


def _to_date(s):
    """Extract yyyy-mm-dd from a variety of date/datetime strings."""
    if not s:
        return ""
    s = str(s).strip()
    m = _DATE_RE.search(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def _num(v):
    """Parse a numeric cost/points value, tolerating thousands separators."""
    if v is None:
        return 0.0
    s = str(v).strip().replace(",", "").replace("¥", "").replace("$", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def _norm_deepseek_zip(zippath):
    """DeepSeek export = zip with cost-*.csv (daily×model cost) + amount-*.csv
    (token buckets). We build one normalized row per (date, model) from the
    cost file; the amount file is token-level detail not needed here."""
    rows = []
    with zipfile.ZipFile(zippath) as z:
        cost_names = [n for n in z.namelist()
                      if re.search(r"cost.*\.csv$", n, re.I)]
        if not cost_names:
            print(f"[import] no cost-*.csv found in {zippath}")
            return rows
        with z.open(cost_names[0]) as f:
            text = f.read().decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for r in reader:
            d = _to_date(r.get("start_time_iso") or r.get("date") or "")
            if not d:
                continue
            cost = _num(r.get("cost"))
            wallet = (r.get("wallet_type") or "").lower()
            rows.append({
                "date": d,
                "model": (r.get("model") or "unknown").strip(),
                "cost": cost,
                "free": wallet == "free",
                "prompt": "",
                "platform": "DeepSeek",
                "account": "",
                "requests": 0,
                "request_id": "",
            })
    print(f"[import] deepseek zip: {len(rows)} daily×model cost rows")
    return rows


def _norm_codebuddy_xlsx(path):
    """CodeBuddy export = xlsx with a 'Usage Details' sheet:
    RequestID, 积分消耗, User Prompt, 模型, 客户端, 时间  (one row per request)."""
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl required for .xlsx import: pip install openpyxl")
    rows = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    # Find the header row by normalizing cell text.
    records = list(ws.iter_rows(values_only=True))
    if not records:
        return rows
    header = [str(c).strip() if c is not None else "" for c in records[0]]
    idx = {name: i for i, name in enumerate(header)}
    # Flexible column lookup (handles CN + EN headers).
    def col(*names):
        for n in names:
            if n in idx:
                return idx[n]
        return None
    i_rid = col("RequestID", "request_id", "请求ID")
    i_cost = col("积分消耗", "cost", "points", "费用")
    i_prompt = col("User Prompt", "prompt", "用户提示")
    i_model = col("模型", "model")
    i_client = col("客户端", "client")
    i_time = col("时间", "time", "date")
    for rec in records[1:]:
        if rec is None:
            continue
        rec = list(rec)
        tval = rec[i_time] if i_time is not None else None
        d = _to_date(tval)
        if not d:
            continue
        cost = _num(rec[i_cost]) if i_cost is not None else 0.0
        prompt = ""
        if i_prompt is not None and rec[i_prompt] is not None:
            prompt = str(rec[i_prompt]).strip()
        client = ""
        if i_client is not None and rec[i_client] is not None:
            client = str(rec[i_client]).strip()
        model = (rec[i_model] if i_model is not None else "unknown")
        model = (model or "unknown").strip()
        rid = (str(rec[i_rid]).strip() if i_rid is not None and rec[i_rid]
               else "")
        rows.append({
            "date": d,
            "model": model,
            "cost": cost,
            "free": cost == 0.0,
            "prompt": prompt,
            "platform": "CodeBuddy",
            "account": "",
            "requests": 1,
            "request_id": rid,
            # client kept off the normalized schema; surfaced via request_id tag
            "_client": client,
        })
    print(f"[import] codebuddy xlsx: {len(rows)} request rows")
    return rows


def _norm_generic_csv(path, platform):
    """Fallback CSV parser: maps common CN/EN column names heuristically."""
    pname = PLATFORM_NAMES.get(platform.lower(), platform.capitalize())
    rows = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        header = [str(c).strip().lower() if c is not None else "" for c in
                  (reader.fieldnames or [])]
        idx = {name: i for i, name in enumerate(header)}

        def col(*names):
            for n in names:
                if n in idx:
                    return idx[n]
            return None
        i_date = col("date", "时间", "time", "start_time_iso", "day")
        i_model = col("model", "模型")
        i_cost = col("cost", "费用", "积分消耗", "points", "amount", "fee")
        i_prompt = col("prompt", "user prompt", "标题", "title")
        i_rid = col("request_id", "requestid", "id")
        i_free = col("free", "is_free", "wallet_type")
        for r in reader:
            vals = list(r.values())
            d = _to_date(vals[i_date]) if i_date is not None else ""
            if not d:
                continue
            cost = _num(vals[i_cost]) if i_cost is not None else 0.0
            free = False
            if i_free is not None:
                fv = str(vals[i_free]).strip().lower()
                free = fv in ("free", "true", "1", "yes")
            rows.append({
                "date": d,
                "model": (vals[i_model] if i_model is not None else "unknown")
                         or "unknown",
                "cost": cost,
                "free": free,
                "prompt": (str(vals[i_prompt]).strip()
                           if i_prompt is not None and vals[i_prompt] else ""),
                "platform": pname,
                "account": "",
                "requests": 1,
                "request_id": (str(vals[i_rid]).strip()
                               if i_rid is not None and vals[i_rid] else ""),
            })
    print(f"[import] {platform} csv: {len(rows)} rows")
    return rows


def _collect_files(args):
    files = []
    if args.file:
        files.append(args.file)
    if args.dir:
        for root, _dirs, names in os.walk(args.dir):
            for n in sorted(names):
                if n.lower().endswith((".csv", ".xlsx", ".zip")):
                    files.append(os.path.join(root, n))
    return files


def _parse_file(path, platform):
    low = path.lower()
    if low.endswith(".zip"):
        return _norm_deepseek_zip(path)
    if low.endswith(".xlsx"):
        return _norm_codebuddy_xlsx(path)
    if low.endswith(".csv"):
        return _norm_generic_csv(path, platform)
    print(f"[import] unsupported file type: {path}")
    return []


def main():
    ap = argparse.ArgumentParser(description="Merge an exported usage file "
                                             "into the data store.")
    ap.add_argument("--platform", required=True,
                    help="qoder / trae / codebuddy / deepseek")
    ap.add_argument("--account", required=True,
                    help="masked data-folder label (e.g. deepseek-kylinlab). "
                         "Must match across captures and imports of the same "
                         "real account so history merges correctly.")
    ap.add_argument("--file", default=None, help="a single .csv/.xlsx/.zip export")
    ap.add_argument("--dir", default=None, help="a folder of exports to merge")
    ap.add_argument("--start", default=None, help="optional filter start yyyy-mm-dd")
    ap.add_argument("--end", default=None, help="optional filter end yyyy-mm-dd")
    args = ap.parse_args()

    platform = args.platform.lower()
    label = args.account
    files = _collect_files(args)
    if not files:
        print("[import] no input files (use --file or --dir).")
        return

    req_start = req_end = None
    if args.start:
        req_start = datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end:
        req_end = datetime.strptime(args.end, "%Y-%m-%d").date()

    all_rows = []
    for fp in files:
        print(f"[import] reading {fp}")
        rows = _parse_file(fp, platform)
        if req_start or req_end:
            rows = [r for r in rows
                    if (not req_start or
                        datetime.strptime(r["date"], "%Y-%m-%d").date() >= req_start)
                    and (not req_end or
                         datetime.strptime(r["date"], "%Y-%m-%d").date() <= req_end)]
        all_rows.extend(rows)

    if not all_rows:
        print("[import] no rows parsed/filtered; nothing to merge.")
        return

    pname = PLATFORM_NAMES.get(platform, platform.capitalize())
    for r in all_rows:
        r["platform"] = pname
        r["account"] = label
        r.pop("_client", None)

    # Merge into the data folder (dedup by identity; monthly files).
    path = data_store.merge_and_save(platform, all_rows, req_start, req_end,
                                     account=label)
    print(f"[import] merged {len(all_rows)} rows -> {path}")

    # Record meta, preserving any coverage span merge_and_save() just wrote.
    data_store.write_account_meta(
        platform, label,
        name=label, masked=True, source="import",
        imported_at=datetime.now().isoformat(timespec="seconds"),
    )
    print(f"[import] data dir: {data_store.platform_data_dir(platform, label)}")
    print(f"        next: python3 build_report.py --platform {platform} "
          f"--account {label}")


if __name__ == "__main__":
    main()
