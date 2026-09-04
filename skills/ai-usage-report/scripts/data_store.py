# -*- coding: utf-8 -*-
"""
data_store.py — Persistent, incremental storage for AI platform usage data.

Design goals
------------
- One platform = one folder under ai-usage-report/data/<platform>/
- Raw captures are saved as <YYYY-MM>.csv — ONE FILE PER CALENDAR MONTH,
  independent of whatever date range the user requested. A request that spans
  several months updates several monthly files (e.g. 8/15~9/10 touches
  2026-08.csv and 2026-09.csv); a partial request (8/10~8/20) simply merges into
  the existing 2026-08.csv. Re-fetches never double-count (dedup by identity).
- When a user asks for a date range we FIRST check what is already on disk.
  We only fetch the *missing* days, then merge into the monthly files. This
  saves time and API calls.

Multi-account support
---------------------
A user may own several accounts on the same platform (e.g. 3 CodeBuddy
accounts). Accounts MUST stay isolated: mixed together they would be
indistinguishable, and rows that happen to share (date, model, cost) would be
collapsed by the dedup logic, silently under-counting usage.

Layout — every account is its own folder; the default (unnamed) account lives
directly under the platform folder:

    data/<platform>/<YYYY-MM>.csv              # default account, one file per month
    data/<platform>/<account>/<YYYY-MM>.csv    # one folder per named account
    data/<platform>/raw/<start>_<end>.csv      # per-request RAW snapshot (default)
    data/<platform>/<account>/raw/<start>_<end>.csv  # per-account RAW snapshot
    report/<start>_<end>/<platform>/           # per-request, per-vendor report
    report/<start>_<end>/<platform>/<account>/ # per-account report (optional)
    report/<start>_<end>/summary/              # cross-vendor combined report

`account=None` (or "") always means the default store, so data captured before
multi-account support keeps working unchanged.

Normalized record schema (same as the scraper / analyzer):
    date, model, cost, free, prompt, platform, account, requests, request_id, row_id, credits

Public API
----------
    ROOT                   -> ~/Desktop/ai-usage-report (overridable via env)
    platform_data_dir(p, account=None)   -> .../data/<p>[/<acc>]
    platform_report_dir(p, account=None) -> .../report/<p>[/<acc>]
    list_accounts(p)       -> [None, "a", ...] accounts that hold CSVs
    list_data_files(p, account=None)     -> [ (start, end, path), ... ]  (monthly)
    covered_dates(p, account=None)       -> set(date) already captured
    missing_ranges(req_start, req_end, p, account=None)
                            -> list[(date,date)] of gaps to fetch
    merge_and_save(p, records, req_start, req_end, account=None)
                            -> writes/updates CSVs, returns consolidated path
    raw_capture_dir(p, account=None)  -> .../data/<p>[/<acc>]/raw
    raw_capture_path(p, account, start, end) -> .../raw/<start>_<end>.csv
    save_raw_capture(p, account, start, end, records)
                            -> writes one per-request RAW snapshot CSV
    load_consolidated(p, req_start, req_end, account=None)
                            -> combined, deduped CSV rows for a requested range
"""
import calendar
import csv
import hashlib
import json
import os
import re
from datetime import date, datetime

def _load_user_config():
    """Load the user-editable configs/config.yaml (sibling of this script's
    parent dir). Returns {} when missing or unreadable so the rest of the code
    can fall back to env / built-in defaults."""
    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "configs", "config.yaml",
    )
    if not os.path.exists(cfg_path):
        return {}
    try:
        import yaml
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_CONFIG = _load_user_config()


# ---- cost unit + RMB conversion (configs/units.json) ---------------------
# Each platform stores `cost` in its NATIVE unit (RMB or 积分). This table
# converts积分-bearing platforms into RMB so cross-platform totals are comparable.
_UNITS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "units.json",
)
_UNITS_CACHE = None


def units_config():
    """Load configs/units.json (per-platform cost unit + RMB conversion rate)."""
    global _UNITS_CACHE
    if _UNITS_CACHE is None:
        _UNITS_CACHE = {}
        if os.path.exists(_UNITS_PATH):
            try:
                with open(_UNITS_PATH, encoding="utf-8") as f:
                    _UNITS_CACHE = json.load(f)
            except Exception:
                _UNITS_CACHE = {}
    return _UNITS_CACHE


