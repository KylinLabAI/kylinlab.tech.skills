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


def render_account_breakdown_md(by_account, unit):
    """Markdown table comparing accounts on one platform (only when >1 account)."""
    if not by_account or len(by_account) < 2:
        return ""
    rows = sorted(by_account.items(), key=lambda kv: -kv[1]["cost"])
    body = "\n".join(
        f"| {name} | {v['n']} | {v['free']} | {v['n'] - v['free']} | "
        f"{round(v['cost'], 2)} {unit} | {len(v['days'])} |"
        for name, v in rows)
    return (f"## 账号分布\n\n"
            f"| 账号 | 总请求 | 免费 | 付费 | 费用 | 活跃天数 |\n"
            f"| --- | --- | --- | --- | --- | --- |\n{body}\n\n"
            f"> 同平台多账号的费用单位一致，可以相加；跨平台的费用单位不同，不可相加。\n")


def render_markdown(platform, total, free, paid, total_cost, unit,
                    day_labels, day_n, day_free, day_paid, day_cost,
                    model_counter, model_cost, task_counter,
                    dmin=None, dmax=None, by_account=None, total_cost_rmb=None,
                    total_credits=None):
    """Render the per-platform usage report as a Markdown document.

    Charts are still produced as PNGs (see plot_*); they are embedded via
    relative ``![](name.png)`` links so the .md is portable inside its folder.
    """
    rng = f"（{dmin} ~ {dmax}）" if dmin and dmax else ""
    credits_line = (f"| 积分消耗（各平台单位不同，不可跨平台相加） | {round(total_credits, 2)} |\n"
                   if total_credits else "")
    day_rows = "\n".join(
        f"| {l} | {n} | {f} | {p} | {c} |"
        for l, n, f, p, c in zip(day_labels, day_n, day_free, day_paid, day_cost))
    model_rows = "\n".join(
        f"| {m} | {c} | {round(model_cost[m], 2)} |"
        for m, c in sorted(model_counter.items(), key=lambda x: -x[1]))
    task_rows = "\n".join(
        f"| {m} | {c} |"
        for m, c in sorted(task_counter.items(), key=lambda x: -x[1]))
    return f"""# AI 使用统计分析报告 — {platform}{rng}

## 总体

| 指标 | 数值 |
| --- | --- |
| 总请求次数 | {total} |
| 免费请求 | {free} |
| 付费请求 | {paid} |
| 总费用 | {round(total_cost, 2)} {unit} |
| 折算费用(RMB) | {round(total_cost_rmb, 2) if total_cost_rmb is not None else "—"} |
{credits_line}

> 说明：表中仅含单一费用列（无折扣信息）时，打折前 = 打折后 = 费用。「免费」指费用=0 的请求；「付费」指费用>0 的请求。无单次耗时字段时省略请求时间相关图表。

{render_account_breakdown_md(by_account, unit)}
## 日期趋势

![每日请求次数（免费/付费）](daily_count.png)

![每日费用趋势](daily_cost.png)

| 日期 | 总次数 | 免费 | 付费 | 费用 |
| --- | --- | --- | --- | --- |
{day_rows}

## 分布

![次数分布：免费 vs 付费](pie_count.png)

![请求次数 - 模型分布](pie_model.png)

![请求费用 - 模型分布](pie_model_cost.png)

![任务类型分布](task_type.png)

| 模型 | 次数 | 费用 |
| --- | --- | --- |
{model_rows}

| 任务类型 | 次数 |
| --- | --- |
{task_rows}

> 任务类型由提示词关键词规则分类，仅供参考。
"""
