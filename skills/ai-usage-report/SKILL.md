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

1. **File export (preferred)** — CodeBuddy `.xlsx`, DeepSeek `.zip` (CSV), or
   any generic `.csv`/`.xlsx`/`.json`. Export files are placed in
   `data/<platform>/raw/` and normalized automatically before reporting.
2. **Browser capture** (`scrape_usage.py`) — for platforms without a reliable
   export (Qoder / TRAE-CN web portals). Playwright opens a real browser,
   keeps the login session, intercepts the backend usage JSON, and writes a
   normalized CSV.

**Critical guardrail**: `build_report.py` always runs `verify_data.py` first.
If a browser capture misses >50% of the requested days, the report is aborted
unless `--force` is given. This prevents the silent data-loss bug that
affected Qoder captures before Aug 2026.

## Persistent data store (incremental + reuse)

All captured data lives under a single root (override with env `AI_USAGE_ROOT`,
default **`~/Desktop/ai-usage-report`**):

```
~/Desktop/ai-usage-report/
├── data/<platform>/
│   ├── raw/                              # original exports (.xlsx / .zip / .csv)
│   └── <start>_<end>.csv                 # normalized captures, one file per window
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
CodeBuddy .xlsx  ──► data/<p>/raw/ ──(normalize.py)──► data/<p>/<s>_<e>.csv
DeepSeek  .zip   ──► data/<p>/raw/ ──(normalize.py)──► data/<p>/<s>_<e>.csv
data/<p>/*.csv   ──(build_report.py)──► report/<p>/<s>_<e>/report.html
all platforms    ──(cross_platform_report.py)──► report/_combined/<s>_<e>/summary.html
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

## Auto-download via direct API (no manual export)

For platforms that expose a usage/export REST API, `scrape_usage.py` can pull
data **directly with a date range** using the persistent Chrome profile's
cookies — so there is **no manual "export / download" click** and, once the
session is cached, **no manual login** either. This is the preferred path over
the file-export workflow for those platforms.

- **Qoder**: works out of the box (endpoint is baked into
  `configs/api_templates.json`). The scraper calls
  `usages/big_model_credits/histories` with `start_time`/`end_time` (epoch ms,
  Beijing time) and paginates.
- **CodeBuddy**: works out of the box — the endpoint is baked into
  `configs/api_templates.json` (`/billing/meter/get-user-request-usage`, POST
  with a `yyyy-MM-dd HH:mm:ss` Beijing-time range). The first run logs in once
  (cookie cached in the persistent profile); every later run is fully automatic.
- **DeepSeek**: run a one-time discovery to capture the real endpoint, then every
  later run is automatic:

  ```bash
  # 1) One-time: log in, open the usage/export page, capture the API request
  python3 scrape_usage.py --platform deepseek \
    --url https://platform.deepseek.com/usage --discover

  # 2) From now on: fully automatic (cookie auth, date-range API call)
  python3 scrape_usage.py --platform deepseek --url <usage-page> \
    --start 2026-07-13 --end 2026-08-11
  ```

  CodeBuddy one-time discovery (only if the endpoint/body ever changes):
  ```bash
  python3 scrape_usage.py --platform codebuddy \
    --url https://www.codebuddy.cn/profile/plans-usage --discover
  ```

  `--discover` saves the captured endpoint to the **system temp dir**
  (`$TMPDIR/ai-usage-report/specs/<platform>_api.json`) — a transient override,
  not user data, never committed. Edit the saved stub if date placeholders
  (`{start}`/`{end}`) or a `{page}` token need adjusting. `date_format` is
  `"date"` by default; set `"ms"` for epoch-millisecond APIs (like Qoder) with
  `tz_offset_hours`.

If no API spec is configured (or the cached session expired), the scraper
falls back to the manual-login + UI-intercept flow described above, so the
existing behavior is preserved.

## Usage (analyze)

```bash
cd <skill_dir>/scripts
pip install openpyxl matplotlib playwright
python3 -m playwright install chromium

# 1) Drop official exports into the raw/ folder, then normalize:
cp request-usage-2026-08-12.xlsx  ~/Desktop/ai-usage-report/data/codebuddy/raw/
cp usage_data_2026-07-14_2026-08-12.zip ~/Desktop/ai-usage-report/data/deepseek/raw/
python3 normalize.py

# 2) For platforms without export (Qoder / TRAE), browser-capture the missing range:
python3 scrape_usage.py --platform qoder --url https://qoder.com.cn/account/usage \
  --start 2026-07-13 --end 2026-08-11
python3 scrape_usage.py --platform trae --url <trae-usage-url> \
  --start 2026-07-13 --end 2026-08-11

# 3) Verify, then build per-platform reports:
python3 verify_data.py --platform codebuddy --start 2026-07-13 --end 2026-08-11
python3 build_report.py --platform codebuddy --start 2026-07-13 --end 2026-08-11

# 4) Cross-platform summary (units are NOT additive):
python3 cross_platform_report.py --start 2026-07-13 --end 2026-08-11
```

- `--out DIR`  : output folder (**default `~/Desktop/<input>_report`** for
  one-shot; `~/Desktop/ai-usage-report/report/<platform>/<s>_<e>/` for store)
- `--platform`: force a platform label when auto-detect is ambiguous

## Output

`<out>/report.html` plus charts: `daily_count.png`, `daily_cost.png`,
`pie_count.png`, `pie_model.png`, `pie_model_cost.png`, `task_type.png`.

## Notes / assumptions

- **Cost units differ per platform and must NOT be summed across platforms**:
  CodeBuddy/TRAE report 积分 (points); Qoder/DeepSeek report 人民币/额度 (CNY/RMB).
  The cross-platform summary only compares request counts / active days / model mix.
- If the export has only a single cost column (no discount info), the report
  treats 打折前 = 打折后 = cost. "免费" = cost 0 (or `wallet_type=free` /
  `free=true`); "付费" = cost > 0.
- If there is no per-request duration field, time-based charts are omitted
  (noted in the report).
- Task-type is keyword-classified from the prompt text (Git/版本控制,
  代码阅读/分析, 代码编写/修改, 文档/博客, 工作流/Agent, 其他/对话) — heuristic.
- No secrets/keys are written to the report beyond what the source contains;
  the analyzer does not exfiltrate data.
- Export files in `data/<platform>/raw/` are kept untouched; `normalize.py`
  produces derived CSVs. You can always re-run `normalize.py` or delete the
  derived CSVs and start over from the original export.

## Extending

Add a `parse_<platform>(path)` function in `analyze_usage.py` and register it
in `detect_and_parse()`. Keep the normalized record shape:
`{date, model, cost, free, prompt, platform}`.
For a new no-export platform, add a keyword to `PLATFORM_KEYWORDS` in
`scrape_usage.py`. To add a platform URL for `--auto-fetch`, edit
`configs/urls.json`.
