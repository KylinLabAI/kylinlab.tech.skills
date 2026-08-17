# -*- coding: utf-8 -*-
"""
scrape_usage.py — Browser-based usage capture via Playwright.

Qoder / TRAE / CodeBuddy IDE web portals do not offer a reliable CSV export;
their usage pages are SPA lists driven by backend JSON. This module opens the
page in a real browser (so login state / cookies / JWT are handled by Chromium),
listens to fetch responses, collects the raw usage records, and writes a normalized
CSV that analyze_usage.py can consume.

Per-platform API keyword hints (matched against the response URL):
  - Qoder (国内个人版) : "usages/big_model_credits/histories"
  - TRAE-CN           : "query_user_usage_group_by_session"
  - CodeBuddy web     : "usage"  (also works for the IDE web portal)
  - DeepSeek web      : "usage"  (or just download the official CSV instead)

Login:
  The script launches the SYSTEM Chrome (channel="chrome") in a persistent
  profile (~/Library/Caches/ai_usage_profile) so cookies survive restarts.
  If a usage URL redirects to a login page, you log in MANUALLY once in the
  opened browser window; the script then waits and re-opens the usage page.

Usage:
  python3 scrape_usage.py --platform Qoder --url https://<usage-page> \
      --out ai_usage_bill.csv [--login-url https://<login>] [--keyword usage-events] \
      [--scroll 20] [--headless False] [--profile-dir ~/Library/Caches/ai_usage_profile]

The captured records are normalized to columns:
  date, model, cost, free, prompt, platform
so they flow straight into analyze_usage.py.
"""
import argparse
import csv
import json
import os
import re
import time
from datetime import datetime, date, timezone, timedelta

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


PLATFORM_KEYWORDS = {
    # Qoder (国内个人版) — confirmed against live usage page
    "qoder": "usages/big_model_credits/histories",
    "trae": "query_user_usage_group_by_session",
    "trae-cn": "query_user_usage_group_by_session",
    "codebuddy": "usage",
    "deepseek": "usage/by_api_key",
}

# Qoder's API returns fields like: time / begin_at / model_category / cost / credits / kind / source / operation
QODER_FIELD_MAP = {
    "date": ("begin_at", "created_at", "timestamp", "time"),
    "model": ("model_category", "model", "model_name", "llm"),
    # prefer 'cost' (¥ reference fee) over 'credits' (internal credit units)
    "cost": ("cost", "original_cost", "reference_fee", "credits", "amount"),
    "kind": ("kind", "type", "level"),
    "operation": ("operation", "source"),
    "prompt": ("name", "prompt", "title"),
}
# TRAE returns user_usage_group_by_sessions: usage_time / model_name / cost_money_float / credits_float / user_input_preview
TRAE_FIELD_MAP = {
    "date": ("usage_time", "start_time", "time", "timestamp", "created_at"),
    "model": ("model_name", "model"),
    "cost": ("cost_money_float", "cost", "credits_float", "amount_float", "amount"),
    "prompt": ("user_input_preview", "session_title", "title", "prompt"),
}
# CodeBuddy get-user-request-usage: requestId / credit / model / client / requestTime / inputTrunc
CODEBUDDY_FIELD_MAP = {
    "date": ("requestTime", "time", "createdAt", "create_time", "date"),
    "model": ("model", "modelName"),
    "cost": ("credit", "cost", "amount", "fee"),
    "prompt": ("inputTrunc", "input", "prompt", "title"),
}
# DeepSeek usage/by_api_key returns daily×model aggregated buckets (amount=tokens,
# cost=fee CNY). We merge the two endpoints by (day, model).
DEEPSEEK_DATE_KEY = "time"      # bucket epoch seconds (per day)
DEEPSEEK_MODEL_KEY = "model"


def _first(d, keys, default=""):
    """Return the first non-empty value among keys in dict d."""
    for k in keys:
        if k in d and d[k] not in (None, "", 0):
            return d[k]
    return default


