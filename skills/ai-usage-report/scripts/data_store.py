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
import os
import re
from datetime import date, datetime

ROOT = os.environ.get(
    "AI_USAGE_ROOT",
    os.path.join(os.path.expanduser("~/Desktop"), "ai-usage-report"),
)
FIELDS = ["date", "model", "cost", "free", "prompt", "platform", "requests"]
DATE_FMT = "%Y-%m-%d"


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


def missing_ranges(req_start, req_end, platform):
    """Compute the date gaps that still need to be fetched.

    req_start / req_end : datetime.date
    Returns a list of (gap_start, gap_end) tuples, possibly empty.
    Gaps are maximal contiguous missing intervals within [req_start, req_end].
    """
    have = covered_dates(platform)
    missing = []
    cur_start = None
    day = req_start
    while day <= req_end:
        if day not in have:
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
    # dedupe by (date, model, round(cost,4), prompt[:40])
    seen, uniq = set(), []
    for r in rows:
        dd = _d(r.get("date", ""))
        if req_start and dd and dd < req_start:
            continue
        if req_end and dd and dd > req_end:
            continue
        key = (r.get("date", ""), r.get("model", ""),
               round(float(str(r.get("cost", 0)) or 0), 4),
               (r.get("prompt", "") or "")[:40])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
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
    old_rows = _read_rows(path)
    # merge old + new, dedupe globally against the whole platform store too
    have_global = {
        (r.get("date", ""), r.get("model", ""),
         round(float(str(r.get("cost", 0)) or 0), 4),
         (r.get("prompt", "") or "")[:40])
        for r in load_consolidated(platform)
    }
    merged = list(old_rows)
    added = 0
    for r in new_records:
        key = (r.get("date", ""), r.get("model", ""),
               round(float(str(r.get("cost", 0)) or 0), 4),
               (r.get("prompt", "") or "")[:40])
        if key in have_global:
            continue
        have_global.add(key)
        merged.append(r)
        added += 1
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)
    print(f"[store] {path}: +{added} new, {len(merged)} total")
    return path
