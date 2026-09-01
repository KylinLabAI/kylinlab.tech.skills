# -*- coding: utf-8 -*-
"""Chart + HTML helpers for ai-usage-report."""
import os
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


def setup_font():
    for c in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]:
        if os.path.exists(c):
            font_manager.fontManager.addfont(c)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=c).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False


def save(fig, out_dir, name):
    p = os.path.join(out_dir, name)
    fig.savefig(p, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return name


def plot_daily_count(labels, n, paid, free, out_dir):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(labels, n, marker="o", label="总次数", color="#2c7fb8", linewidth=2)
    ax.bar(labels, paid, label="付费次数", color="#2c7fb8", alpha=0.6)
    ax.bar(labels, free, bottom=paid, label="免费次数", color="#f4a582", alpha=0.85)
    ax.set_title("每日请求次数趋势（免费 / 付费）")
    ax.set_xlabel("日期"); ax.set_ylabel("请求次数")
    ax.legend(); fig.autofmt_xdate()
    return save(fig, out_dir, "daily_count.png")


def plot_daily_cost(labels, cost, out_dir):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(labels, cost, marker="o", label="费用(积分/元)", color="#d95f0e", linewidth=2)
    ax.set_title("每日费用趋势")
    ax.set_xlabel("日期"); ax.set_ylabel("费用")
    ax.legend(); fig.autofmt_xdate()
    return save(fig, out_dir, "daily_cost.png")


def plot_pie(values, labels, colors, title, out_dir, name):
    if not values or sum(values) <= 0:
        # empty / all-zero data: emit a placeholder text image
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.text(0.5, 0.5, "无数据", ha="center", va="center", fontsize=16)
        ax.axis("off"); ax.set_title(title)
        return save(fig, out_dir, name)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.pie(values, labels=labels, autopct="%1.1f%%", colors=list(colors),
           startangle=90, textprops={"fontsize": 9})
    ax.set_title(title)
    return save(fig, out_dir, name)


def plot_model_pies(model_counter, model_cost, out_dir):
    names = list(model_counter.keys())
    plot_pie(model_counter.values(),
             [f"{m}\n{c}" for m, c in model_counter.items()],
             plt.cm.Set3.colors, "请求次数 - 模型分布", out_dir, "pie_model.png")
    plot_pie([model_cost[m] for m in names],
             [f"{m}\n{round(model_cost[m], 1)}" for m in names],
             plt.cm.Set2.colors, "请求费用 - 模型分布", out_dir, "pie_model_cost.png")


def plot_task(task_counter, out_dir):
    order = sorted(range(len(task_counter)), key=lambda i: -list(task_counter.values())[i])
    names = list(task_counter.keys())
    vals = list(task_counter.values())
    tn = [vals[i] for i in order]; tnm = [names[i] for i in order]
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.barh(tnm[::-1], tn[::-1], color="#756bb1")
    ax.set_title("任务类型分布（按提示词关键词分类）")
    ax.set_xlabel("请求次数")
    return save(fig, out_dir, "task_type.png")


def render_account_breakdown(by_account):
    """HTML table comparing accounts on one platform (only when >1 account)."""
    if not by_account or len(by_account) < 2:
        return ""
    rows = sorted(by_account.items(), key=lambda kv: -kv[1]["cost"])
    body = "".join(
        f"<tr><td>{name}</td><td>{v['n']}</td><td>{v['free']}</td>"
        f"<td>{v['n'] - v['free']}</td><td>{round(v['cost'], 2)}</td>"
        f"<td>{len(v['days'])}</td></tr>"
        for name, v in rows)
    return (f"<h2>账号分布</h2>"
            f"<table><tr><th>账号</th><th>总请求</th><th>免费</th><th>付费</th>"
            f"<th>费用</th><th>活跃天数</th></tr>{body}</table>"
            f"<p class=\"note\">同平台多账号的费用单位一致，可以相加；"
            f"跨平台的费用单位不同，不可相加。</p>")


def render_html(platform, total, free, paid, total_cost,
                day_labels, day_n, day_free, day_paid, day_cost,
                model_counter, model_cost, task_counter,
                by_account=None):
    day_rows = "".join(
        f"<tr><td>{l}</td><td>{n}</td><td>{f}</td><td>{p}</td><td>{c}</td></tr>"
        for l, n, f, p, c in zip(day_labels, day_n, day_free, day_paid, day_cost))
    model_rows = "".join(
        f"<tr><td>{m}</td><td>{c}</td><td>{round(model_cost[m], 2)}</td></tr>"
        for m, c in sorted(model_counter.items(), key=lambda x: -x[1]))
    task_rows = "".join(
        f"<tr><td>{m}</td><td>{c}</td></tr>"
        for m, c in sorted(task_counter.items(), key=lambda x: -x[1]))
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>body{{font-family:-apple-system,'PingFang SC',sans-serif;margin:24px;color:#222}}
h1{{border-bottom:2px solid #2c7fb8;padding-bottom:8px}} h2{{color:#2c7fb8;margin-top:32px}}
.kpi{{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}}
.kpi div{{background:#f4f7fb;border:1px solid #dce3ec;border-radius:10px;padding:16px 20px;min-width:150px}}
.kpi b{{font-size:24px;color:#2c7fb8;display:block}}
table{{border-collapse:collapse;margin-top:12px}} td,th{{border:1px solid #ddd;padding:6px 12px;text-align:center}}
img{{max-width:100%;margin:12px 0;border:1px solid #eee;border-radius:8px}}
.note{{background:#fff8e1;border-left:4px solid #ffc107;padding:10px 14px;color:#665}}
</style></head><body>
<h1>AI 使用统计分析报告 — {platform}</h1>
<h2>总体</h2>
<div class="kpi">
  <div><b>{total}</b>总请求次数</div>
  <div><b>{free}</b>免费请求</div>
  <div><b>{paid}</b>付费请求</div>
  <div><b>{round(total_cost, 2)}</b>总费用</div>
</div>
<div class="note">说明：表中仅含单一费用列（无折扣信息）时，打折前 = 打折后 = 费用。
「免费」指费用=0 的请求；「付费」指费用&gt;0 的请求。无单次耗时字段时省略请求时间相关图表。</div>
{render_account_breakdown(by_account)}
<h2>日期趋势</h2>
<img src="daily_count.png"><img src="daily_cost.png">
<table><tr><th>日期</th><th>总次数</th><th>免费</th><th>付费</th><th>费用</th></tr>{day_rows}</table>
<h2>分布</h2>
<img src="pie_count.png"><img src="pie_model.png"><img src="pie_model_cost.png"><img src="task_type.png">
<table><tr><th>模型</th><th>次数</th><th>费用</th></tr>{model_rows}</table>
<table><tr><th>任务类型</th><th>次数</th></tr>{task_rows}</table>
<p class="note">任务类型由提示词关键词规则分类，仅供参考。</p>
</body></html>"""
