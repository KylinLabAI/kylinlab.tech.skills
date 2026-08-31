# Skill Manual: ai-usage-report

## What Problem It Solves

AI platform usage (bills/usage from Qoder, TRAE, CodeBuddy, DeepSeek, …) lives
in scattered, format-incompatible exports — xlsx, zip, web portals, generic
CSV/JSON. You want one statistical, visual report across all of them for
cross-platform comparison of spend and model distribution, without hand-crunching
numbers.

## ⚠️ Key Caveats (Common Pitfalls)

1. **Cost units are not additive**: each platform's `cost` column uses a
   different unit — Qoder / DeepSeek are in CNY/RMB, while TRAE / CodeBuddy are
   in points. For cross-platform comparison, only compare dimensionless metrics
   like request count, active days, and Top models.
2. **Fetching everything ≠ fetching correctly**: if browser pagination/
   scrolling doesn't actually trigger the next-page request, data is **silently
   dropped**. Therefore, after every capture you **must** run `verify_data.py`
   or let `build_report.py` auto-verify; if more than 50% of days are missing,
   report generation aborts.
3. **Qoder capture fixed**: `_fetch_qoder_api_pages` now parses the JSON
   returned by `page.evaluate()` directly (no longer relying on Playwright's
   `on_response`, which dropped paginated data in the old implementation), and
   date ranges are converted to epoch-ms in Beijing time (UTC+8).

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
| CodeBuddy | `.xlsx` (sheet `Usage Details`) | columns: `RequestID, Points Consumed, User Prompt, Model, Client, Time` |
| DeepSeek | `.zip` (contains `cost-*.csv` + `amount-*.csv`) | daily aggregated cost + token breakdown |
| Qoder / TRAE / generic | `.csv` / `.xlsx` / `.json` | best-effort column detection |

## How To Use

Install dependencies once, in the scripts directory:

```bash
cd skills/ai-usage-report/scripts
pip install --break-system-packages openpyxl matplotlib
```

The skill ships four scripts:

1. **`scrape_usage.py`** — open the platform site in a real browser, sign in,
   auto/manually page through, and write captured records to a normalized CSV
   under `data/<platform>/`.
2. **`verify_data.py`** — check the cached capture for completeness (empty
   files, missing dates, duplicates, density anomalies). Non-zero exit means data
   is incomplete. **Always run this after a scrape** — missing >50% of days
   aborts report generation.
3. **`build_report.py`** — merge CSVs into matplotlib charts + an HTML report
   under `report/<platform>/<start>_<end>/`. It runs the verify gate first and
   aborts on failure (use `--force` to override, with care).
4. **`cross_platform_report.py`** — combine all platforms into one overview HTML,
   embedding each platform's verify result and noting that cost units are not
   comparable across platforms.

Guided example (Qoder, ~30 days):

```bash
# 1) Scrape (set --headless False for interactive login)
python3 scrape_usage.py --platform qoder \
  --url "https://qoder.com.cn/account/usage" \
  --out ~/Desktop/ai-usage-report/data/qoder/2026-07-13_2026-08-11.csv \
  --start-date 2026-07-13 --end-date 2026-08-11 --headless False

# 2) Verify (build_report also verifies, but run standalone for clarity)
python3 verify_data.py --platform qoder --start 2026-07-13 --end 2026-08-11

# 3) Single-platform report (aborts if data incomplete)
python3 build_report.py --platform qoder --start 2026-07-13 --end 2026-08-11

# 4) Cross-platform overview
python3 cross_platform_report.py --start 2026-07-13 --end 2026-08-11
```

One-shot from a single export file (no scrape needed):

```bash
python3 analyze_usage.py /path/to/export.xlsx [--out DIR] [--platform NAME]
```

### Automatic download (no manual export)

For platforms that expose a usage/export REST API, `scrape_usage.py` can pull
data **directly with a date range** using the persistent Chrome profile's
cookies — no manual "export / download" click, and (once the session is
cached) no manual login either.

- **Qoder**: works out of the box (endpoint is in `configs/api_templates.json`).
- **CodeBuddy**: works out of the box too — the endpoint
  (`/billing/meter/get-user-request-usage`, POST with a `yyyy-MM-dd HH:mm:ss`
  Beijing-time range) is baked into `configs/api_templates.json`. First run
  logs in once; later runs are fully automatic.
- **DeepSeek**: run a one-time discovery to capture the real endpoint, then
  every later run is automatic:

  ```bash
  # One-time: log in, open the usage/export page, capture the API request
  python3 scrape_usage.py --platform deepseek \
    --url https://platform.deepseek.com/usage --discover

  # From now on: fully automatic (cookie auth + date-range API call)
  python3 scrape_usage.py --platform deepseek \
    --url https://platform.deepseek.com/usage \
    --start 2026-07-13 --end 2026-08-11
  ```

  (CodeBuddy also supports `--discover` if the endpoint/body ever changes.)

  `--discover` saves the endpoint to the system temp dir
  (`$TMPDIR/ai-usage-report/specs/<platform>_api.json`) — a transient override,
  not user data, never committed. Edit the saved stub if the date placeholders
  (`{start}`/`{end}`) or a `{page}` token need adjusting; set
  `"date_format": "ms"` for epoch-millisecond APIs (with `tz_offset_hours`).

If no API spec is configured, or the cached session expired, the scraper
falls back to the manual-login + UI-intercept flow, preserving the old
behavior.

Build from the persistent store (recommended), with auto-fill of missing gaps:

```bash
python3 build_report.py --platform qoder --start 2026-08-01 --end 2026-08-15 [--auto-fetch]
```

Flags:
- `--out DIR`: output folder (default `~/Desktop/<input>_report` for one-shot;
  `~/Desktop/ai-usage-report/report/<platform>/<s>_<e>/` for store).
- `--auto-fetch`: fill missing date gaps via the scraper before building.

## Output

`<out>/report.html` plus charts: `daily_count.png`, `daily_cost.png`,
`pie_count.png`, `pie_model.png`, `pie_model_cost.png`, `task_type.png`.

## Example Usage

User: "Use ai-usage-report to generate a ~30-day usage analysis for qoder/codebuddy/trae/deepseek"
→ scrape per platform (fill missing ranges) → verify → build → cross_platform_report.

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

## Related Skill File

See [`SKILL.md`](../skills/ai-usage-report/SKILL.md) for the agent-facing
execution rules.
