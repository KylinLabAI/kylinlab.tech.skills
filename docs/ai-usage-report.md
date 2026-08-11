# Skill Manual: ai-usage-report

## What Problem It Solves

AI platform usage lives in scattered, format-incompatible exports (CodeBuddy
xlsx, DeepSeek zip, Qoder/TRAE web portals, generic CSV/JSON). You want one
statistical, visual report across all of them without hand-crunching numbers.

## Objective

Analyze AI platform usage data and produce a self-contained HTML report (with
PNG charts) covering overall stats, daily trends, and model / task / free-vs-paid
distributions.

## Two Data Paths

1. **File export** — CodeBuddy `.xlsx`, DeepSeek `.zip` (CSV), or any generic
   `.csv` / `.xlsx` / `.json`.
2. **Browser capture** (`scrape_usage.py`) — for platforms without a clean
   export (Qoder / TRAE-CN web portals, or unifying CodeBuddy/DeepSeek via the
   web portal). A real browser keeps your login session, intercepts the backend
   usage JSON, and writes a normalized CSV.

## Persistent Data Store

Captured data is cached under a single root (env `AI_USAGE_ROOT`, default
`~/Desktop/ai-usage-report`):

```
~/Desktop/ai-usage-report/
├── data/<platform>/<start>_<end>.csv     # raw captures, one file per window
└── report/<platform>/<start>_<end>/       # report.html + charts
```

This enables **reuse** (skip fetch if range is cached), **incremental fetch**
(only fetch missing days, dedupe by `date+model+cost+prompt`), and **merge**
across partial fetches.

## Supported Inputs

| Platform | Format | Notes |
|----------|--------|-------|
| CodeBuddy | `.xlsx` (sheet `Usage Details`) | columns: `RequestID, 积分消耗, User Prompt, 模型, 客户端, 时间` |
| DeepSeek | `.zip` (contains `cost-*.csv` + `amount-*.csv`) | daily aggregated cost + token breakdown |
| Qoder / TRAE / generic | `.csv` / `.xlsx` / `.json` | best-effort column detection |

## Usage

```bash
cd skills/ai-usage-report/scripts
pip install --break-system-packages openpyxl matplotlib

# One-shot from a single export file:
python3 analyze_usage.py /path/to/export.xlsx [--out DIR] [--platform NAME]

# Or build from the persistent store (recommended):
python3 build_report.py --platform qoder --start 2026-08-01 --end 2026-08-15 [--auto-fetch]

# Browser capture (no export available):
python3 scrape_usage.py --platform qoder --url https://<usage-page> --start 2026-08-01 --end 2026-08-15
```

- `--out DIR`: output folder (default `~/Desktop/<input>_report` for one-shot;
  `~/Desktop/ai-usage-report/report/<platform>/<s>_<e>/` for store).
- `--auto-fetch`: fill missing date gaps via the scraper before building.

## Output

`<out>/report.html` plus charts: `daily_count.png`, `daily_cost.png`,
`pie_count.png`, `pie_model.png`, `pie_model_cost.png`, `task_type.png`.

## Privacy / Safety

- The browser capture signs in with **your own** session cookies locally and
  writes only a normalized usage CSV to your machine. No credentials are stored
  in the repo and no data is exfiltrated.
- The analyzer does not embed secrets/keys in the report beyond what the source
  already contains.
- No live config or secrets are committed (only empty/`configs/urls.json`
  templates).

## Extending

Add a `parse_<platform>(path)` function in `analyze_usage.py`, or a keyword in
`PLATFORM_KEYWORDS` in `scrape_usage.py`. For `--auto-fetch` URLs, edit
`configs/urls.json`. Normalized record shape:
`{date, model, cost, free, prompt, platform}`.