def platform_unit(platform):
    """Human unit label for a platform, e.g. '人民币(RMB)' / '积分(points)'."""
    cfg = units_config().get("platforms", {}).get((platform or "").lower(), {})
    return cfg.get("unit", "未知")


def rmb_per_unit(platform):
    """Multiplier converting one native cost unit into RMB (1.0 for RMB platforms)."""
    cfg = units_config().get("platforms", {}).get((platform or "").lower(), {})
    try:
        return float(cfg.get("rmb_per_unit", 1.0))
    except Exception:
        return 1.0


def to_rmb(platform, cost):
    """Convert a native-unit cost into RMB using the platform's rate."""
    return round(float(cost or 0) * rmb_per_unit(platform), 2)


def get_root():
    """Resolve the output root.

    Precedence (highest wins):
        1. env  AI_USAGE_ROOT
        2. config.yaml `data_root`   (user-editable, no code change needed)
        3. built-in  ~/Desktop/ai-usage-report
    """
    root = os.environ.get("AI_USAGE_ROOT")
    if not root:
        root = _CONFIG.get("data_root")
    if not root:
        root = os.path.join(os.path.expanduser("~/Desktop"), "ai-usage-report")
    return os.path.expanduser(root)


ROOT = get_root()
FIELDS = ["date", "model", "cost", "free", "prompt", "platform", "account",
          "requests", "request_id", "row_id", "credits"]
DATE_FMT = "%Y-%m-%d"
# Named accounts live under data/<platform>/<account>/ (one folder per account).
# The default (unnamed) account is the platform folder itself, so data captured
# before multi-account support keeps working unchanged.
# Cost tolerance for dedup: platforms may return the same logical cost with
# tiny float/currency-conversion differences across re-fetches. Treat anything
# within this epsilon as the same cost so it dedups instead of double-counting.
COST_EPS = 1e-4


def _d(s):
    """Parse a yyyy-mm-dd string to date, or None."""
    try:
        return datetime.strptime(s.strip(), DATE_FMT).date()
    except Exception:
        return None


def safe_account(account):
    """Normalize an account label to a filesystem-safe folder name.

    Unicode word characters (incl. CJK) are preserved, so a masked account name
    like "王x二" becomes a valid, distinct folder name on macOS/Linux. Only
    non-word separators (spaces, punctuation other than ./-) collapse to "-".
    Returns "" for the default (unnamed) account.
    """
    s = (account or "").strip()
    if not s:
        return ""
    return re.sub(r"[^\w.-]+", "-", s).strip("-")


def platform_data_dir(platform, account=None):
    d = os.path.join(ROOT, "data", platform.lower())
    acc = safe_account(account)
    if acc:
        d = os.path.join(d, acc)
    os.makedirs(d, exist_ok=True)
    return d


def report_request_dir(req_start, req_end):
    """Top-level report folder for one request range: report/<start>_<end>/.

    Kept for backwards compatibility; new reports use report_run_dir() instead.
    """
    return os.path.join(ROOT, "report",
                        f"{req_start.strftime('%Y-%m-%d')}_{req_end.strftime('%Y-%m-%d')}")


def report_run_dir(run_id=None):
    """Top-level report folder, named by a run id.

    Default: a generation timestamp ``YYYY-MM-DD_HH-MM-SS`` (local time), so each
    report generation is an immutable snapshot. All reports of one generation
    live under this folder, which lets the summary link to the per-vendor
    reports. Pass ``run_id`` (e.g. via ``--out``) to fix the folder name.
    """
    if not run_id:
        run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join(ROOT, "report", run_id)


def platform_report_dir(platform, account=None, req_start=None, req_end=None,
                        run_id=None):
    """Report output dir for a platform.

    Preferred layout (when ``run_id`` is supplied) — one folder per generation,
    with a sub-folder per vendor:
        report/<run_id>/<platform>[/<account>]
    The default (unnamed) account has no extra sub-folder. When a request range
    is supplied (legacy) the range-based folder is used for backwards compat.
    """
    if run_id:
        d = os.path.join(report_run_dir(run_id), platform.lower())
        acc = safe_account(account)
        if acc:
            d = os.path.join(d, acc)
        os.makedirs(d, exist_ok=True)
        return d
    if req_start and req_end:
        d = report_request_dir(req_start, req_end)
        d = os.path.join(d, platform.lower())
        acc = safe_account(account)
        if acc:
            d = os.path.join(d, acc)
        os.makedirs(d, exist_ok=True)
        return d
    d = os.path.join(ROOT, "report", platform.lower())
    acc = safe_account(account)
    if acc:
        d = os.path.join(d, acc)
    os.makedirs(d, exist_ok=True)
    return d


