# -*- coding: utf-8 -*-
"""Generate a combined cross-platform AI usage summary (last N days).

Reads all captured CSVs from the data store for each platform, runs the
verify gate so incomplete captures are flagged, and emits a single HTML
summary with a per-platform comparison + daily trend + report links.

IMPORTANT: cost units differ per platform and are NOT additive:
  - qoder / deepseek : 美元 or 额度
  - trae / codebuddy : 积分 (points)
Do not sum across platforms.

Usage:
  python3 cross_platform_report.py [--days 30] [--start 2026-07-13] [--end 2026-08-11]
"""
import argparse
import csv
import glob
import os
import sys
import datetime as dt
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data_store  # noqa: E402
import verify_data  # noqa: E402

ROOT = data_store.ROOT
PLATS = ["qoder", "trae", "codebuddy", "deepseek"]
LABEL = {
    "qoder": "Qoder (国内个人版)",
    "trae": "TRAE (国内版)",
    "codebuddy": "CodeBuddy",
    "deepseek": "DeepSeek (开放平台)",
}
# cost unit note per platform (NOT additive across platforms!)
UNIT = {
    "qoder": "美元/额度",
    "trae": "积分(points)",
    "codebuddy": "积分/额度",
    "deepseek": "美元",
}


def main():
    ap = argparse.ArgumentParser(description="Cross-platform usage summary.")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--start", default=None, help="yyyy-mm-dd (overrides --days)")
    ap.add_argument("--end", default=None, help="yyyy-mm-dd (default: today)")
    args = ap.parse_args()

    today = dt.date.today()
    if args.end:
        end = dt.datetime.strptime(args.end, "%Y-%m-%d").date()
    else:
        end = today
    if args.start:
        start = dt.datetime.strptime(args.start, "%Y-%m-%d").date()
    else:
        start = end - dt.timedelta(days=args.days)

    plat_verify = {}   # platform -> (errors, warnings)
    stats = {}
    for p in PLATS:
        files = glob.glob(f"{data_store.platform_data_dir(p)}/*.csv")
        cost = 0.0
        n = free = paid = 0
        models = defaultdict(float)
        wdates = defaultdict(float)
        for f in files:
            with open(f, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if not row.get("date"):
                        continue
                    d = dt.datetime.strptime(row["date"], "%Y-%m-%d").date()
                    c = float(row.get("cost") or 0)
                    cost += c
                    n += 1
                    if c == 0:
                        free += 1
                    else:
                        paid += 1
                    models[row.get("model", "?")] += c
                    if start <= d <= end:
                        wdates[row["date"]] += c
        # highest-uid report dir for the link
        rep_dirs = sorted(glob.glob(
            os.path.join(data_store.platform_report_dir(p), "*_*")))
        link = rep_dirs[-1].replace(ROOT, "..") if rep_dirs else f"{p}/"
        stats[p] = dict(n=n, cost=round(cost, 2), free=free, paid=paid,
                        models=dict(sorted(models.items(), key=lambda x: -x[1])[:5]),
                        wdays=len(wdates), link=link)
        # run verify gate (best-effort, do not abort the whole summary)
        try:
            errs, warns, _ = verify_data.verify(p, start, end)
            plat_verify[p] = (errs, warns)
        except Exception as e:
            plat_verify[p] = ([], [f"verify 失败: {e}"])

    # combined daily cost across all platforms (align by date)
    all_dates = set()
    for p in PLATS:
        for f in glob.glob(f"{data_store.platform_data_dir(p)}/*.csv"):
            with open(f, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("date"):
                        all_dates.add(row["date"])
    combined = defaultdict(lambda: defaultdict(float))
    for p in PLATS:
        for f in glob.glob(f"{data_store.platform_data_dir(p)}/*.csv"):
            with open(f, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if not row.get("date"):
                        continue
                    combined[row["date"]][p] += float(row.get("cost") or 0)

    # ---- build HTML ----
    rows_cmp = "".join(
        f"<tr><td>{LABEL[p]}</td><td>{stats[p]['n']}</td>"
        f"<td>{stats[p]['paid']}</td><td>{stats[p]['free']}</td>"
        f"<td>{stats[p]['cost']} {UNIT[p]}</td>"
        f"<td>{stats[p]['wdays']}</td>"
        f"<td>{', '.join(f'{k} ({round(v,1)})' for k,v in stats[p]['models'].items())}</td>"
        f"<td><a href='{stats[p]['link']}/report.html' target='_blank'>打开报告</a></td></tr>"
        for p in PLATS
    )

    verify_notes = "".join(
        f"<li><b>{LABEL[p]}</b>: "
        + ("✅ 校验通过" if not any(plat_verify[p])
           else "; ".join("⚠ " + w for w in plat_verify[p][1])
           + ("; " + "; ".join("❌ " + e for e in plat_verify[p][0]) if plat_verify[p][0] else ""))
        + "</li>"
        for p in PLATS
    )

    sd = sorted(all_dates)
    daily_rows = "".join(
        "<tr><td>%s</td><td>%.2f</td><td>%.2f</td><td>%.2f</td><td>%.2f</td></tr>"
        % (d,
           combined[d].get("qoder", 0), combined[d].get("trae", 0),
           combined[d].get("codebuddy", 0), combined[d].get("deepseek", 0))
        for d in sd if start <= dt.datetime.strptime(d, "%Y-%m-%d").date() <= end
    )

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>body{{font-family:-apple-system,'PingFang SC',sans-serif;margin:24px;color:#222}}
h1{{border-bottom:2px solid #2c7fb8;padding-bottom:8px}}
h2{{color:#2c7fb8;margin-top:32px}}
table{{border-collapse:collapse;margin-top:12px}} td,th{{border:1px solid #ddd;padding:6px 12px;text-align:center}}
.note{{background:#fff8e1;border-left:4px solid #ffc107;padding:10px 14px;color:#665;margin:12px 0}}
.warn{{background:#fdecea;border-left:4px solid #e53935;padding:10px 14px;margin:12px 0}}
a{{color:#2c7fb8}}
</style></head><body>
<h1>AI 平台使用统计 · 汇总（{start} ~ {end}）</h1>
<div class="note"><b>单位说明：</b>各平台费用单位不同且<b>不可直接相加</b>——
Qoder/DeepSeek 为美元/额度，TRAE/CodeBuddy 为积分(points)。
跨平台比较请使用「请求数 / 活跃天数」等无量纲指标。
数据来自本地已抓取缓存，未做外发。</div>
<div class="warn"><b>数据完整性校验：</b>
<ul>{verify_notes}</ul>
若有 ❌，请先用 <code>scrape_usage.py --platform &lt;p&gt; --start {start} --end {end}</code>
补齐后再重新生成本报告。</div>
<h2>平台对比</h2>
<table><tr><th>平台</th><th>总请求</th><th>付费</th><th>免费</th><th>总费用(单位见各列)</th><th>窗口内活跃天数</th><th>Top 模型（费用）</th><th>独立报告</th></tr>
{rows_cmp}
</table>
<h2>每日费用趋势（按平台，单位各自独立）</h2>
<table><tr><th>日期</th><th>Qoder</th><th>TRAE</th><th>CodeBuddy</th><th>DeepSeek</th></tr>
{daily_rows}
</table>
</body></html>"""

    out = os.path.join(data_store.platform_report_dir("_combined"),
                       f"{start}_{end}", "summary.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[cross] written: {out}")


if __name__ == "__main__":
    main()
