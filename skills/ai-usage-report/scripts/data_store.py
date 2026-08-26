# -*- coding: utf-8 -*-
"""
data_store.py — Persistent, incremental storage for AI platform usage data.

Design goals
------------
- One platform = one folder under ai-usage-report/data/<platform>/
- Raw captures are saved as <start>_<end>.csv (date range in filenames) so we
  can tell at a glance what period each file covers.
- When a user asks for a date range we FIRST check what is already on disk.
  We only fetch the *missing* days, then merge overlapping files into a single
  consolidated dataset for reporting. This saves time and API calls.

Normalized record schema (same as the scraper / analyzer):
    date, model, cost, free, prompt, platform, requests

Public API
----------
    ROOT                   -> ~/Desktop/ai-usage-report (overridable via env)
    platform_data_dir(p)   -> .../data/<p>
    platform_report_dir(p) -> .../report/<p>
    list_data_files(p)     -> [ (start_date, end_date, path), ... ]
    covered_dates(p)       -> set(datetime.date) of all dates already captured
    missing_ranges(req_start, req_end, p)
                            -> list[(date,date)] of gaps to fetch
    merge_and_save(p, records, req_start, req_end)
                            -> writes/updates CSVs, returns consolidated path
    load_consolidated(p, req_start, req_end)
                            -> combined, deduped CSV rows for a requested range
"""
import csv
import hashlib
import os
import re
from datetime import date, datetime

ROOT = os.environ.get(
    "AI_USAGE_ROOT",
    os.path.join(os.path.expanduser("~/Desktop"), "ai-usage-report"),
)
FIELDS = ["date", "model", "cost", "free", "prompt", "platform", "requests",
          "request_id", "row_id"]
DATE_FMT = "%Y-%m-%d"
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


def platform_data_dir(platform):
    d = os.path.join(ROOT, "data", platform.lower())
    os.makedirs(d, exist_ok=True)
    return d


def platform_report_dir(platform):
    d = os.path.join(ROOT, "report", platform.lower())
    os.makedirs(d, exist_ok=True)
    return d


def _filename_for(start, end):
    return f"{start.strftime(DATE_FMT)}_{end.strftime(DATE_FMT)}.csv"


def list_data_files(platform):
    """Return list of (start_date, end_date, path) sorted by start date."""
    d = platform_data_dir(platform)
    out = []
    for fn in os.listdir(d):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$", fn)
        if not m:
            continue
        s, e = _d(m.group(1)), _d(m.group(2))
        if s and e:
            out.append((s, e, os.path.join(d, fn)))
    out.sort(key=lambda t: t[0])
    return out


def covered_dates(platform):
    """Union of all dates present in existing data files for the platform."""
    dates = set()
    for _s, _e, path in list_data_files(platform):
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


def last_covered_date(platform):
    """Return the latest date that already has cached data, or None.

    Used to force a re-fetch of the previous pull's final day, because that
    day may have been captured mid-day (e.g. at noon) and thus is only
    partially complete. Re-fetching it and merging (deduped) backfills the
    missing tail without double-counting.
    """
    files = list_data_files(platform)
    if files:
        return max(e for _s, e, _p in files)
    dates = covered_dates(platform)
    return max(dates) if dates else None


def _canon_cost(r):
    """Return cost as a float, falling back to 0.0 for empty/invalid values."""
    try:
        return float(str(r.get("cost", 0) or 0))
    except Exception:
        return 0.0


def _dedup_key(r):
    """Stable identity for a logical usage row.

    Design decision: the report's accuracy is about *cost*, and each platform
    returns one aggregated cost line per (date, model). The `prompt` is only a
    *preview* that the platform may reformat between pulls (e.g. add a
    `[client]` prefix), so it MUST NOT be part of the identity — otherwise a
    re-fetch would fail to dedup and double-count (the original bug).

    Identity = (date, model, cost-bucket, free). `cost-bucket` is rounded to 4
    dp; same-day-same-model rows whose costs are within COST_EPS are treated as
    the same logical line at merge time (see `_cost_same`). The most-complete
    prompt is kept as a representative copy via `_more_complete`, but it does
    not affect identity.
    """
    return (
        r.get("date", ""),
        str(r.get("model", "") or ""),
        round(_canon_cost(r), 4),
        bool(r.get("free", False)),
        str(r.get("request_id", "") or ""),
    )