def raw_capture_dir(platform, account=None):
    """Folder for per-request raw capture snapshots.

        data/<platform>/raw/                  # default account
        data/<platform>/<account>/raw/        # named account
    """
    return os.path.join(platform_data_dir(platform, account), "raw")


def raw_capture_path(platform, account, start, end):
    """Path of the per-request raw snapshot for a capture window."""
    return os.path.join(raw_capture_dir(platform, account),
                        f"{start.strftime('%Y-%m-%d')}_{end.strftime('%Y-%m-%d')}.csv")


def save_raw_capture(platform, account, start, end, records):
    """Persist the raw captured records for ONE request as a single CSV snapshot.

    One file per request range — even if ranges overlap or only a gap was
    fetched, each scrape invocation gets its own self-contained file. This is the
    un-merged, un-deduped capture output, kept for troubleshooting and recovery.
    Returns the written path.
    """
    out = raw_capture_path(platform, account, start, end)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)
    return out


def save_raw_response(platform, account, start, end, payload, label, url=None):
    """Persist ONE raw API response as JSON for later re-analysis.

    Unlike save_raw_capture (which stores the *normalized* rows as CSV), this
    keeps the *original* platform payload verbatim — every field the API
    returned (费用, 积分, tokens, everything) — so we can re-parse it later
    without losing data. One file per request; `label` disambiguates requests
    that share the same (start, end) window (e.g. pagination pages).

    Layout: data/<platform>/<account>/raw/<start>_<end>_<label>.json
    """
    import re as _re
    from datetime import date as _date, datetime as _dt
    d = raw_capture_dir(platform, account)
    os.makedirs(d, exist_ok=True)

    def _fmt(x):
        if isinstance(x, _date):
            return x.strftime("%Y-%m-%d")
        if x is None:
            return "na"
        return str(x)

    s, e = _fmt(start), _fmt(end)
    lbl = _re.sub(r"[^A-Za-z0-9._-]+", "-", str(label)).strip("-") or "req"
    base = os.path.join(d, f"{s}_{e}_{lbl}.json")
    # Never overwrite an existing snapshot of the same request; bump a suffix.
    path = base
    if os.path.exists(path):
        i = 1
        while os.path.exists(os.path.join(d, f"{s}_{e}_{lbl}.{i}.json")):
            i += 1
        path = os.path.join(d, f"{s}_{e}_{lbl}.{i}.json")
    envelope = {
        "_meta": {
            "platform": (platform or "").lower(),
            "account": account or "",
            "captured_at": _dt.now().isoformat(timespec="seconds"),
            "start": s, "end": e, "label": lbl, "url": url or "",
        },
        "payload": payload,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)
    return path


def _dir_has_csv(d):
    """True if a directory contains at least one normalized .csv file."""
    try:
        return any(fn.endswith(".csv") for fn in os.listdir(d))
    except OSError:
        return False


def list_account_dirs(platform):
    """Names of named-account folders that hold normalized CSVs on disk.

    A named account is any sub-folder of data/<platform>/ that contains .csv
    files (one folder per account; the default/unnamed store is the platform
    folder itself, not listed here). Legacy accounts/<acc>/ folders are also
    recognised so old captures are not orphaned.
    """
    root = os.path.join(ROOT, "data", platform.lower())
    names = []
    if os.path.isdir(root):
        for n in sorted(os.listdir(root)):
            if n == "raw":
                # Per-request raw snapshots live here, not a data account.
                continue
            d = os.path.join(root, n)
            if os.path.isdir(d) and _dir_has_csv(d):
                names.append(n)
    legacy = os.path.join(root, "accounts")
    if os.path.isdir(legacy):
        for n in sorted(os.listdir(legacy)):
            d = os.path.join(legacy, n)
            if os.path.isdir(d) and _dir_has_csv(d) and n not in names:
                names.append(n)
    return names


def list_accounts(platform):
    """Account ids that already hold normalized CSVs.

    `None` stands for the default (unnamed) store and is only returned when it
    actually has data, so freshly created account folders are skipped.
    """
    out = [None] if list_data_files(platform) else []
    for name in list_account_dirs(platform):
        if list_data_files(platform, name):
            out.append(name)
    return out