def _parse_dt(value):
    """Normalize a date value to ISO yyyy-mm-dd when possible."""
    if value in (None, ""):
        return ""
    s = str(value)
    # epoch seconds or milliseconds
    if s.isdigit() or (s.lstrip("-").isdigit()):
        try:
            n = int(s)
            if n > 10**12:        # ms
                n = n / 1000.0
            dt = datetime.fromtimestamp(n, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return s
    # already ISO-like?
    if "T" in s:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except Exception:
            return s[:10]
    # "2026-08-11 10:27:00" style
    if re.match(r"^\d{4}-\d{2}-\d{2}[ \d:]", s):
        return s[:10]
    # "2026/08/05 10:57:00" style
    m = re.match(r"^(\d{4})/(\d{2})/(\d{2})(?:[ T]\S*)?$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return s[:10]


def _coerce_record(rec, platform):
    """Map an arbitrary usage-event dict to the normalized schema."""
    p = platform.lower()
    if p == "qoder":
        dt_raw = _first(rec, QODER_FIELD_MAP["date"])
        model = _first(rec, QODER_FIELD_MAP["model"], "unknown")
        cost_raw = _first(rec, QODER_FIELD_MAP["cost"], 0)
        prompt = _first(rec, QODER_FIELD_MAP["prompt"])
        kind = _first(rec, QODER_FIELD_MAP["kind"])
        operation = _first(rec, QODER_FIELD_MAP["operation"])
        type_field = kind or operation
    elif p == "codebuddy":
        dt_raw = _first(rec, CODEBUDDY_FIELD_MAP["date"])
        model = _first(rec, CODEBUDDY_FIELD_MAP["model"], "unknown")
        cost_raw = _first(rec, CODEBUDDY_FIELD_MAP["cost"], 0)
        prompt = _first(rec, CODEBUDDY_FIELD_MAP["prompt"])
        type_field = _first(rec, ("client", "agentPurpose"))
        if type_field:
            prompt = f"[{type_field}] {prompt}" if prompt else f"[{type_field}]"
    elif p in ("trae", "trae-cn"):
        dt_raw = _first(rec, TRAE_FIELD_MAP["date"])
        model = _first(rec, TRAE_FIELD_MAP["model"], "unknown")
        cost_raw = _first(rec, TRAE_FIELD_MAP["cost"], 0)
        prompt = _first(rec, TRAE_FIELD_MAP["prompt"])
        type_field = ""
    else:
        dt_raw = (rec.get("date") or rec.get("time") or rec.get("createdAt")
                  or rec.get("created_at") or rec.get("startTime")
                  or rec.get("start_time") or rec.get("timestamp") or "")
        model = (rec.get("model") or rec.get("modelName") or rec.get("model_name")
                 or rec.get("llm") or "unknown")
        cost_raw = (rec.get("cost") or rec.get("amount") or rec.get("consumption")
                    or rec.get("price") or rec.get("tokens") or 0)
        prompt = (rec.get("prompt") or rec.get("userPrompt") or rec.get("title"))
        type_field = ""

    dt = _parse_dt(dt_raw)

    # numeric coercion
    try:
        cost = float(str(cost_raw).replace(",", ""))
    except Exception:
        cost = 0.0

    # free signal
    wallet = str(rec.get("walletType") or rec.get("wallet_type")
                 or rec.get("billingType") or "").lower()
    free = (wallet == "free") or (cost == 0.0) \
        or (p == "qoder" and str(type_field).lower() in ("refunded", "free", "升级", "upgrade"))
    # merge kind/operation into prompt for visibility
    tag = type_field or ""
    if tag and tag not in str(prompt):
        prompt = f"[{tag}] {prompt}" if prompt else f"[{tag}]"
    return {
        "date": dt, "model": str(model), "cost": cost,
        "free": bool(free), "prompt": str(prompt or ""), "platform": platform,
    }


def _extract_list(payload):
    """Pull the list of records out of arbitrary JSON wrappers."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    # 1-level keys
    for k in ("usageEvents", "records", "items", "list",
              "histories", "rows", "events",
              "user_usage_group_by_sessions"):
        v = payload.get(k)
        if isinstance(v, list):
            return v
    # data.* nests
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("list", "items", "records", "rows", "histories", "events"):
            v = data.get(k)
            if isinstance(v, list):
                return v
        # nested data.data
        d2 = data.get("data")
        if isinstance(d2, list):
            return d2
        if isinstance(d2, dict):
            for k in ("list", "items", "records", "rows"):
                v = d2.get(k)
                if isinstance(v, list):
                    return v
    return []


def _ingest_deepseek(url, payload, state):
    """Merge DeepSeek's daily×model aggregated buckets into normalized rows.

    There are two sibling endpoints:
      - .../by_api_key/amount  -> per-day token usage (REQUEST / *_TOKEN)
      - .../by_api_key/cost    -> per-day fee (CNY)
    We key by (day, model) so the two can be combined into one row each.
    """
    biz = (payload.get("data") or {}).get("biz_data") or {}
    outer = biz.get("data") or []
    is_cost = "cost" in url
    # cost endpoint: data = [ {currency, series:[...]} ]
    # amount endpoint: data = [ {api_key, model, buckets:[...]} ]
    series = []
    for item in outer:
        if isinstance(item, dict) and "series" in item and isinstance(item["series"], list):
            series.extend(item["series"])
        elif isinstance(item, dict) and "buckets" in item:
            series.append(item)
    # We keep a module-level-ish cache via state to merge amount+cost.
    merge = state.setdefault("_deepseek_rows", {})
    for entry in series:
        model = entry.get(DEEPSEEK_MODEL_KEY) or "unknown"
        for bucket in entry.get("buckets", []):
            day = bucket.get(DEEPSEEK_DATE_KEY)
            if day is None:
                continue
            key = (str(day), model)
            row = merge.setdefault(key, {
                "date": _parse_dt(str(day)),
                "model": model,
                "cost": 0.0,
                "free": False,
                "prompt": "",
                "platform": "DeepSeek",
                "requests": 0,
            })
            if is_cost:
                try:
                    row["cost"] = float(str(bucket.get("cost", 0)))
                except Exception:
                    pass
            else:
                usage = bucket.get("usage") or {}
                row["requests"] = int(usage.get("REQUEST", 0) or 0)
    # Rebuild collected from merge (dedup across amount + cost).
    state["collected"] = list(merge.values())
    n = len(state["collected"])
    print(f"[deepseek] merged -> {n} daily×model rows (cost={is_cost})")


def capture(platform, usage_url, login_url=None, keyword=None,
            scroll=20, headless=False, profile_dir=None,
            start=None, end=None):
    if sync_playwright is None:
        raise RuntimeError("playwright not installed. Run: pip install playwright")
    kw = keyword or PLATFORM_KEYWORDS.get(platform.lower(), "usage")
    profile_dir = profile_dir or os.path.join(
        os.path.expanduser("~/Library/Caches"), "ai_usage_profile")
    os.makedirs(profile_dir, exist_ok=True)
    state = {"collected": [], "start": start, "end": end}

    def on_response(resp):
        url = resp.url
        if kw.lower() in url.lower() and resp.status == 200:
            try:
                payload = resp.json()
            except Exception:
                return
            if platform.lower() == "deepseek":
                # DeepSeek returns daily×model aggregated buckets, not a
                # per-request list. Merge amount + cost responses.
                _ingest_deepseek(url, payload, state)
                return
            records = _extract_list(payload)
            if records:
                norm = [_coerce_record(r, platform) for r in records]
                state["collected"].extend(norm)
                print(f"[capture] +{len(norm)} ({len(state['collected'])} total) "
                      f"from {url[:80]}")

    with sync_playwright() as p:
        # Use the SYSTEM Chrome via channel="chrome" so we don't download Chromium.
        # Persistent profile keeps cookies across runs -> login once, reuse forever.
        context = p.chromium.launch_persistent_context(
            profile_dir, channel="chrome", headless=headless)
        page = context.new_page()
        page.on("response", on_response)

        def _wait_for_login_and_data():
            """Block until the user finishes manual login (incl. OTP) AND the
            usage API has returned data.

            We do NOT decide 'logged in' by URL (OTP/verify steps drop the
            'login' keyword and would falsely trigger closure). Instead we
            poll until state['collected'] is non-empty, which only happens
            once the real usage API responds with records.
            """
            print("\n[login] A Chrome window is open. Please log in MANUALLY "
                  "(including any SMS/OTP step).")
            print("        The script will automatically continue as soon as "
                  "usage data loads — no need to press anything.\n")
            # Prime the page so the SPA fires its first usage request.
            deadline = time.time() + 600  # up to 10 minutes
            while not state["collected"]:
                if time.time() > deadline:
                    print("[login] Timed out waiting for usage data.")
                    break
                # nudge: if still on a pure login page, keep waiting; otherwise
                # the SPA is likely fetching -> just wait.
                page.wait_for_timeout(2000)
            if state["collected"]:
                print(f"[login] Usage data detected ({len(state['collected'])} "
                      f"records so far). Continuing.")

        if login_url:
            page.goto(login_url)
            page.wait_for_load_state("domcontentloaded")
        page.goto(usage_url)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            print("[warn] load state timeout; continuing anyway.")
        # Wait for manual login + data; never closes browser prematurely.
        _wait_for_login_and_data()
        # give SPA a moment to fire the usage API after redirect
        page.wait_for_timeout(5000)
        for _ in range(scroll):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)

        # Platform-specific date-range + pagination: each platform's UI is
        # different, so we hook them in here. Both are safe no-ops if the
        # target elements aren't present.
        if platform.lower() == "qoder":
            _set_qoder_date_range(page, state, state.get("start"), state.get("end"))
        if platform.lower() in ("trae", "trae-cn"):
            _fetch_trae_all_pages(page, state, platform)

        context.close()

    records = state["collected"]
    warnings = _self_check(platform, records, start, end, kw)
    return records, warnings


def _self_check(platform, records, start, end, kw):
    """Post-capture sanity checks. Returns a list of human-readable warnings
    so callers can decide whether the result looks complete before storing it.

    We DO NOT silently accept a partial capture, because that produced wrong
    reports before. Instead we surface red flags loudly.
    """
    warnings = []
    if not records:
        warnings.append(
            f"未捕获到任何记录。可能原因：API 关键字 '{kw}' 不匹配、未登录、"
            f"或页面未触发 usage 请求。请检查 --keyword / 登录态。")
        return warnings

    # 1) date parse rate
    bad = [r for r in records if not r.get("date")]
    if bad:
        warnings.append(f"{len(bad)} 条记录缺少可解析的日期字段，可能被图表忽略。")

    # 2) requested range coverage
    if start and end:
        have = {r["date"] for r in records if r.get("date")}
        missing = []
        d = start
        while d <= end:
            if d not in have:
                missing.append(d)
            d = d.fromordinal(d.toordinal() + 1)
        if missing:
            # tolerate a few missing days (some platforms omit zero-usage days)
            if len(missing) > (end - start).days * 0.5:
                warnings.append(
                    f"请求范围 {start}~{end} 中缺失 {len(missing)} 天"
                    f"（{missing[0]}…{missing[-1]}），数据可能不完整。")
            else:
                warnings.append(
                    f"注意：范围内 {len(missing)} 天无记录（可能是零用量日）。")

    # 3) suspiciously small capture for a wide range
    if start and end and records:
        span_days = max((end - start).days, 1)
        per_day = len(records) / span_days
        if per_day < 1 and span_days >= 7:
            warnings.append(
                f"捕获密度偏低（{len(records)} 条 / {span_days} 天）。"
                f"若实际使用频繁，多半漏抓了分页，请重跑并确认滚动/翻页生效。")

    # 4) Qoder-specific: duplicate/over-merge guard
    if platform.lower() == "qoder":
        # Qoder returns one row per IDE session; flag if model field is empty
        empties = [r for r in records if not r.get("model")]
        if empties:
            warnings.append(f"{len(empties)} 条 Qoder 记录模型名为空。")
    return warnings


def _set_qoder_date_range(page, state, start=None, end=None):
    """Set Qoder's date range via the Ant Design dropdown + picker.

    Discovered DOM (Aug 2026):
      - Trigger: div.ant-space whose visible text contains a date span
        ("8月4日 ~ 8月11日") and "按起始时间".
      - Dropdown: Ant dropdown menu with
          * spans.ant-dropdown-menu-title-content → "今天"/"最近7天"/"最近30天"
          * a bare <div> → "自定义"
      - Custom panel: div.ant-picker-dropdown.analyticsDatePickerRangePickerOverlay
          * input[placeholder="开始日期"]
          * input[placeholder="结束日期"]
      - After any selection the dashboard re-fires the
        `usages/big_model_credits/histories` API call, which on_response
        picks up automatically.
    """
    try:
        # == 1) Open the dropdown by clicking the ant-space trigger ====
        opened = page.evaluate("""() => {
            const spaces = Array.from(document.querySelectorAll('.ant-space'));
            const trig = spaces.find(el => {
                const t = (el.innerText||'').trim();
                return /\\d{1,2}\\s*月\\s*\\d{1,2}\\s*日/.test(t) &&
                       t.includes('按起始时间');
            });
            if (!trig) return null;
            trig.click();
            return (trig.innerText||'').trim().slice(0,60);
        }""")
        print(f"[qoder-range] trigger: {opened}")
        page.wait_for_timeout(800)

        if start and end:
            # == 2a) Custom range: fetch API directly via page.evaluate ====
            # Qoder's API takes epoch-ms timestamps. The DOM-based date picker
            # approach doesn't reliably update the API params, so we call the
            # endpoint ourselves (same-origin, no CORS issues).
            start_ms, end_ms = _qoder_date_to_ms(start, end)
            print(f"[qoder-api] fetching {start}~{end} (ms: {start_ms}~{end_ms})")
            _fetch_qoder_api_pages(page, state, start_ms, end_ms)
            page.wait_for_timeout(1000)
            return

        # == 2b) Preset path: click "最近30天" in the dropdown ====
        picked = page.evaluate("""() => {
            const items = Array.from(
                document.querySelectorAll('.ant-dropdown-menu-title-content')
            );
            for (const it of items) {
                const t = (it.innerText||'').trim();
                if (t === '最近30天') { it.click(); return t; }
            }
            return null;
        }""")
        print(f"[qoder-range] picked preset: {picked}")
        if picked:
            page.wait_for_timeout(3000)
    except Exception as e:
        print(f"[qoder-range] failed: {e}")


def _qoder_date_to_ms(start, end):
    """Convert local dates to Beijing (UTC+8) epoch milliseconds for Qoder API."""
    from datetime import datetime as _dt
    tz_beijing = timezone(timedelta(hours=8))
    start_dt = _dt.combine(start, _dt.min.time(), tzinfo=tz_beijing)
    end_dt = _dt.combine(end + timedelta(days=1), _dt.min.time(), tzinfo=tz_beijing)
    start_ms = str(int(start_dt.timestamp() * 1000))
    end_ms = str(int(end_dt.timestamp() * 1000) - 1)
    return start_ms, end_ms


def _fetch_qoder_api_pages(page, state, start_ms, end_ms):
    """Call Qoder's histories API with custom date range and paginate.

    We fetch the JSON directly inside the browser and return it to Python.
    This is more reliable than relying on Playwright's on_response listener
    for fetch() calls issued from page.evaluate().

    Qoder API:
      GET .../usages/big_model_credits/histories
        ?page=<n>&page_size=100&start_time=<ms>&end_time=<ms>
         &order_by=begin_at&order=-1
    """
    base_url = "https://qoder.com.cn/api/v1/me/usages/big_model_credits/histories"
    PAGE_SIZE = 100

    page_num = 1
    total_fetched = 0
    while True:
        url = (f"{base_url}?page={page_num}&page_size={PAGE_SIZE}"
               f"&start_time={start_ms}&end_time={end_ms}"
               f"&order_by=begin_at&order=-1")
        print(f"[qoder-api] page {page_num}: fetching...")
        payload = page.evaluate("""async (url) => {
            try {
                const r = await fetch(url, {credentials: 'include'});
                if (!r.ok) return {__error: r.status};
                return await r.json();
            } catch (e) {
                return {__error: String(e)};
            }
        }""", url)

        if not payload:
            print(f"[qoder-api] page {page_num}: empty response, stopping.")
            break
        if isinstance(payload, dict) and payload.get("__error"):
            print(f"[qoder-api] page {page_num}: error {payload['__error']}, stopping.")
            break

        records = _extract_list(payload)
        if records:
            norm = [_coerce_record(r, "qoder") for r in records]
            state["collected"].extend(norm)
            total_fetched += len(norm)
            print(f"[qoder-api] page {page_num}: +{len(norm)} items "
                  f"(total fetched this run: {total_fetched}, "
                  f"state total: {len(state['collected'])})")
        else:
            print(f"[qoder-api] page {page_num}: no records in payload keys "
                  f"{list(payload.keys()) if isinstance(payload, dict) else 'list'}")

        # Pagination: stop if this page wasn't full.
        if len(records) < PAGE_SIZE:
            break
        page_num += 1

    print(f"[qoder-api] done: {total_fetched} records fetched across "
          f"{page_num} page(s); state now {len(state['collected'])} records")


def _fetch_trae_all_pages(page, state, platform):
    """Click TRAE dashboard's pagination buttons to load all pages.

    The dashboard's pagination is real <button> elements (paginationItem-*).
    Clicking them triggers the SPA's own (same-origin) fetch, which is captured
    by the on_response listener. We DO NOT call the POST API ourselves — CORS
    blocks it from a non-TRAE page context.
    """
    # 1) try to widen the time range to ~30 days via the dashboard UI.
    try:
        clicked = page.evaluate("""() => {
            const candidates = Array.from(document.querySelectorAll(
                'button, .range-picker li, .arco-radio-button, .arco-radio, [class*=range]'
            ));
            const btn = candidates.find(e => {
                const t = (e.innerText || '').trim();
                return /30\\s*(天|days)|近\\s*30|最近\\s*30/i.test(t);
            });
            if (btn) { btn.click(); return btn.innerText.trim(); }
            return null;
        }""")
        print(f"[trae-range] 30d button: {clicked}")
        if clicked:
            page.wait_for_timeout(2500)
    except Exception as e:
        print(f"[trae-range] failed: {e}")

    # 2) iterate pagination buttons in order.
    page_numbers = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('button'))
            .filter(b => /^\\d+$/.test((b.innerText||'').trim()))
            .map(b => (b.innerText||'').trim());
    }""")
    print(f"[trae-pages] found: {page_numbers}")
    if not page_numbers:
        print("[trae-pages] no pagination buttons found; keeping SPA-loaded data.")
        return

    # Always include page 1 (may already be loaded by SPA).
    for pno in page_numbers:
        # de-dupe: re-click page 1 is safe (idempotent); data is deduped by
        # (date, model) at the end.
        try:
            ok = page.evaluate(
                """(pno) => {
                    const btn = Array.from(document.querySelectorAll('button'))
                        .find(b => (b.innerText||'').trim() === pno);
                    if (btn) { btn.click(); return true; }
                    return false;
                }""",
                pno,
            )
            if not ok:
                continue
            page.wait_for_timeout(1500)  # let SPA fetch and render
            print(f"[trae-pages] clicked page {pno}; collected={len(state['collected'])}")
        except Exception as e:
            print(f"[trae-pages] click {pno} failed: {e}")

    # 3) deduplicate by (cost, model, prompt_prefix). Each session in TRAE is
    # distinct per page, but the same session could theoretically appear
    # twice across our clicks. We dedupe conservatively only on the most
    # identifying triple.
    seen, uniq = set(), []
    for r in state["collected"]:
        key = (r.get("model", ""),
               round(float(r.get("cost") or 0), 6),
               (r.get("prompt", "") or "")[:30])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    state["collected"] = uniq
    print(f"[trae-pages] final unique rows: {len(state['collected'])}")


def main():
    ap = argparse.ArgumentParser(description="Capture AI platform usage via Playwright.")
    ap.add_argument("--platform", required=True, help="qoder / trae / codebuddy / deepseek")
    ap.add_argument("--url", required=True, help="usage page URL")
    ap.add_argument("--login-url", default=None, help="login page URL (optional)")
    ap.add_argument("--keyword", default=None, help="override API URL keyword")
    ap.add_argument("--out", default=None, help="output CSV path (overrides data store)")
    ap.add_argument("--scroll", type=int, default=20, help="scroll iterations")
    ap.add_argument("--headless", action="store_true", help="run headless (risk of bot detection)")
    ap.add_argument("--profile-dir", default=None,
                    help="persistent Chrome profile dir (default: ~/Library/Caches/ai_usage_profile)")
    ap.add_argument("--start", default=None, help="requested range start yyyy-mm-dd (incremental)")
    ap.add_argument("--end", default=None, help="requested range end yyyy-mm-dd (incremental)")
    args = ap.parse_args()

    # Resolve requested date range (used for incremental storage + Qoder UI).
    req_start = req_end = None
    if args.start:
        req_start = datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end:
        req_end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if req_start and not req_end:
        req_end = date.today()
    if req_end and not req_start:
        req_start = req_end

    # Incremental logic: if no explicit --out, consult the data store to see
    # what is already captured, and only fetch the missing gaps.
    if not args.out and req_start and req_end:
        from data_store import missing_ranges, platform_data_dir
        gaps = missing_ranges(req_start, req_end, args.platform)
        if not gaps:
            print(f"[store] range {req_start}~{req_end} already fully cached; "
                  f"skip fetching. Use analyze_usage.py to build the report.")
            return
        print(f"[store] need to fetch gaps: {gaps}")
        # We fetch the union of gaps by setting the widest gap as the capture
        # window; Qoder/TRAE UIs accept a single range, so use the outer bounds.
        g0, g1 = gaps[0][0], gaps[-1][1]
        recs, warnings = capture(args.platform, args.url, args.login_url, args.keyword,
                                 args.scroll, args.headless, args.profile_dir,
                                 start=g0, end=g1)
    else:
        recs, warnings = capture(args.platform, args.url, args.login_url, args.keyword,
                                 args.scroll, args.headless, args.profile_dir,
                                 start=req_start, end=req_end)

    if warnings:
        print("\n" + "=" * 60)
        print("[capture: WARNINGS] 抓取结果可能不完整：")
        for w in warnings:
            print("  ⚠ " + w)
        print("=" * 60 + "\n")

    if not recs:
        print("[warn] no records captured. Check keyword / login / URL.")
        return

    if args.out:
        out = args.out
        fields = ["date", "model", "cost", "free", "prompt", "platform", "requests"]
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(recs)
        print(f"[done] wrote {len(recs)} records -> {out}")
    else:
        # Persist via the incremental data store (merge + dedupe).
        from data_store import merge_and_save, platform_data_dir
        if not req_start or not req_end:
            # No range given: default to the widest range seen in captured data.
            ds = [datetime.strptime(r["date"], "%Y-%m-%d").date()
                  for r in recs if r.get("date")]
            req_start = min(ds) if ds else date.today()
            req_end = max(ds) if ds else date.today()
        path = merge_and_save(args.platform, recs, req_start, req_end)
        print(f"[done] stored {len(recs)} records -> {path}")
        print(f"        data dir: {platform_data_dir(args.platform)}")
    print(f"        next: python3 analyze_usage.py --platform {args.platform} "
          f"--start {req_start} --end {req_end}")


if __name__ == "__main__":
    main()
