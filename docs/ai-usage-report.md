# Skill Manual: ai-usage-report

## What Problem It Solves

AI platform usage (bills/usage from Qoder, TRAE, CodeBuddy, DeepSeek, …) lives
in scattered, format-incompatible exports — xlsx, zip, web portals, generic
CSV/JSON. You want one statistical, visual report across all of them for
cross-platform comparison of spend and model distribution, without hand-crunching
numbers.

## ⚠️ Key Caveats (Common Pitfalls)

1. **Cost units differ, but are convertible to RMB**: each platform's `cost`
   column uses a different native unit — Qoder / DeepSeek are in CNY/RMB, while
   TRAE / CodeBuddy are in points. `configs/units.json` defines a `rmb_per_unit`
   rate per platform (TRAE 89 RMB / 4000 积分, CodeBuddy 99 RMB / 4000 积分),
   so the cross-platform summary shows a **折算费用(RMB)** column and a
   **全平台折算合计** row. The conversion rate is user-editable in that file.
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
├── data/<platform>/
│   ├── raw/<start>_<end>.csv            # default account: per-request RAW snapshot
│   ├── <YYYY-MM>.csv                     # default (unnamed) account, ONE FILE PER MONTH
│   └── <account>/                        # one self-contained folder per account
│       ├── raw/<start>_<end>.csv        # that account's per-request RAW snapshot
│       └── <YYYY-MM>.csv
└── report/<start>_<end>/                 # ONE folder per request range
    ├── <platform>/                        # per-vendor report
    ├── <platform>/<account>/              # per-account report (optional)
    ├── <platform>/_all/                   # vendor report across its accounts
    └── summary/                           # cross-vendor combined report
```

The default (unnamed) account lives at `data/<platform>/`, so data captured
**before** multi-account support still works.

Captured data is stored as **ONE FILE PER CALENDAR MONTH** (e.g.
`2026-08.csv`), independent of the requested date range:

- A request spanning months (8/15~9/10) updates several monthly files
  (`2026-08.csv` **and** `2026-09.csv`).
- A partial request (8/10~8/20) simply merges into the existing `2026-08.csv`.
- Legacy `<start>_<end>.csv` files are auto-migrated into monthly files on the
  next save, so storage converges to the monthly layout over time.

This enables **reuse** (skip fetch if range is cached), **incremental fetch**
(only fetch missing days, dedupe by
`account+date+model+cost-bucket+free+request_id`), **merge** across partial
fetches, and **isolation** (each account is a separate store — three CodeBuddy
accounts never overwrite or silently merge into each other).

Each account's covered date range is cached as `covered_range` in
`data/<platform>/<account>/account.json`; coverage checks prefer this meta and
fall back to scanning the real CSVs when absent (then write it back). When a
requested range is only partially cached, `build_report.py` **auto-fetches the
missing gaps by default** (pass `--no-fetch` to disable). Accounts whose
`account.json` has `source == "import"` are *external-import* accounts: they can
never be pulled from the platform, so the build skips scraping them and instead
reminds you to import the external export file.

> The dedup key deliberately excludes `prompt`: platforms reformat the prompt
> preview between pulls (e.g. adding a `[client]` prefix), so including it
> would break dedup and double-count re-fetched days. It does include
> `account`, so rows from different accounts never collapse together.

## Supported Inputs

| Platform | Format | Notes |
|----------|--------|-------|
| CodeBuddy | `.xlsx` (sheet `Usage Details`) | columns: `RequestID, Points Consumed, User Prompt, Model, Client, Time` |
| DeepSeek | `.zip` (contains `cost-*.csv` + `amount-*.csv`) | daily aggregated cost + token breakdown |
| Qoder / TRAE / generic | `.csv` / `.xlsx` / `.json` | best-effort column detection |

## How To Use

### Initialization

This skill needs extra tools beyond Python 3: the `openpyxl`, `matplotlib`, and
`playwright` packages, plus the Playwright Chromium build (only required for
browser capture). Run the one-time init:

```bash
python3 skills/ai-usage-report/scripts/init.py          # install
python3 skills/ai-usage-report/scripts/init.py --check  # status only
```

Normal reporting runs should execute the task scripts directly — do not
preflight-check dependencies. If something is missing at runtime, re-run the
init above instead of installing ad hoc.

The skill ships five scripts:

1. **`scrape_usage.py`** — open the platform site in a real browser, sign in,
   auto/manually page through, and write captured records to a normalized CSV
   under `data/<platform>/` (or `data/<platform>/<label>/` when
   `--account <label>` is given). A separate persistent Chrome profile is used
   per account.
2. **`verify_data.py`** — check the cached capture for completeness (empty
   files, missing dates, duplicates, density anomalies). Non-zero exit means data
   is incomplete. **Always run this after a scrape** — missing >50% of days
   aborts report generation. Use `--account <label>` or `--all-accounts`.
3. **`build_report.py`** — merge CSVs into matplotlib charts + an HTML report
   under `report/<start>_<end>/<platform>/` (or per-account / `_all/` when
   `--account` is given). It runs the verify gate first and aborts on failure
   (use `--force` to override, with care).
4. **`cross_platform_report.py`** — combine all platforms into one overview HTML,
   embedding each platform's verify result and noting that cost units are not
   comparable across platforms.
5. **`init.py`** — one-time setup that installs Python 3 and the Python
   dependencies (plus the Playwright Chromium build) via `laptop-setup`.

(The shared helpers `analyze_usage.py`, `charts.py`, `data_store.py`, and
`normalize.py` are imported by the scripts above rather than run directly —
except for the one-shot `analyze_usage.py <file>` flow shown below.)

Guided example (Qoder, ~30 days):

```bash
# 1) Scrape (omit --headless for interactive login; --headless is a flag with
#    no value, so drop it rather than passing "False")
python3 scrape_usage.py --platform qoder \
  --url "https://qoder.com.cn/account/usage" \
  --start 2026-07-13 --end 2026-08-11

