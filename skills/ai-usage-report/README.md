# Skill Manual: ai-usage-report

## What Problem It Solves

把多个 AI 编码平台（Qoder / TRAE / CodeBuddy / DeepSeek 等）网页上的"用量/账单"
抓取成结构化 CSV，并自动生成可视化报告，便于横向对比投入与模型分布。

## ⚠️ 关键注意事项（易错点）

1. **费用单位不可相加**：各平台 `cost` 列单位不同——
   Qoder / DeepSeek 为「美元/额度」，TRAE / CodeBuddy 为「积分(points)」。
   跨平台只比较「请求数、活跃天数、Top 模型」等无量纲指标。
2. **抓全 ≠ 抓对**：浏览器分页/滚动若没真正触发下一页请求，会**静默漏数据**。
   因此每次抓取后**必须**跑 `verify_data.py` 或让 `build_report.py` 自动校验，
   缺失超过 50% 的天数会直接中止出报告。
3. **Qoder 抓取已修正**：`_fetch_qoder_api_pages` 直接解析 `page.evaluate()`
   返回的 JSON（不再依赖 Playwright 的 `on_response`，旧实现会丢分页），
   日期范围按北京时间 UTC+8 转 epoch-ms。

## Workflow / Design

1. `scrape_usage.py` —— 用 Playwright 打开平台网页，登录后自动/手动翻页，
   把响应里的记录转成统一 CSV 落盘到 `data/<platform>/`。
2. `verify_data.py` —— 校验缓存完整性（空文件、缺日期、重复、密度异常），
   返回 ERROR/WARNING，退出码非 0 表示数据不完整。
3. `build_report.py` —— 合并 CSV → 生成 matplotlib 图表 + HTML 报告到
   `report/<platform>/<start>_<end>/`。默认先跑 verify 门禁，失败则中止
   （可用 `--force` 强制作废门禁，慎用）。
4. `cross_platform_report.py` —— 把四个平台汇总成一份总览 HTML，
   内嵌各平台校验结果，明确指出单位不可相加。

## When To Use It

- "帮我统计最近 30 天各 AI 编码工具花了多少 / 用了什么模型"
- "对比 CodeBuddy / Qoder / TRAE / DeepSeek 使用量"

## How To Use This Skill

```bash
# 1) 抓取（需交互登录时设 --headless False）
python3 scrape_usage.py --platform qoder \
  --url "https://qoder.com.cn/account/usage" \
  --out ~/Desktop/ai-usage-report/data/qoder/2026-07-13_2026-08-11.csv \
  --start-date 2026-07-13 --end-date 2026-08-11 --headless False

# 2) 校验（build_report 也会自动校验，但先单独跑一次更直观）
python3 verify_data.py --platform qoder --start 2026-07-13 --end 2026-08-11

# 3) 出单平台报告（数据不全会中止并提示）
python3 build_report.py --platform qoder --start 2026-07-13 --end 2026-08-11

# 4) 出跨平台总览
python3 cross_platform_report.py --start 2026-07-13 --end 2026-08-11
```

## Example Usage

用户："用 ai-usage-report 生成 qoder/codebuddy/trae/deepseek 近 30 天用量分析"
→ 逐平台 scrape（补齐缺失范围）→ verify → build → cross_platform_report。

## Related Skill File

See [SKILL.md](./SKILL.md) for the agent-facing execution rules.
