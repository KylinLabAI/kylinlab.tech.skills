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

Output (per request range):
  report/<start>_<end>/summary/report.html   # cross-vendor combined report
  (per-vendor reports are produced by build_report.py under report/<start>_<end>/<platform>/)
"""
import argparse
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


def _accounts_with_data(platform):
    """Accounts holding data for a platform; [None] = default store."""
    return data_store.list_accounts(platform) or [None]


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

    # Report layout: one folder per request range, with a per-vendor sub-folder;
    # the combined summary lives at report/<start>_<end>/summary/.
    req_dir = data_store.report_request_dir(start, end)
    plat_link = {}
    for p in PLATS:
        pdir = data_store.platform_report_dir(p, None, start, end)
        plat_link[p] = (os.path.join("..", p, "report.html")
                        if os.path.isfile(os.path.join(pdir, "report.html")) else f"{p}/")

    plat_verify = {}   # (platform, account) -> (errors, warnings)
    stats = {}
    cols = []          # one column per (platform, account)
    combined = defaultdict(lambda: defaultdict(float))
    all_dates = set()

    for p in PLATS:
        for acc in _accounts_with_data(p):
            key = (p, acc)
            cols.append(key)
            # load_consolidated (not a raw CSV scan) so the numbers here match
            # the per-platform reports, including dedup.
            rows = data_store.load_consolidated(p, start, end, acc)
            cost = 0.0
            n = free = paid = 0
            models = defaultdict(float)
            wdates = defaultdict(float)
            for r in rows:
                d_str = r.get("date") or ""
                if not d_str:
                    continue
                c = float(r.get("cost") or 0)
                cost += c
                n += 1
                if c == 0:
                    free += 1
                else:
                    paid += 1
                models[r.get("model", "?")] += c
                wdates[d_str] += c
                all_dates.add(d_str)
                combined[d_str][key] += c
            # link to this vendor's per-request report (default account)
            link = plat_link[p]
            stats[key] = dict(n=n, cost=round(cost, 2), free=free, paid=paid,
                              models=dict(sorted(models.items(),
                                                 key=lambda x: -x[1])[:5]),
                              wdays=len(wdates), link=link)
            # run verify gate (best-effort, do not abort the whole summary)
            try:
                errs, warns, _ = verify_data.verify(p, start, end, acc)
                plat_verify[key] = (errs, warns)
            except Exception as e:
                plat_verify[key] = ([], [f"verify 失败: {e}"])

    # ---- build HTML ----
    def _col(key):
        """Human label for a (platform, account) column."""
        p, acc = key
        return LABEL[p] if not acc else f"{LABEL[p]} · {acc}"

    rows_cmp = "".join(
        f"<tr><td>{_col(k)}</td><td>{stats[k]['n']}</td>"
        f"<td>{stats[k]['paid']}</td><td>{stats[k]['free']}</td>"
        f"<td>{stats[k]['cost']} {UNIT[k[0]]}</td>"
        f"<td>{stats[k]['wdays']}</td>"
        f"<td>{', '.join(f'{m} ({round(v,1)})' for m,v in stats[k]['models'].items())}</td>"
        f"<td><a href='{stats[k]['link']}/report.html' target='_blank'>打开报告</a></td></tr>"
        for k in cols
    )

    verify_notes = "".join(
        f"<li><b>{_col(k)}</b>: "
        + ("✅ 校验通过" if not any(plat_verify[k])
           else "; ".join("⚠ " + w for w in plat_verify[k][1])
           + ("; " + "; ".join("❌ " + e for e in plat_verify[k][0]) if plat_verify[k][0] else ""))
        + "</li>"
        for k in cols
    )

    sd = sorted(all_dates)
    daily_head = "".join(f"<th>{_col(k)}</th>" for k in cols)
    daily_rows = ""
    for d in sd:
        if not (start <= dt.datetime.strptime(d, "%Y-%m-%d").date() <= end):
            continue
        tds = "".join(f"<td>{round(combined[d].get(k, 0), 2)}</td>" for k in cols)
        daily_rows += f"<tr><td>{d}</td>{tds}</tr>"

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
<h2>平台 / 账号对比</h2>
<table><tr><th>平台 · 账号</th><th>总请求</th><th>付费</th><th>免费</th><th>总费用(单位见各列)</th><th>窗口内活跃天数</th><th>Top 模型（费用）</th><th>独立报告</th></tr>
{rows_cmp}
</table>
<h2>每日费用趋势（按平台 · 账号，单位各自独立）</h2>
<table><tr><th>日期</th>{daily_head}</tr>
{daily_rows}
</table>
</body></html>"""

    out = os.path.join(req_dir, "summary", "report.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[cross] written: {out}")


if __name__ == "__main__":
    main()