# Filename patterns. Monthly storage is the primary layout; legacy range-based
# files (<start>_<end>.csv) are read for backwards compatibility and migrated
# into monthly files on the next save.
_RE_MONTH = re.compile(r"^(\d{4})-(\d{2})\.csv$")
_RE_RANGE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$")


def _month_path(account_dir, year, month):
    """Path of the monthly CSV for a (year, month) inside an account folder."""
    return os.path.join(account_dir, f"{year:04d}-{month:02d}.csv")


def list_data_files(platform, account=None):
    """Return list of (start_date, end_date, path) sorted by start date.

    Matches both monthly files (2026-08.csv -> 2026-08-01..2026-08-31) and
    legacy range files (2026-08-01_2026-08-31.csv).
    """
    d = platform_data_dir(platform, account)
    out = []
    if not os.path.isdir(d):
        return out
    for fn in os.listdir(d):
        m = _RE_MONTH.match(fn)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            s = date(y, mo, 1)
            e = date(y, mo, calendar.monthrange(y, mo)[1])
            out.append((s, e, os.path.join(d, fn)))
            continue
        m = _RE_RANGE.match(fn)
        if m:
            s, e = _d(m.group(1)), _d(m.group(2))
            if s and e:
                out.append((s, e, os.path.join(d, fn)))
    out.sort(key=lambda t: t[0])
    return out


def covered_dates(platform, account=None):
    """Union of all dates present in existing data files for the platform.

    Scoped to a single account: coverage from account A must never mask a gap
    in account B.
    """
    dates = set()
    for _s, _e, path in list_data_files(platform, account):
        for row in _read_rows(path):
            dd = _d(row.get("date", ""))
            if dd:
                dates.add(dd)
    return dates


def _read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return list(csv.DictReader(f))


def last_covered_date(platform, account=None):
    """Return the latest date that already has cached data, or None.

    Used to force a re-fetch of the previous pull's final day, because that
    day may have been captured mid-day (e.g. at noon) and thus is only
    partially complete. Re-fetching it and merging (deduped) backfills the
    missing tail without double-counting.
    """
    files = list_data_files(platform, account)
    if files:
        return max(e for _s, e, _p in files)
    dates = covered_dates(platform, account)
    return max(dates) if dates else None


def _canon_cost(r):
    """Return cost as a float, falling back to 0.0 for empty/invalid values."""
    try:
        return float(str(r.get("cost", 0) or 0))
    except Exception:
        return 0.0


def as_bool(v):
    """Parse the `free` flag, which is a real bool in memory but a string once
    it has been round-tripped through CSV.

    `bool("False")` is True, so comparing a freshly captured record against a
    row read from disk used to produce different dedup keys — every re-fetch
    appended another physical copy of the same row.
    """
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "t")
    return bool(v)


def _dedup_key(r):
    """Stable identity for a logical usage row.

    Design decision: the report's accuracy is about *cost*, and each platform
    returns one aggregated cost line per (date, model). The `prompt` is only a
    *preview* that the platform may reformat between pulls (e.g. add a
    `[client]` prefix), so it MUST NOT be part of the identity — otherwise a
    re-fetch would fail to dedup and double-count (the original bug).

    Identity = (account, date, model, cost-bucket, free, request_id).
    `cost-bucket` is rounded to 4 dp; same-day-same-model rows whose costs are
    within COST_EPS are treated as the same logical line at merge time (see
    `_cost_same`). The most-complete prompt is kept as a representative copy
    via `_more_complete`, but it does not affect identity.

    `account` is part of the identity so two accounts on the same platform can
    never collapse into one row.
    """
    return (
        str(r.get("account", "") or ""),
        r.get("date", ""),
        str(r.get("model", "") or ""),
        round(_canon_cost(r), 4),
        as_bool(r.get("free", False)),
        str(r.get("request_id", "") or ""),
    )


def _cost_same(a, b):
    """True if two costs represent the same logical amount (within epsilon)."""
    return abs(_canon_cost(a) - _canon_cost(b)) <= COST_EPS


