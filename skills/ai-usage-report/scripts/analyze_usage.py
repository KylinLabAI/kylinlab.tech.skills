# -*- coding: utf-8 -*-
"""
analyze_usage.py — Analyze AI platform usage export files and generate a report.

Supported platforms / formats (auto-detected by file name + content):
  - CodeBuddy : .xlsx  (RequestID, 积分消耗, User Prompt, 模型, 客户端, 时间)
  - DeepSeek  : .zip   containing cost-*.csv + amount-*.csv (daily aggregated)
  - Qoder / TRAE / generic : .csv / .xlsx / .json (best-effort column detection)

Usage:
  python3 analyze_usage.py <input_file> [--out DIR] [--platform NAME]
"""
import argparse
import csv
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime

import charts

try:
    import data_store
except ImportError:
    data_store = None

try:
    import openpyxl
except ImportError:
    openpyxl = None


# ----------------------------- helpers -----------------------------
def to_float(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return 0.0


def to_dt(x):
    s = str(x).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s[:19])
    except Exception:
        return None


def read_csv_rows(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return list(csv.DictReader(f))


# ----------------------------- parsers -----------------------------
def parse_codebuddy_xlsx(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    ci_cost = idx.get("积分消耗", idx.get("cost", 1))
    ci_prompt = idx.get("User Prompt", idx.get("prompt", 2))
    ci_model = idx.get("模型", idx.get("model", 3))
    ci_time = idx.get("时间", idx.get("time", 5))
    recs = []
    for r in rows[1:]:
        if not r or all(c is None for c in r):
            continue
        cost = to_float(r[ci_cost]) if ci_cost < len(r) else 0.0
        dt = to_dt(r[ci_time]) if ci_time < len(r) else None
        recs.append({
            "date": dt.date() if dt else None,
            "model": str(r[ci_model]) if ci_model < len(r) and r[ci_model] else "unknown",
            "cost": cost,
            "free": cost == 0.0,
            "prompt": str(r[ci_prompt]) if ci_prompt < len(r) and r[ci_prompt] else "",
            "platform": "CodeBuddy",
        })
    return recs


def parse_deepseek_zip(path):
    """DeepSeek export: cost-*.csv (per-day cost) + amount-*.csv (token breakdown).

    cost csv columns: user_id, start_time_iso, end_time_iso, model, wallet_type, cost, currency
    amount csv columns: user_id, start_time_iso, end_time_iso, model, api_key_name, api_key, type, price, amount
    """
    recs = []
    token_totals = defaultdict(float)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        cost_csv = next((n for n in names if "cost" in n.lower()), None)
        amount_csv = next((n for n in names if "amount" in n.lower()), None)
        if cost_csv:
            with z.open(cost_csv) as f:
                for row in csv.DictReader(f.read().decode("utf-8-sig", errors="replace").splitlines()):
                    dt = to_dt(row.get("start_time_iso", ""))
                    cost = to_float(row.get("cost", 0))
                    wallet = (row.get("wallet_type") or "").lower()
                    is_free = (wallet != "paid") or cost == 0.0
                    recs.append({
                        "date": dt.date() if dt else None,
                        "model": row.get("model", "unknown") or "unknown",
                        "cost": cost, "free": is_free, "prompt": "",
                        "platform": "DeepSeek",
                    })
        if amount_csv:
            with z.open(amount_csv) as f:
                for row in csv.DictReader(f.read().decode("utf-8-sig", errors="replace").splitlines()):
                    dt = to_dt(row.get("start_time_iso", ""))
                    model = row.get("model", "unknown") or "unknown"
                    token_totals[model] += to_float(row.get("amount", 0))
                    recs.append({
                        "date": dt.date() if dt else None,
                        "model": model,
                        "cost": 0.0, "free": True, "prompt": "",
                        "platform": "DeepSeek",
                        "tokens": to_float(row.get("amount", 0)),
                        "type": row.get("type", ""),
                    })
    return recs


def parse_generic_csv(path):
    """Accept either the scraper's normalized CSV (date,model,cost,free,prompt)
    or arbitrary platform exports (loose column matching)."""
    recs = []
    for row in read_csv_rows(path):
        dt = to_dt(row.get("date") or row.get("时间") or row.get("日期") or "")
        cost = to_float(row.get("cost") or row.get("消耗") or row.get("费用") or 0)
        # honor an explicit free flag if present
        free_raw = str(row.get("free", "")).strip().lower()
        if free_raw in ("true", "1", "yes", "free"):
            free = True
        elif free_raw in ("false", "0", "no", "paid"):
            free = False
        else:
            free = cost == 0.0
        model = (row.get("model") or row.get("模型") or row.get("模型名称")
                 or row.get("modelName") or "unknown")
        recs.append({
            "date": dt.date() if dt else None,
            "model": model,
            "cost": cost, "free": free,
            "prompt": row.get("prompt") or row.get("User Prompt") or "",
            "platform": row.get("platform") or "Generic",
        })
    return recs


def parse_xlsx_generic(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip().lower() for h in rows[0]]
    def find(*keys):
        for k in keys:
            for i, h in enumerate(header):
                if k in h:
                    return i
        return None
    ci_cost = find("cost", "消耗", "费用")
    ci_model = find("model", "模型")
    ci_time = find("time", "时间", "日期")
    ci_prompt = find("prompt", "提示")
    recs = []
    for r in rows[1:]:
        if not r or all(c is None for c in r):
            continue
        cost = to_float(r[ci_cost]) if ci_cost is not None and ci_cost < len(r) else 0.0
        dt = to_dt(r[ci_time]) if ci_time is not None and ci_time < len(r) else None
        recs.append({
            "date": dt.date() if dt else None,
            "model": str(r[ci_model]) if ci_model is not None and ci_model < len(r) and r[ci_model] else "unknown",
            "cost": cost, "free": cost == 0.0,
            "prompt": str(r[ci_prompt]) if ci_prompt is not None and ci_prompt < len(r) and r[ci_prompt] else "",
            "platform": "XLSX",
        })
    return recs


def parse_json(path):
    data = json.load(open(path, encoding="utf-8"))
    if not isinstance(data, list):
        data = data.get("records", data.get("data", []))
    recs = []
    for d in data:
        if not isinstance(d, dict):
            continue
        dt = to_dt(d.get("date") or d.get("时间") or d.get("日期"))
        cost = to_float(d.get("cost") or d.get("消耗") or 0)
        recs.append({
            "date": dt.date() if dt else None,
            "model": str(d.get("model") or d.get("模型") or "unknown"),
            "cost": cost, "free": cost == 0.0,
            "prompt": str(d.get("prompt") or ""),
            "platform": "JSON",
        })
    return recs


def is_codebuddy_xlsx(path):
    """Detect CodeBuddy export by sheet name or header."""
    try:
        wb = openpyxl.load_workbook(path, read_only=True)
        if any("usage" in s.lower() for s in wb.sheetnames):
            return True
        ws = wb[wb.sheetnames[0]]
        first = next(ws.iter_rows(values_only=True), [])
        return any(str(h).strip() in ("积分消耗", "User Prompt", "RequestID") for h in first)
    except Exception:
        return False


def detect_and_parse(path, platform_hint=None):
    low = path.lower()
    hint = (platform_hint or "").lower()
    if low.endswith(".zip"):
        return parse_deepseek_zip(path), "DeepSeek"
    if low.endswith(".json"):
        return parse_json(path), "JSON"
    if low.endswith(".csv"):
        return parse_generic_csv(path), (platform_hint or "CSV")
    if low.endswith(".xlsx"):
        if openpyxl is None:
            raise RuntimeError("openpyxl required for .xlsx; pip install openpyxl")
        if "codebuddy" in hint or "codebuddy" in low or is_codebuddy_xlsx(path):
            return parse_codebuddy_xlsx(path), "CodeBuddy"
        return parse_xlsx_generic(path), (platform_hint or "XLSX")
    raise ValueError("Unsupported file type: " + path)


# ----------------------------- analysis -----------------------------
def classify_task(prompt):
    if not prompt:
        return "其他/对话"
    p = prompt.lower()
    rules = [
        (r"git-repo-check|git status|commit|push|pull|分支|repo", "Git/版本控制"),
        (r"read|explore|analyze|summary|总结|分析|理解|探索|review", "代码阅读/分析"),
        (r"improve|update|fix|add|create|write|修改|改进|更新|实现|生成|写", "代码编写/修改"),
        (r"blog|draft|文档|doc|markdown|\.md", "文档/博客"),
        (r"workflow|stage|agent|工作流", "工作流/Agent"),
    ]
    for pat, label in rules:
        if re.search(pat, p):
            return label
    return "其他/对话"


def analyze(records, platform, out_dir, unit="元(RMB)"):
    os.makedirs(out_dir, exist_ok=True)
    total = len(records)
    # All money math is done in RMB via configs/units.json (rmb_per_unit) so the
    # end-user report only ever shows comparable ¥ — the platform-native 积分 /
    # credits never reach the output. The native `cost` is still kept in the CSV;
    # it is converted to RMB exactly once, here, then summed everywhere.
    to_rmb = (data_store.to_rmb if data_store
              else lambda p, c: round(float(c or 0), 2))

    def rc(r):
        return to_rmb(platform, r.get("cost", 0) or 0)

    total_cost = round(sum(rc(r) for r in records), 2)
    total_cost_rmb = total_cost  # `cost` is already RMB after the conversion above
    free = sum(1 for r in records if r["free"])
    paid = total - free

    by_day = defaultdict(lambda: {"n": 0, "free": 0, "cost": 0.0})
    for r in records:
        d = r["date"] or "unknown"
        by_day[d]["n"] += 1
        by_day[d]["free"] += 1 if r["free"] else 0
        by_day[d]["cost"] += rc(r)
    days = sorted([d for d in by_day if d != "unknown"])
    day_labels = [d.strftime("%m-%d") if hasattr(d, "strftime") else str(d) for d in days]
    day_n = [by_day[d]["n"] for d in days]
    day_free = [by_day[d]["free"] for d in days]
    day_paid = [by_day[d]["n"] - by_day[d]["free"] for d in days]
    day_cost = [round(by_day[d]["cost"], 2) for d in days]

    model_counter = Counter(r["model"] for r in records)
    model_cost = defaultdict(float)
    for r in records:
        model_cost[r["model"]] += rc(r)
    task_counter = Counter(classify_task(r["prompt"]) for r in records)

    # Per-account rollup. Only rendered when the data actually spans more than
    # one account (e.g. `build_report.py --account all`).
    by_account = defaultdict(lambda: {"n": 0, "cost": 0.0, "free": 0, "days": set()})
    for r in records:
        a = str(r.get("account") or "default")
        by_account[a]["n"] += 1
        by_account[a]["cost"] += rc(r)
        if r["free"]:
            by_account[a]["free"] += 1
        if r.get("date"):
            by_account[a]["days"].add(str(r["date"]))

    charts.setup_font()
    charts.plot_daily_count(day_labels, day_n, day_paid, day_free, out_dir)
    charts.plot_daily_cost(day_labels, day_cost, out_dir, unit=unit)
    charts.plot_pie([free, paid], [f"免费\n{free}", f"付费\n{paid}"],
                    ["#f4a582", "#2c7fb8"], "次数分布：免费 vs 付费", out_dir, "pie_count.png")
    charts.plot_model_pies(model_counter, model_cost, out_dir)
    charts.plot_task(task_counter, out_dir)

    dates = [r["date"] for r in records if r.get("date")]
    # Consolidated rows store `date` as an ISO "YYYY-MM-DD" string, which sorts
    # chronologically, so min/max need no parsing.
    dmin = min(dates) if dates else None
    dmax = max(dates) if dates else None
    md = charts.render_markdown(platform, total, free, paid, total_cost, unit,
                                day_labels, day_n, day_free, day_paid, day_cost,
                                model_counter, model_cost, task_counter,
                                dmin=dmin, dmax=dmax,
                                by_account=by_account if len(by_account) > 1 else None,
                                total_cost_rmb=total_cost_rmb)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(md)
    return {
        "total": total, "free": free, "paid": paid,
        "total_cost": total_cost, "total_cost_rmb": total_cost_rmb,
        "out": out_dir,
    }


def main():
    ap = argparse.ArgumentParser(description="Analyze AI platform usage export and generate report.")
    ap.add_argument("input", help="Path to usage export file (xlsx/zip/csv/json)")
    ap.add_argument("--out", default=None, help="Output directory (default: <data_root>/<input>_report)")
    ap.add_argument("--platform", default=None, help="Force platform name (CodeBuddy/DeepSeek/Qoder/TRAE/...)")
    args = ap.parse_args()

    if args.out:
        out = args.out
    else:
        from data_store import get_root
        stem = os.path.splitext(os.path.basename(args.input))[0]
        out = os.path.join(get_root(), stem + "_report")
    records, platform = detect_and_parse(args.input, args.platform)
    summary = analyze(records, platform, out)
    print(f"Platform: {platform}")
    print(f"Records : {summary['total']} (free={summary['free']}, paid={summary['paid']})")
    print(f"Cost    : {summary['total_cost']}")
    print(f"Report  : {os.path.join(out, 'report.md')}")


if __name__ == "__main__":
    main()