def _cost_same(a, b):
    """True if two costs represent the same logical amount (within epsilon)."""
    return abs(_canon_cost(a) - _canon_cost(b)) <= COST_EPS


def _row_id(r):
    """Stable, content-derived id for a row (persisted to CSV for idempotency).

    Based on the same identity as `_dedup_key` (date, model, cost-bucket, free)
    plus the platform, so identical logical rows always collide and genuinely
    different rows never do. Prompt is intentionally excluded (see _dedup_key).
    """
    h = hashlib.sha1()
    h.update(str(r.get("date", "")).encode("utf-8", "replace"))
    h.update(b"|")
    h.update(str(r.get("model", "")).encode("utf-8", "replace"))
    h.update(b"|")
    h.update(("%.4f" % round(_canon_cost(r), 4)).encode("utf-8"))
    h.update(b"|")
    h.update(str(r.get("free", False)).encode("utf-8"))
    h.update(b"|")
    h.update(str(r.get("platform", "")).encode("utf-8"))
    h.update(b"|")
    rid = str(r.get("request_id", "") or "")
    h.update(rid.encode("utf-8"))
    return h.hexdigest()[:20]


def _more_complete(a, b):
    """True if row `a` is a better copy than `b` for the same logical row.

    Preference: non-empty prompt > higher cost > longer prompt. Used when a day
    is re-fetched and we must choose one copy to keep (backfill wins).
    """
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


def missing_ranges(req_start, req_end, platform, force_days=None):
    """Compute the date gaps that still need to be fetched.

    req_start / req_end : datetime.date
    force_days           : optional iterable of datetime.date that must be
                           re-fetched even if already covered (e.g. the
                           previous pull's final day, which may be partial).
    Returns a list of (gap_start, gap_end) tuples, possibly empty.
    Gaps are maximal contiguous missing intervals within [req_start, req_end].
    """
    have = covered_dates(platform)
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


def load_consolidated(platform, req_start=None, req_end=None):
    """Return combined, deduped record dicts for a platform (optionally clipped
    to a requested range)."""
    rows = []
    for _s, _e, path in list_data_files(platform):
        rows.extend(_read_rows(path))
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
    return uniq


def merge_and_save(platform, new_records, req_start, req_end):
    """Merge freshly captured `new_records` into the store and persist.

    Strategy:
    - Append new rows into the file whose range already covers [req_start,
      req_end] if one exists; otherwise create a new dated file.
    - Dedup against all existing rows to avoid double-counting overlaps.
    Returns the path of the file that was written/updated.
    """
    existing = list_data_files(platform)
    # pick a target file: prefer one that already spans the requested range
    target = None
    for s, e, path in existing:
        if s <= req_start and e >= req_end:
            target = (s, e, path)
            break
    if target is None:
        # create a new file named after the requested range
        path = os.path.join(platform_data_dir(platform),
                            _filename_for(req_start, req_end))
        target = (req_start, req_end, path)

    _s, _e, path = target
    # Build a global view of existing keys (with cost, for near-match checks).
    # A new row is dropped if it matches an existing row on the stable key AND
    # its cost is within epsilon of the existing cost (i.e. the same logical
    # row re-fetched). Near-cost matches that differ beyond epsilon are kept
    # (treated as genuinely distinct activity on the same day/model).
    existing_rows = load_consolidated(platform)
    have_keys = {_dedup_key(r) for r in existing_rows}
    have_cost = {_dedup_key(r): r for r in existing_rows}
    old_rows = _read_rows(path)
    merged = list(old_rows)
    added = 0
    for r in new_records:
        key = _dedup_key(r)
        if key in have_keys:
            prev = have_cost[key]
            if _cost_same(r, prev):
                # Same logical row re-fetched -> backfill only if the new copy
                # is more complete (then replace), otherwise skip to avoid dup.
                if _more_complete(r, prev):
                    merged = [m for m in merged if not _same_key(m, key)]
                    merged.append(r)
                continue
            # cost differs beyond epsilon -> distinct activity, keep both
        merged.append(r)
        have_keys.add(key)
        have_cost[key] = r
        added += 1
    # persist a stable row_id on every row so re-fetches stay idempotent
    for r in merged:
        r["row_id"] = _row_id(r)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)
    print(f"[store] {path}: +{added} new, {len(merged)} total")
    return path