def _row_id(r):
    """Stable, content-derived id for a row (persisted to CSV for idempotency).

    Based on the same identity as `_dedup_key` (account, date, model,
    cost-bucket, free) plus the platform, so identical logical rows always
    collide and genuinely different rows never do. Prompt is intentionally
    excluded (see _dedup_key).
    """
    h = hashlib.sha1()
    h.update(str(r.get("account", "") or "").encode("utf-8", "replace"))
    h.update(b"|")
    h.update(str(r.get("date", "")).encode("utf-8", "replace"))
    h.update(b"|")
    h.update(str(r.get("model", "")).encode("utf-8", "replace"))
    h.update(b"|")
    h.update(("%.4f" % round(_canon_cost(r), 4)).encode("utf-8"))
    h.update(b"|")
    h.update(("1" if as_bool(r.get("free", False)) else "0").encode("utf-8"))
    h.update(b"|")
    h.update(str(r.get("platform", "")).encode("utf-8"))
    h.update(b"|")
    rid = str(r.get("request_id", "") or "")
    h.update(rid.encode("utf-8"))
    return h.hexdigest()[:20]


def _more_complete(a, b):
    """True if row `a` is a better copy than `b` for the same logical row.

    Preference: non-empty credits(积分) > non-empty prompt > higher cost >
    longer prompt. Used when a day is re-fetched and we must choose one copy
    to keep — a re-fetch that finally captured 积分 must win over the older
    credit-less copy, otherwise 积分 never backfills.
    """
    def _has_credits(x):
        v = x.get("credits")
        return v not in (None, "", 0, 0.0) and str(v).strip() not in ("", "0", "0.0")
    if _has_credits(a) != _has_credits(b):
        return _has_credits(a)
    pa, pb = (a.get("prompt", "") or ""), (b.get("prompt", "") or "")
    if bool(pa) != bool(pb):
        return bool(pa)
    ca, cb = _canon_cost(a), _canon_cost(b)
    if abs(ca - cb) > COST_EPS:
        return ca > cb
    return len(pa) >= len(pb)


def _same_key(r, key):
    """True if row `r` matches a previously computed dedup `key`."""
    return _dedup_key(r) == key


def missing_ranges(req_start, req_end, platform, account=None, force_days=None):
    """Compute the date gaps that still need to be fetched.

    req_start / req_end : datetime.date
    account             : scope the check to this account (None = default)
    force_days           : optional iterable of datetime.date that must be
                           re-fetched even if already covered (e.g. the
                           previous pull's final day, which may be partial).
    Returns a list of (gap_start, gap_end) tuples, possibly empty.
    Gaps are maximal contiguous missing intervals within [req_start, req_end].
    """
    have = covered_dates(platform, account)
    force = set(force_days or [])
    missing = []
    cur_start = None
    day = req_start
    while day <= req_end:
        # A day is a gap if it's not covered OR if it's explicitly forced.
        if day not in have or day in force:
            if cur_start is None:
                cur_start = day
            cur_end = day
        else:
            if cur_start is not None:
                missing.append((cur_start, cur_end))
                cur_start = None
        day = day.fromordinal(day.toordinal() + 1)
    if cur_start is not None:
        missing.append((cur_start, cur_end))
    return missing


# ---- account metadata (coverage span + import/scrape provenance) ----------
def account_meta_path(platform, account):
    """Path of account.json (coverage + provenance metadata) for an account."""
    return os.path.join(platform_data_dir(platform, account), "account.json")


def read_account_meta(platform, account):
    """Load account.json metadata; returns {} when missing or unreadable."""
    p = account_meta_path(platform, account)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, dict):
                return m
        except Exception:
            pass
    return {}


def write_account_meta(platform, account, **updates):
    """Merge `updates` into account.json, preserving other keys, and write it."""
    m = read_account_meta(platform, account)
    if "name" not in m:
        m["name"] = safe_account(account) or ""
    m.update(updates)
    p = account_meta_path(platform, account)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    return m


def is_imported(platform, account):
    """True when an account's data came from an external/imported file
    (account.json `source == 'import'`). Such accounts CANNOT be pulled from the
    platform — report generation must skip scraping them and instead remind the
    user to import the external export."""
    return str(read_account_meta(platform, account).get("source", "")).lower() == "import"


def refresh_coverage_meta(platform, account=None):
    """Recompute the covered date span from real CSV data and persist it as
    `covered_range` in account.json. Returns (start, end) or None when empty."""
    dates = covered_dates(platform, account)
    if not dates:
        return None
    s, e = min(dates), max(dates)
    write_account_meta(platform, account,
                       covered_range=[s.strftime(DATE_FMT), e.strftime(DATE_FMT)])
    return s, e