# 2) Verify (build_report also verifies, but run standalone for clarity)
python3 verify_data.py --platform qoder --start 2026-07-13 --end 2026-08-11

# 3) Single-platform report (aborts if data incomplete)
python3 build_report.py --platform qoder --start 2026-07-13 --end 2026-08-11

# 4) Cross-platform overview
python3 cross_platform_report.py --start 2026-07-13 --end 2026-08-11
```

### Multiple accounts on one platform

If you own several logins on the same platform (e.g. 3 CodeBuddy accounts), pass
`--account <label>` everywhere. Each account is stored under
`data/<platform>/<label>/` with its own raw exports, captures, coverage
gaps and report — so they never overwrite or merge. The capture uses a separate
persistent Chrome profile per account (one login each).

The account count is declared, not auto-detected, and never asked interactively.
`--setup` resolves it without blocking:

1. `configs/accounts.json` (opt-in) when it lists labels for the platform;
2. `--accounts N` passed to `--setup`, if given;
3. otherwise a single default account (`auto_1`).

```bash
# Pre-declare labels (opt-in):
#   echo '{"codebuddy": ["work","personal"]}' > configs/accounts.json
# Or pass the count non-interactively:
python3 scrape_usage.py --platform codebuddy --url <usage> --setup --accounts 4
```

`scrape_usage.py --setup` does not scan the installed IDE. It picks labels
from `configs/accounts.json` or `--accounts N`, otherwise defaults to 1, then
opens one Chrome window per account for a one-time manual login (an IDE token
cannot be replayed as a web cookie), caching each session for later runs. We
don't auto-detect because a client's local trace under-counts the real
accounts (e.g. 4 CodeBuddy logins left only 2 local traces), so detection
would silently skip accounts the user actually owns.

```bash
# Capture each account into its own store
python3 scrape_usage.py --platform codebuddy --account work \
  --url https://www.codebuddy.cn/profile/plans-usage --start 2026-08-01 --end 2026-08-31
python3 scrape_usage.py --platform codebuddy --account personal \
  --url https://www.codebuddy.cn/profile/plans-usage --start 2026-08-01 --end 2026-08-31

# Report one account, or aggregate all accounts (with a per-account breakdown)
python3 build_report.py --platform codebuddy --account work --start 2026-08-01 --end 2026-08-31
python3 build_report.py --platform codebuddy --account all --start 2026-08-01 --end 2026-08-31

# Verify one account, or every account
python3 verify_data.py --platform codebuddy --account personal --start 2026-08-01 --end 2026-08-31
python3 verify_data.py --platform codebuddy --all-accounts --start 2026-08-01 --end 2026-08-31
```

With no `--account`, scripts operate on the default (unnamed) store;
`build_report.py` additionally prints a hint listing any other accounts it found.

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
# Auto-fetch missing gaps is ON by default; --no-fetch builds from cache only.
python3 build_report.py --platform qoder --start 2026-08-01 --end 2026-08-15 [--no-fetch]
```

Flags:
- `--out DIR`: output folder (default `~/Desktop/<input>_report` for one-shot;
  `~/Desktop/ai-usage-report/report/<s>_<e>/<platform>/` for store).
- `--auto-fetch` (default on): fill missing date gaps via the scraper before
  building. External-import accounts (`account.json` `source == "import"`) are
  skipped and you are reminded to import the export instead.
- `--no-fetch`: build the report from the existing cache only; never scrape.
- `--account <label>`: scope every operation to one account
  (`scrape_usage.py` / `verify_data.py` / `build_report.py`). Use `all` with
  `build_report.py` to aggregate every account into one report with a per-account
  breakdown. `verify_data.py` uses `--all-accounts` to check every account.

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
`{date, model, cost, free, prompt, platform, account, requests}` (`account`
is part of the dedup identity; default `""` for the unnamed store).

## Related Skill File

See [`SKILL.md`](../skills/ai-usage-report/SKILL.md) for the agent-facing
execution rules.
