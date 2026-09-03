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
    plat_link = {}
    for p in PLATS:
        # Per-vendor report lives at ../<platform>/report.md relative to summary/.
        plat_link[p] = f"../{p}/"

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

    md = f"""# AI 平台使用统计 · 汇总（{start} ~ {end}）

> **单位说明：** 各平台原生费用单位不同（Qoder/DeepSeek 为人民币；TRAE/CodeBuddy 为积分），
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
"""
    out = os.path.join(req_dir, "summary", "report.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[cross] written: {out}")


if __name__ == "__main__":
    main()
