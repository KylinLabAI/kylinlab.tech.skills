# -*- coding: utf-8 -*-
"""Generate a combined cross-platform AI usage summary (last N days).

Reads all captured CSVs from the data store for each platform, runs the
verify gate so incomplete captures are flagged, and emits a single Markdown
summary with a per-platform comparison + daily trend + report links.

IMPORTANT: cost units differ per platform (Qoder/DeepSeek = RMB, TRAE/CodeBuddy = 积分),
but configs/units.json converts 积分 -> RMB so a comparable cross-platform RMB total is shown.
Per-platform native cost is NOT summed directly; only the RMB-converted figures are added.

Usage:
  python3 cross_platform_report.py [--days 30] [--start 2026-07-13] [--end 2026-08-11]

Output (one folder per generation, named by a timestamp run id):
  report/<run_id>/summary/report.md          # cross-vendor combined report
  (per-vendor reports are produced by build_report.py under report/<run_id>/<platform>/)
"""
import argparse
import os
import sys
import datetime as dt
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data_store  # noqa: E402
import verify_data  # noqa: E402
import charts  # noqa: E402
import analyze_usage  # noqa: E402

ROOT = data_store.ROOT
PLATS = ["qoder", "trae", "codebuddy", "deepseek"]
LABEL = {
    "qoder": "Qoder (国内个人版)",
    "trae": "TRAE (国内版)",
    "codebuddy": "CodeBuddy",
    "deepseek": "DeepSeek (开放平台)",
}
# cost unit + RMB conversion are sourced from configs/units.json via data_store
# (native units differ per platform; to_rmb() converts 积分 -> RMB for comparison).


def _accounts_with_data(platform):
    """Accounts holding data for a platform; [None] = default store."""
    return data_store.list_accounts(platform) or [None]