def covered_range(platform, account=None, persist=True):
    """Return the (start_date, end_date) span of cached data for one account.

    Uses the persisted `covered_range` meta (O(1)) when present; otherwise scans
    the real CSV data (covered_dates) and — when `persist` — writes the span back
    into account.json so the next coverage check is O(1). Returns (None, None)
    when there is no data yet.
    """
    cr = read_account_meta(platform, account).get("covered_range")
    if isinstance(cr, (list, tuple)) and len(cr) == 2:
        s, e = _d(cr[0]), _d(cr[1])
        if s and e:
            return s, e
    if not persist:
        dates = covered_dates(platform, account)
        return (min(dates), max(dates)) if dates else (None, None)
    return refresh_coverage_meta(platform, account) or (None, None)


def load_consolidated(platform, req_start=None, req_end=None, account=None):
    """Return combined, deduped record dicts for one platform account
    (optionally clipped to a requested range).

    Rows read from disk get their `account` field backfilled, so CSVs written
    before multi-account support can be merged with newer ones safely.
    """
    rows = []
    for _s, _e, path in list_data_files(platform, account):
        rows.extend(_read_rows(path))
    # Backfill legacy rows: exports used to store `raw_request_id` while the
    # dedup identity uses `request_id`, so old rows had an empty id and would
    # collapse together. Copy it over so they merge correctly.
    for r in rows:
        if not str(r.get("request_id") or "") and str(r.get("raw_request_id") or ""):
            r["request_id"] = str(r.get("raw_request_id"))
    # Stable dedup by _dedup_key. We keep the most-complete copy on conflict
    # (non-empty prompt wins; otherwise higher cost wins) so re-fetching a
    # partially-captured day backfills the tail without double-counting.
    best = {}
    for r in rows:
        dd = _d(r.get("date", ""))
        if req_start and dd and dd < req_start:
            continue
        if req_end and dd and dd > req_end:
            continue
        key = _dedup_key(r)
        prev = best.get(key)
        if prev is None or _more_complete(r, prev):
            best[key] = r
    uniq = list(best.values())
    uniq.sort(key=lambda r: (r.get("date", ""), str(r.get("model", ""))))
    acc = safe_account(account)
    for r in uniq:
        if not str(r.get("account", "") or ""):
            r["account"] = acc
    return uniq


def _merge_rows(rows):
    """Dedup rows by _dedup_key, keeping the most-complete copy. Stable order."""
    best, order = {}, []
    for r in rows:
        k = _dedup_key(r)
        if k in best:
            if _more_complete(r, best[k]):
                best[k] = r
        else:
            order.append(k)
            best[k] = r
    return [best[k] for k in order]


def _median_positive(values):
    pos = [v for v in values if v > 0]
    if not pos:
        return 0.0
    pos.sort()
    n = len(pos)
    mid = n // 2
    return float(pos[mid] if n % 2 else (pos[mid - 1] + pos[mid]) / 2.0)


def _drop_legacy_unit_scale(existing, new_rows, platform):
    """When re-scraping a platform whose cost unit changed, legacy rows stored
    in the old unit have a wildly different cost magnitude and fail to dedup
    against the freshly scraped (new-unit) rows, double-counting every
    overlapping session. Drop only those old-unit rows; same-unit rows and
    zero-cost (free) rows are kept. The freshly scraped batch is authoritative.
    """
    med_ex = _median_positive([_canon_cost(r) for r in existing])
    med_nw = _median_positive([_canon_cost(r) for r in new_rows])
    if med_ex <= 0 or med_nw <= 0:
        return existing
    # Use a high bar so we only react to a true unit change (TRAE's RMB->积分
    # switch is ~40x). A modest same-unit median drift (e.g. a price change
    # mid-month) won't trip this and silently drop legitimate rows.
    if max(med_nw, med_ex) / min(med_nw, med_ex) < 20.0:
        return existing
    kept, dropped = [], 0
    for r in existing:
        c = _canon_cost(r)
        if c <= 0 or max(c, med_nw) / min(c, med_nw) < 5.0:
            kept.append(r)
        else:
            dropped += 1
    if dropped:
        print(f"[store] ⚠ {platform}: detected cost-unit change; dropped "
              f"{dropped} legacy row(s) in the old unit to avoid double-count.")
    return kept


