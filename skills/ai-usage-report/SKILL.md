---
name: ai-usage-report
description: Analyze AI platform usage export files (CodeBuddy xlsx, DeepSeek zip csv, Qoder, TRAE, generic csv/json/xlsx) and generate a statistical HTML report with daily/cost/model/task charts. Use when the user wants to summarize, visualize, or report on exported AI assistant usage data.
---

# AI Usage Report

Analyze AI platform usage data and produce a self-contained HTML report (with
PNG charts) covering overall stats, daily trends, and model / task /
free-vs-paid distributions.

The skill handles **two data-acquisition paths** that both feed the same
analyzer:

1. **File export** — CodeBuddy `.xlsx`, DeepSeek `.zip` (CSV), or any
   generic `.csv`/`.xlsx`/`.json`.
2. **Browser capture** (`scrape_usage.py`) — for platforms without a reliable
   export (Qoder / TRAE-CN web portals, or unifying CodeBuddy/DeepSeek via the
   web portal). Playwright opens a real browser, keeps the login session,
   intercepts the backend usage JSON, and writes a normalized CSV.

## Persistent data store (incremental + reuse)

All captured data lives under a single root (override with env `AI_USAGE_ROOT`,
default **`~/Desktop/ai-usage-report`**):

```
~/Desktop/ai-usage-report/
├── data/<platform>/<start>_<end>.csv     # raw captures, one file per fetch window
└── report/<platform>/<start>_<end>/       # generated reports (report.html + charts)
```

Each raw file is named after the date range it covers
(e.g. `data/qoder/2026-08-01_2026-08-15.csv`). This lets the skill:

- **Reuse**: if a user later asks for a range already fully cached, no fetch
  happens — `build_report.py` just reads the CSVs.
- **Incremental fetch**: if the requested range only partially overlaps cached
  data, the scraper fetches *only the missing days* and re-merges (dedup by
  `date+model+cost+prompt`). Overlapping days are not double-counted.
- **Merge**: `data_store.load_consolidated()`/ `merge_and_save()` dedupe across
  files so multiple partial fetches combine into one clean dataset.

```bash
# First fetch (writes data/qoder/2026-08-01_2026-08-15.csv)
python3 scrape_usage.py --platform qoder --url <url> --start 2026-08-01 --end 2026-08-15

# Later ask for 8/10~8/25 → only 8/16~8/25 is fetched, merged with the above
python3 scrape_usage.py --platform qoder --url <url> --start 2026-08-10 --end 2026-08-25

# Later ask for 7/15~8/15 → fully cached, NO fetch, report built from disk
python3 build_report.py --platform qoder --start 2026-07-15 --end 2026-08-15

# Auto-fill any missing gaps then build the report
python3 build_report.py --platform qoder --start 2026-08-01 --end 2026-08-31 --auto-fetch
```

`data_store.py` API: `covered_dates(p)`, `missing_ranges(start,end,p)`,
`merge_and_save(p,records,start,end)`, `load_consolidated(p,start,end)`.

## Unified data flow

```
Platform web portal  ──(scrape_usage.py --start/--end)──► data/<p>/<s>_<e>.csv
CodeBuddy .xlsx  ─────────────────┐
DeepSeek  .zip   ─────────────────┤
any .csv/.json   ─────────────────┘──(analyze_usage.py)──► report/<p>/.../report.html
data/<p>/*.csv   ──(build_report.py)──► report/<p>/<s>_<e>/report.html
```

## Supported inputs (analyze_usage.py, auto-detected by filename + content)

| Platform   | Format | Notes |
|------------|--------|-------|
| CodeBuddy  | `.xlsx` (sheet `Usage Details`) | columns: `RequestID, 积分消耗, User Prompt, 模型, 客户端, 时间` |
| DeepSeek   | `.zip` (contains `cost-*.csv` + `amount-*.csv`) | daily aggregated cost + token breakdown |
| Qoder / TRAE / generic | `.csv` / `.xlsx` / `.json` | best-effort column detection; scraper CSV uses `date,model,cost,free,prompt,platform` |

## Browser capture (scrape_usage.py)

Use when a platform has no clean export. The browser handles cookies / JWT /
anti-bot; we only listen to fetch responses and collect the raw usage records.

```bash
pip install playwright && playwright install chromium
# Qoder / TRAE (no export) — start/end drive incremental storage:
python3 scrape_usage.py --platform qoder  --url https://<usage-page> --start 2026-08-01 --end 2026-08-15
python3 scrape_usage.py --platform trae  --url https://<usage-page> --start 2026-08-01 --end 2026-08-15
# Unify CodeBuddy / DeepSeek via web portal (optional):
python3 scrape_usage.py --platform codebuddy --url https://<usage-page> --start 2026-08-01 --end 2026-08-15
```

Per-platform API keyword hints (override with `--keyword`):

| Platform | default keyword |
|----------|-----------------|
| Qoder (国内个人版) | `usages/big_model_credits/histories` |
| TRAE-CN | `query_user_usage_group_by_session` |
| CodeBuddy web | `usage` |
| DeepSeek web | `usage/by_api_key` |

> Tip: run `headless=False` (default) to avoid bot detection; solve any captcha
> manually after the login step. Qoder's date range is selected in the UI
> (custom range if `--start`/`--end` given, else "最近30天" preset).

## Usage (analyze)

```bash
cd <skill_dir>/scripts
pip install --break-system-packages openpyxl matplotlib   # deps (xlsx + charts)

# One-shot from a single export file:
python3 analyze_usage.py /path/to/export.xlsx [--out DIR] [--platform NAME]

# Or build from the persistent data store (recommended workflow):
python3 build_report.py --platform qoder --start 2026-08-01 --end 2026-08-15 [--auto-fetch]
```

- `--out DIR`  : output folder (**default `~/Desktop/<input>_report`** for
  one-shot; `~/Desktop/ai-usage-report/report/<platform>/<s>_<e>/` for store)
- `--platform`: force a platform label when auto-detect is ambiguous

## Output

`<out>/report.html` plus charts: `daily_count.png`, `daily_cost.png`,
`pie_count.png`, `pie_model.png`, `pie_model_cost.png`, `task_type.png`.

## Notes / assumptions

- If the export has only a single cost column (no discount info), the report
  treats 打折前 = 打折后 = cost. "免费" = cost 0 (or `wallet_type=free` /
  `free=true`); "付费" = cost > 0.
- If there is no per-request duration field, time-based charts are omitted
  (noted in the report).
- Task-type is keyword-classified from the prompt text (Git/版本控制,
  代码阅读/分析, 代码编写/修改, 文档/博客, 工作流/Agent, 其他/对话) — heuristic.
- No secrets/keys are written to the report beyond what the source contains;
  the analyzer does not exfiltrate data.

## Extending

Add a `parse_<platform>(path)` function in `analyze_usage.py` and register it
in `detect_and_parse()`. Keep the normalized record shape:
`{date, model, cost, free, prompt, platform}`.
For a new no-export platform, add a keyword to `PLATFORM_KEYWORDS` in
`scrape_usage.py`. To add a platform URL for `--auto-fetch`, edit
`configs/urls.json`.