def main():
    ap = argparse.ArgumentParser(description="Cross-platform usage summary.")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--start", default=None, help="yyyy-mm-dd (overrides --days)")
    ap.add_argument("--end", default=None, help="yyyy-mm-dd (default: today)")
    ap.add_argument("--out", default=None,
                    help="report folder name (run id); default: a generation "
                         "timestamp. Pass the SAME value used for build_report.py "
                         "so the per-vendor links resolve.")
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
    req_dir = data_store.report_run_dir(args.out)
    sum_dir = os.path.join(req_dir, "summary")
    plat_link = {}
    for p in PLATS:
        # Per-vendor report lives at ../<platform>/report.md relative to summary/.
        plat_link[p] = f"../{p}/"

    plat_verify = {}   # (platform, account) -> (errors, warnings)
    stats = {}
    cols = []          # one column per (platform, account)
    combined = defaultdict(lambda: defaultdict(float))
    all_dates = set()
    # combined (cross-platform) accumulators — cost is kept in RMB so charts
    # are comparable; request counts are summed directly across platforms.
    combined_n = defaultdict(int)
    combined_free = defaultdict(int)
    combined_paid = defaultdict(int)
    combined_cost_rmb = defaultdict(float)
    platform_n = defaultdict(int)
    platform_cost_rmb = defaultdict(float)
    combined_model_counter = Counter()
    combined_model_cost_rmb = defaultdict(float)
    combined_task_counter = Counter()

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
                # combined (cross-platform) accumulators
                crmb = data_store.to_rmb(p, c)
                combined_n[d_str] += 1
                if c == 0:
                    combined_free[d_str] += 1
                else:
                    combined_paid[d_str] += 1
                combined_cost_rmb[d_str] += crmb
                platform_n[p] += 1
                platform_cost_rmb[p] += crmb
                mdl = r.get("model", "?")
                combined_model_counter[mdl] += 1
                combined_model_cost_rmb[mdl] += crmb
                combined_task_counter[analyze_usage.classify_task(r.get("prompt") or "")] += 1
            # link to this vendor's per-request report (default account)
            link = plat_link[p]
            stats[key] = dict(n=n, cost=round(cost, 2), free=free, paid=paid,
                              models=dict(sorted(models.items(),
                                                 key=lambda x: -x[1])[:5]),
                              wdays=len(wdates), link=link,
                              unit=data_store.platform_unit(p),
                              cost_rmb=round(data_store.to_rmb(p, cost), 2))
            # run verify gate (best-effort, do not abort the whole summary)
            try:
                errs, warns, _ = verify_data.verify(p, start, end, acc)
                plat_verify[key] = (errs, warns)
            except Exception as e:
                plat_verify[key] = ([], [f"verify 失败: {e}"])

    # ---- build Markdown ----
    def _col(key):
        """Human label for a (platform, account) column."""
        p, acc = key
        return LABEL[p] if not acc else f"{LABEL[p]} · {acc}"

    def _esc(x):
        return str(x).replace("|", "\\|")

    rate_trae = data_store.rmb_per_unit("trae")
    rate_cb = data_store.rmb_per_unit("codebuddy")
    rows_cmp = "\n".join(
        f"| {_esc(_col(k))} | {stats[k]['n']} | {stats[k]['paid']} | "
        f"{stats[k]['free']} | {stats[k]['cost']} {stats[k]['unit']} | "
        f"{stats[k]['cost_rmb']} | {stats[k]['wdays']} | "
        f"{_esc(', '.join(f'{m} ({round(v,1)})' for m,v in stats[k]['models'].items()))} | "
        f"[打开报告]({stats[k]['link']}report.md) |"
        for k in cols
    )
    tot_n = sum(s['n'] for s in stats.values())
    tot_paid = sum(s['paid'] for s in stats.values())
    tot_free = sum(s['free'] for s in stats.values())
    tot_rmb = round(sum(s['cost_rmb'] for s in stats.values()), 2)
    rows_cmp += (
        f"| **全平台折算合计** | {tot_n} | {tot_paid} | {tot_free} | "
        f"—（单位不同） | **{tot_rmb}** | — | — | — |\n"
    )

    verify_notes = "\n".join(
        f"- **{_esc(_col(k))}**: "
        + ("✅ 校验通过" if not any(plat_verify[k])
           else "; ".join("⚠ " + w for w in plat_verify[k][1])
           + ("; " + "; ".join("❌ " + e for e in plat_verify[k][0]) if plat_verify[k][0] else ""))
        for k in cols
    )

    sd = sorted(all_dates)
    daily_head = "".join(f"| {_esc(_col(k))} " for k in cols)
    daily_rows = ""
    for d in sd:
        if not (start <= dt.datetime.strptime(d, "%Y-%m-%d").date() <= end):
            continue
        tds = "".join(f"| {round(combined[d].get(k, 0), 2)} " for k in cols)
        daily_rows += f"| {d} {tds}|\n"

    # ---- combined charts (mirror the per-platform report, merging all data) ----
    charts_md = ""
    if platform_n:
        os.makedirs(sum_dir, exist_ok=True)
        charts.setup_font()
        sd_chart = sorted(all_dates)
        day_labels = [d[5:] if len(d) >= 10 else d for d in sd_chart]
        day_n = [combined_n[d] for d in sd_chart]
        day_free = [combined_free[d] for d in sd_chart]
        day_paid = [combined_paid[d] for d in sd_chart]
        day_cost_rmb = [round(combined_cost_rmb[d], 2) for d in sd_chart]
        charts.plot_daily_count(day_labels, day_n, day_paid, day_free, sum_dir)
        charts.plot_daily_cost(day_labels, day_cost_rmb, sum_dir, unit="元(RMB)")
        charts.plot_pie([sum(combined_free.values()), sum(combined_paid.values())],
                        [f"免费\n{sum(combined_free.values())}",
                         f"付费\n{sum(combined_paid.values())}"],
                        ["#f4a582", "#2c7fb8"], "次数分布：免费 vs 付费",
                        sum_dir, "pie_count.png", others_pct=0)
        charts.plot_model_pies(combined_model_counter, combined_model_cost_rmb, sum_dir)
        charts.plot_task(combined_task_counter, sum_dir)
        plats_present = [p for p in PLATS if platform_n[p] > 0]
        _pc = ["#2c7fb8", "#d95f0e", "#756bb1", "#31a354",
               "#e7298a", "#66a61e", "#ff7f00"]
        charts.plot_pie([platform_cost_rmb[p] for p in plats_present],
                        [f"{LABEL[p]}\n{round(platform_cost_rmb[p], 1)}"
                         for p in plats_present],
                        _pc, "折算费用(RMB) 各平台占比", sum_dir, "pie_platform_cost.png",
                        others_pct=0)
        charts.plot_pie([platform_n[p] for p in plats_present],
                        [f"{LABEL[p]}\n{platform_n[p]}" for p in plats_present],
                        _pc, "请求次数 各平台占比", sum_dir, "pie_platform_request.png",
                        others_pct=0)
        charts_md = f"""
## 图表概览（全平台合并）

> 以下图表合并所有平台数据。**费用类图表均按 `configs/units.json` 折算率换算为 RMB**（各平台原生单位不同，不可直接相加）；请求次数可直接相加。

### 每日趋势

![每日请求次数（免费/付费）](daily_count.png)

![每日折算费用(RMB)趋势](daily_cost.png)

### 分布

![次数分布：免费 vs 付费](pie_count.png)

![请求次数 - 模型分布](pie_model.png)

![请求费用(折算RMB) - 模型分布](pie_model_cost.png)

![任务类型分布](task_type.png)

### 各平台占比（汇总专属）

![折算费用(RMB) 各平台占比](pie_platform_cost.png)

![请求次数 各平台占比](pie_platform_request.png)
"""

    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    top3_models = combined_model_counter.most_common(3)
    top3_str = "、".join(f"{m}（{n}）" for m, n in top3_models) or "—"
    summary_block = (
        "## 摘要\n\n"
        "| 字段 | 值 |\n"
        "| --- | --- |\n"
        f"| 生成时间 | {generated} |\n"
        f"| 报告日期范围 | {start} ~ {end} |\n"
        f"| 总费用（折算 RMB） | {tot_rmb} |\n"
        f"| 总请求次数 | {tot_n} |\n"
        f"| Top 3 模型（按请求量） | {top3_str} |\n\n"
    )
    md = f"""# AI 平台使用统计 · 汇总（{start} ~ {end}）

{summary_block}> **单位说明：** 各平台原生费用单位不同（Qoder/DeepSeek 为人民币；TRAE/CodeBuddy 为积分），
> 本表「折算费用(RMB)」按 `configs/units.json` 的折算率把积分换算成人民币以便跨平台比较：
> TRAE {rate_trae}/积分（89RMB/4000积分），CodeBuddy {rate_cb}/积分（99RMB/4000积分）。
> 末行「全平台折算合计」即为可比的人民币总费用。
> 数据来自本地已抓取缓存，未做外发。

## 数据完整性校验

{verify_notes}

若有 ❌，请先用 `scrape_usage.py --platform <p> --start {start} --end {end}` 补齐后再重新生成本报告。

## 平台 / 账号对比

| 平台 · 账号 | 总请求 | 付费 | 免费 | 总费用(单位见各列) | 折算费用(RMB) | 窗口内活跃天数 | Top 模型（费用） | 独立报告 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
{rows_cmp}

## 每日费用趋势（按平台 · 账号，单位各自独立）

| 日期 {daily_head}|
| ---{"| ---" * len(cols)}
{daily_rows}
""" + charts_md
    out = os.path.join(sum_dir, "report.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[cross] written: {out}")


if __name__ == "__main__":
    main()