def merge_and_save(platform, new_records, req_start=None, req_end=None,
                   account=None):
    """Merge freshly captured records into the store as MONTHLY CSV files.

    Storage layout (independent of the requested range):
        data/<platform>/<YYYY-MM>.csv            # default account
        data/<platform>/<account>/<YYYY-MM>.csv  # one folder per named account

    - Records are bucketed by their own calendar month, so a request spanning
      several months updates several monthly files (e.g. 8/15~9/10 touches
      2026-08.csv and 2026-09.csv); a partial request (8/10~8/20) simply merges
      into the existing 2026-08.csv.
    - Each monthly file is deduped against its previous contents, so re-fetches
      and overlapping requests never double-count.
    - Legacy <start>_<end>.csv files are folded into the monthly files and then
      removed, so storage converges to the monthly layout over time.
    Scoped to a single account; accounts never overwrite each other.
    Returns the path of the most recent monthly file that was written.
    """
    acc = safe_account(account)
    account_dir = platform_data_dir(platform, acc or None)
    for r in new_records:
        r["account"] = acc

    # Source rows = the new capture plus any legacy range files still on disk.
    legacy = [(s, e, p) for (s, e, p) in list_data_files(platform, acc or None)
              if _RE_RANGE.match(os.path.basename(p))]

    # Guard against out-of-window captures. Some platforms' usage APIs ignore
    # the requested date range and return a *recent* window instead (e.g. TRAE's
    # query_user_usage_group_by_session returned 9/2-9/3 when asked for
    # 8/1-8/29). Without this, those rows would be bucketed into the WRONG
    # month (polluting e.g. 2026-09.csv) and inflate covered_range(), leaving
    # the real gap silently unfilled. We only persist records inside the
    # requested window; legacy rows are already-validated data and kept as-is.
    if req_start and req_end:
        kept, dropped = [], []
        for r in new_records:
            dd = _d(r.get("date", ""))
            if dd and req_start <= dd <= req_end:
                kept.append(r)
            else:
                dropped.append(r)
        if dropped:
            sample = [str(r.get("date", "?")) for r in dropped[:5]]
            print(f"[store] ⚠ dropped {len(dropped)} out-of-range record(s) "
                  f"outside {req_start}~{req_end} (e.g. {', '.join(sample)}); "
                  f"not persisted.")
        new_records = kept

    all_rows = list(new_records)
    for _s, _e, p in legacy:
        all_rows.extend(_read_rows(p))

    # Bucket by calendar month.
    by_month = {}
    for r in all_rows:
        dd = _d(r.get("date", ""))
        if not dd:
            continue
        by_month.setdefault((dd.year, dd.month), []).append(r)

    written = []
    for (y, mo), rows in sorted(by_month.items()):
        path = _month_path(account_dir, y, mo)
        existing = _read_rows(path)
        # Guard: if a platform's cost *unit* changed between runs (e.g. TRAE
        # switched RMB -> 积分), legacy rows carry a different cost magnitude
        # and would survive dedup next to the new rows, silently
        # double-counting. Drop only the old-unit rows; keep new-unit rows.
        if existing and rows:
            existing = _drop_legacy_unit_scale(existing, rows, platform)
        merged = _merge_rows(existing + rows)
        for r in merged:
            r["account"] = acc
            r["row_id"] = _row_id(r)
        merged.sort(key=lambda r: (r.get("date", ""), str(r.get("model", ""))))
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(merged)
        added = max(len(merged) - len(existing), 0)
        print(f"[store] {path}: {len(merged)} total"
              + (f" (+{added} new)" if added else ""))
        written.append(path)

    # Migrate: drop legacy range files now that their months live in monthly files.
    for _s, _e, p in legacy:
        try:
            os.remove(p)
            print(f"[store] migrated legacy file -> {os.path.basename(p)}")
        except OSError:
            pass

    if not written:
        print(f"[store] no dated rows to persist for {platform}"
              + (f"/{acc}" if acc else ""))

    # Persist the covered date span so the next coverage check is O(1): the
    # `covered_range` meta in account.json backs the real-data scan used by
    # covered_range()/missing_ranges(). Written on every pull/import.
    try:
        refresh_coverage_meta(platform, acc or None)
    except Exception:
        pass

    return written[-1] if written else account_dir
