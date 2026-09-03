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
import sys
import time
from datetime import datetime, date, timezone, timedelta

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

import data_store  # persistent store root + helpers


PLATFORM_KEYWORDS = {
    # Qoder (国内个人版) — confirmed against live usage page
    "qoder": "usages/big_model_credits/histories",
    "trae": "query_user_usage_group_by_session",
    "trae-cn": "query_user_usage_group_by_session",
    "codebuddy": "usage",
    "deepseek": "usage/by_api_key",
}

# Profile-page URL + the label that precedes the account name on it. After login
# we open this page to learn the *real* account identity, which we then mask and
# use as the data-folder name (so history is keyed on a person, not a placeholder
# like auto_1). The cookie/login profile stays a placeholder (--account), only the
# on-disk data folder uses the masked real name.
PROFILE_URLS = {
    "deepseek": ("https://platform.deepseek.com/profile", "用户名"),
    "codebuddy": ("https://www.codebuddy.cn/profile/account-settings", "账号名称"),
    "qoder": ("https://qoder.com.cn/account/profile", "名称"),
    "trae": ("https://www.trae.cn/dashboard#account", "昵称"),
    "trae-cn": ("https://www.trae.cn/dashboard#account", "昵称"),
}


def mask_account_name(name):
    """Mask an account name for privacy before storing it on disk.

    Rules:
      - CJK names: keep first + last char, mask the middle ("王小二" -> "王x二",
        "王二" -> "王x").
      - Identifiers / phones: keep first 2 + last 2, mask the middle
        ("13800000001" -> "13xxxxxxx01", "yh-2026" -> "yhxxx26").
      - Too-short values keep the first char and mask the rest.
    """
    if not name:
        return name
    s = name.strip()
    if not s:
        return s
    # Email: mask the local part but keep the domain so accounts stay
    # distinguishable (kylinlab@example.com -> ky***b@example.com).
    em = re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s)
    if em:
        local = em.group(1)
        if len(local) <= 2:
            masked_local = local[0] + "*"
        elif len(local) <= 4:
            masked_local = local[0] + "*" * (len(local) - 1)
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{em.group(2)}"
    if re.search(r"[一-鿿]", s):  # contains CJK
        n = len(s)
        if n <= 1:
            return s
        if n == 2:
            return s[0] + "x"
        return s[0] + "x" * (n - 2) + s[-1]
    n = len(s)
    if n <= 1:
        return s
    if n <= 4:
        return s[0] + "x" * (n - 1)
    return s[:2] + "x" * (n - 4) + s[-2:]


def _first_token(s):
    """Take the first whitespace-delimited token, stripping stray quotes."""
    s = s.strip().strip("\"'\"`")
    toks = s.split()
    return toks[0] if toks else s


def _extract_profile_value(text, label):
    """Best-effort extraction of the account value shown next to `label`."""
    # "label: value" / "label：value" on one line
    m = re.search(re.escape(label) + r"\s*[:：]\s*([^\n\r]{1,80})", text)
    if m and m.group(1).strip():
        return _first_token(m.group(1))
    # "label value" (no colon)
    m = re.search(re.escape(label) + r"\s+([^\n\r]{1,80})", text)
    if m:
        val = m.group(1).strip()
        if val and not val.startswith((":", "：")):
            return _first_token(val)
    # any line containing the label; take the text after it
    for line in text.splitlines():
        if label in line:
            after = line.split(label, 1)[1].strip(" :：-")
            if after:
                return _first_token(after)
    # "label" on its own line, value on the following non-empty line (common SPA
    # layout: the label and the value live in separate divs). Look a few lines ahead.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if label in line:
            rem = line.split(label, 1)[1].strip(" :：-")
            if rem:
                return _first_token(rem)
            for j in range(i + 1, min(i + 4, len(lines))):
                nxt = lines[j].strip()
                if nxt and label not in nxt:
                    return _first_token(nxt)
    return None


PROFILE_API = {
    # platform -> (user-info endpoint, ordered JSON keys to try)
    "qoder": ("https://qoder.com.cn/api/v1/me", ("name", "username", "email")),
}


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _extract_email(text):
    """Return the first email address found in `text`, or None."""
    if not text:
        return None
    m = _EMAIL_RE.search(text)
    return m.group(0) if m else None


def _detect_account_name(page, platform):
    """Return the raw account name (string) from the platform's user-info API
    or profile/usage page, or None if it can't be read.

    Priority (most reliable first):
      1) user-info REST API (qoder's api/v1/me) — deterministic, no DOM timing.
      2) an email visible on the CURRENT logged-in page (the usage/account
         header almost always shows it; label-agnostic, robust across SPA
         layouts and languages).
      3) profile-page DOM parse keyed on a label (fallback only).
    """
    plat = platform.lower()
    # 1) User-info REST API (most reliable; no DOM-timing dependency).
    api = PROFILE_API.get(plat)
    if api:
        url, keys = api
        try:
            data = page.evaluate(
                "async (u) => { try { const r = await fetch(u, {credentials:'include'});"
                " const t = await r.text(); try { return JSON.parse(t); } catch(e){ return null; } }"
                " catch(e){ return null; } }", url)
            if isinstance(data, dict):
                for k in keys:
                    v = data.get(k)
                    if v and str(v).strip():
                        return str(v).strip()
        except Exception:
            pass
    # 2) Email visible on the CURRENT page (we are already logged in on the
    #    usage page; the account header usually shows the email).
    try:
        email = _extract_email(_page_text(page))
        if email:
            return email
    except Exception:
        pass
    # 3) Profile-page DOM parse (fallback): navigate, then try email, then label.
    info = PROFILE_URLS.get(plat)
    if not info:
        return None
    url, label = info
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        try:
            page.goto(url, timeout=20000)
        except Exception:
            return None
    try:
        page.wait_for_timeout(4000)
    except Exception:
        pass
    text = _page_text(page)
    email = _extract_email(text)
    if email:
        return email
    return _extract_profile_value(text, label)


def _is_placeholder(label):
    """True for cookie-profile placeholders we must NOT use as a data-folder
    name (they would silently mislabel history as e.g. 'account_1')."""
    if not label:
        return True
    s = label.strip()
    if s in ("", "default", "auto_1", "account_1"):
        return True
    if re.match(r"^(account_|auto_)\d+$", s):
        return True
    return False


def _maybe_confirm(suggested, fallback):
    """Return the label to use. When stdin is a TTY, let the user confirm / type
    the correct masked label; otherwise (non-interactive runs) just return the
    suggestion so the run never blocks. The chosen label is always printed for
    the user to verify afterwards."""
    val = suggested or fallback
    if not sys.stdin.isatty():
        return val
    try:
        ans = input(
            f"[account] 数据文件夹将使用账号标签: '{val}' "
            f"(直接回车确认，或输入正确的脱敏标签): ").strip()
        if ans:
            return ans
    except Exception:
        pass
    return val


def _resolve_data_label(page, platform, account, label=None):
    """Decide the on-disk data label.

    - If the user passed an explicit --label (non-placeholder), TRUST it; the
      cookie/login profile stays the --account placeholder. We still auto-detect
      purely for display.
    - Otherwise prefer the auto-detected (masked) real name; confirm interactively
      when possible; fall back to the --account placeholder only as a last resort.
    """
    if label and not _is_placeholder(label):
        raw = _detect_account_name(page, platform)
        if raw:
            print(f"[account] 使用指定的 --label '{label}'"
                  f"（自动识别到 '{mask_account_name(raw)}'，已忽略）。")
        else:
            print(f"[account] 使用指定的 --label '{label}'。")
        return label
    raw = _detect_account_name(page, platform)
    if raw:
        detected = mask_account_name(raw)
        print(f"[account] 自动识别到脱敏账号: {detected}")
        return _maybe_confirm(detected, account)
    print(f"[account] 未能自动识别账号名；回退到占位标签 '{account}'。"
          f" 可用 --label 指定明确标签。")
    return _maybe_confirm(account, account)

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
    rid = ""
    if p == "qoder":
        dt_raw = _first(rec, QODER_FIELD_MAP["date"])
        model = _first(rec, QODER_FIELD_MAP["model"], "unknown")
        cost_raw = _first(rec, QODER_FIELD_MAP["cost"], 0)
        prompt = _first(rec, QODER_FIELD_MAP["prompt"])
        kind = _first(rec, QODER_FIELD_MAP["kind"])
        operation = _first(rec, QODER_FIELD_MAP["operation"])
        type_field = kind or operation
        # Qoder records carry no stable per-request id; fingerprint from the
        # full timestamp so distinct same-day/same-model/same-cost requests stay
        # separate (otherwise store dedup collapses them into one).
        rid = str(rec.get("begin_at") or rec.get("time")
                  or rec.get("created_at") or rec.get("timestamp") or "")
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

    # unique request/session id, when the platform provides one (used to keep
    # genuinely distinct requests from being collapsed by the store dedup).
    rid = (rid or rec.get("requestId") or rec.get("request_id") or rec.get("id")
           or rec.get("sessionId") or rec.get("session_id") or "")

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
        # Filled in by capture() once the caller's --account is known.
        "account": "",
        "request_id": str(rid) if rid else "",
    }


def _safe_name(s):
    """Filesystem-safe fragment for profile dir names."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (s or "").strip()).strip("-")


def _default_profile_dir(platform, account=None):
    """One persistent Chrome profile per platform ACCOUNT.

    A single profile can only hold one logged-in session, so sharing it across
    accounts would force a logout/login on every switch.
    """
    base = os.path.join(os.path.expanduser("~/Library/Caches"), "ai_usage_profile")
    acc = _safe_name(account)
    return f"{base}_{platform.lower()}_{acc}" if acc else base


# ---------------------------------------------------------------------------
# Direct-API auto-download (cookie-auth via the persistent Chrome profile)
#
# Platforms that expose a usage/export REST API can be pulled directly with a
# date range: NO manual file download, and (once cookies are cached) NO manual
# login. The Qoder endpoint is known; CodeBuddy/DeepSeek endpoints are captured
# once via `--discover` and saved to <AI_USAGE_ROOT>/config/<p>_api.json (this
# lives under the data root, outside the repo, so it is never committed).
# ---------------------------------------------------------------------------

def _api_spec_path(platform):
    # Discovered specs are transient overrides, not user data — keep them in the
    # system temp dir, NOT under AI_USAGE_ROOT (the user-facing data store).
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "ai-usage-report", "specs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{platform.lower()}_api.json")


def load_api_spec(platform):
    """Live, user-captured spec wins; else fall back to committed template."""
    live = _api_spec_path(platform)
    if os.path.exists(live):
        try:
            with open(live, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    tmpl = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "configs", "api_templates.json")
    try:
        with open(tmpl, "r", encoding="utf-8") as f:
            return json.load(f).get(platform.lower())
    except Exception:
        return None


def save_api_spec(platform, spec):
    d = os.path.dirname(_api_spec_path(platform))
    os.makedirs(d, exist_ok=True)
    with open(_api_spec_path(platform), "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
    print(f"[discover] saved API spec -> {_api_spec_path(platform)}")


def _build_date_tokens(start, end, fmt, tz_offset_hours=0):
    """Return (start_token, end_token) strings for the given date_format."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    if fmt == "ms":
        tz = _tz(_td(hours=tz_offset_hours))
        s = _dt.combine(start, _dt.min.time(), tzinfo=tz)
        e = _dt.combine(end + _td(days=1), _dt.min.time(), tzinfo=tz)
        return str(int(s.timestamp() * 1000)), str(int(e.timestamp() * 1000) - 1)
    if fmt == "datetime":
        # "yyyy-MM-dd HH:mm:ss" in the given timezone (default Beijing).
        tz = _tz(_td(hours=tz_offset_hours))
        s = _dt.combine(start, _dt.min.time(), tzinfo=tz)
        e = _dt.combine(end, _dt.max.time(), tzinfo=tz)
        return s.strftime("%Y-%m-%d %H:%M:%S"), e.strftime("%Y-%m-%d %H:%M:%S")
    if fmt == "epoch":
        # epoch SECONDS (UTC). DeepSeek's by_api_key API uses this.
        s = _dt.combine(start, _dt.min.time(), tzinfo=_tz.utc)
        e = _dt.combine(end, _dt.max.time(), tzinfo=_tz.utc)
        return str(int(s.timestamp())), str(int(e.timestamp()))
    if fmt == "iso":
        return start.isoformat(), end.isoformat()
    # default: yyyy-mm-dd
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _month_windows(start, end):
    """DeepSeek's by_api_key API only accepts month-aligned ranges, so split a
    requested range into one window per calendar month and fetch each."""
    import calendar
    out = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        last = calendar.monthrange(cur.year, cur.month)[1]
        out.append((cur, date(cur.year, cur.month, last)))
        cur = (date(cur.year + 1, 1, 1) if cur.month == 12
               else date(cur.year, cur.month + 1, 1))
    return out


def _origin_of(url):
    """Return the scheme://netloc origin of a URL."""
    import urllib.parse as _up
    return _up.urlunparse(_up.urlparse(url)._replace(path="", query="",
                                                    fragment=""))


def _fetch_json_via_page(page, url, headers=None):
    """Call the API from inside the page so the persistent profile's cookies
    (cookie auth) are sent automatically. Returns parsed JSON, or a dict with
    `__error`/`__text` on failure."""
    return page.evaluate("""async (args) => {
        const {url, headers} = args;
        try {
            const r = await fetch(url, {credentials: 'include', headers: headers || {}});
            if (!r.ok) return {__error: r.status};
            const ct = r.headers.get('content-type') || '';
            if (ct.indexOf('application/json') !== -1) return await r.json();
            return {__text: await r.text()};
        } catch (e) { return {__error: String(e)}; }
    }""", {"url": url, "headers": headers or {}})


def _capture_via_api(platform, page, start, end):
    """Pull usage via a configured REST endpoint with a date range.

    Returns a list of normalized records, or None if no spec / no url is
    configured (caller should fall back to the UI-intercept flow).
    """
    spec = load_api_spec(platform)
    if not spec or not spec.get("url"):
        return None
    print(f"[api] _capture_via_api start={start!r} end={end!r}")
    if platform.lower() == "deepseek":
        return _capture_deepseek_via_api(page, start, end, spec)
    fmt = spec.get("date_format", "date")
    tz = spec.get("tz_offset_hours", 0)
    s_tok, e_tok = _build_date_tokens(start, end, fmt, tz)
    print(f"[api] _build_date_tokens returned s_tok={s_tok} e_tok={e_tok} "
          f"(start={start!r} end={end!r} fmt={fmt} tz={tz})")
    pg = spec.get("pagination", {}) or {}
    page_param = pg.get("page_param", "page")
    size = pg.get("size", 100)
    stop_less = pg.get("stop_when_less_than_size", True)
    base = spec["url"]
    tmpl_body = spec.get("body")
    body_str_tmpl = (json.dumps(tmpl_body, ensure_ascii=False)
                     if isinstance(tmpl_body, dict) else (tmpl_body or ""))
    has_page_token = ("{page}" in base) or ("{page}" in body_str_tmpl)
    headers = spec.get("headers", {})
    method = (spec.get("method") or "GET").upper()

    collected = []
    pno = 1
    while True:
        url = (base.replace("{page}", str(pno))
                   .replace("{start}", s_tok)
                   .replace("{end}", e_tok))
        if pno == 1:
            print(f"[api] built url: {url}\n[api] tokens: start={s_tok} end={e_tok} fmt={fmt}")
        if method == "POST":
            # Substitute placeholders at the DICT level so numeric fields
            # (e.g. pageNum) stay integers instead of becoming strings.
            if isinstance(tmpl_body, dict):
                body = json.loads(json.dumps(tmpl_body))  # deep copy
                for k in list(body.keys()):
                    v = body[k]
                    if v == "{start}":
                        body[k] = s_tok
                    elif v == "{end}":
                        body[k] = e_tok
                    elif v == "{page}":
                        body[k] = pno
            else:
                body = {}
            if pno == 1:
                print(f"[api] POST {url}\n[api] body: {body}")
            try:
                payload = page.evaluate("""async (args) => {
                    const {url, headers, body} = args;
                    try {
                        const r = await fetch(url, {method:'POST', credentials:'include',
                            headers: Object.assign({'content-type':'application/json'}, headers||{}),
                            body: JSON.stringify(body)});
                        if (!r.ok) return {__error: r.status};
                        return await r.json();
                    } catch (e) { return {__error: String(e)}; }
                }""", {"url": url, "headers": headers, "body": body})
            except Exception as e:
                print(f"[api] evaluate error: {e!r}")
                payload = {"__error": str(e)}
        else:
            try:
                payload = _fetch_json_via_page(page, url, headers)
            except Exception as e:
                print(f"[api] evaluate error: {e!r}")
                payload = {"__error": str(e)}

        if not payload:
            break
        if isinstance(payload, dict) and payload.get("__error"):
            print(f"[api] {platform} page {pno}: error {payload['__error']}")
            break
        if isinstance(payload, dict) and payload.get("__text"):
            # Non-JSON (likely a login redirect / HTML) -> session expired.
            print(f"[api] {platform} page {pno}: non-JSON response "
                  f"({payload['__text'][:50]!r}); session may be expired.")
            break

        records = _extract_list(payload)
        if pno == 1 and not records:
            _d = payload.get("data") if isinstance(payload, dict) else None
            _dinfo = (f"type={type(_d).__name__} "
                      f"keys={list(_d.keys())[:12] if isinstance(_d, dict) else 'n/a'} "
                      f"sample={str(_d)[:300]}")
            print(f"[api] {platform} page 1: no list; payload keys="
                  f"{list(payload.keys())[:12]} data={_dinfo}")
        if pno == 1 and records:
            print(f"[api] sample record fields: {list(records[0].keys())}")
        if records:
            norm = [_coerce_record(r, platform) for r in records]
            collected.extend(norm)
            print(f"[api] {platform} page {pno}: +{len(norm)} (total {len(collected)})")
        if not has_page_token:
            break
        if stop_less and (not records or len(records) < size):
            break
        pno += 1

    if not collected:
        return None
    return collected


def _capture_deepseek_via_api(page, start, end, spec):
    """DeepSeek-only fetch: month-aligned windows, merging the amount and cost
    sibling endpoints, then filtering rows back to the requested [start, end]."""
    print(f"[api] deepseek windows={_month_windows(start, end)} start={start!r} end={end!r}")
    base = spec["url"]              # .../by_api_key/amount?start=..&end=..&tz=..
    cost_base = base.replace("/amount", "/cost")
    headers = spec.get("headers", {})
    fmt = spec.get("date_format", "epoch")
    tz = spec.get("tz_offset_hours", 0)
    state = {"_deepseek_rows": {}}

    for (w_start, w_end) in _month_windows(start, end):
        s_tok, e_tok = _build_date_tokens(w_start, w_end, fmt, tz)
        for b in (base, cost_base):
            url = b.replace("{start}", s_tok).replace("{end}", e_tok)
            kind = "cost" if "cost" in url else "amount"
            if w_start == start and w_end == end:
                print(f"[api] deepseek {kind} url: {url}")
            try:
                payload = _fetch_json_via_page(page, url, headers)
            except Exception as e:
                print(f"[api] deepseek {kind} evaluate error: {e!r}")
                payload = {"__error": str(e)}
            if isinstance(payload, dict) and payload.get("__error"):
                print(f"[api] deepseek {kind}: error {payload['__error']}")
                continue
            if isinstance(payload, dict):
                biz_data = (payload.get("data") or {}).get("biz_data")
                if isinstance(biz_data, dict):
                    print(f"[api] deepseek {kind}: biz_code="
                          f"{biz_data.get('biz_code')} biz_msg={biz_data.get('biz_msg')!r}")
                    if kind == "amount":
                        dd = biz_data.get("data")
                        sample = (dd[0] if isinstance(dd, list) and dd else dd)
                        print(f"[api] deepseek amount data type={type(dd).__name__} "
                              f"sample={str(sample)[:500]}")
            _ingest_deepseek(url, payload, state)

    rows = list(state["_deepseek_rows"].values())
    rows = [r for r in rows
            if isinstance(r.get("date"), datetime) and start <= r["date"].date() <= end]
    print(f"[api] deepseek: {len(rows)} rows after month fetch + range filter")
    if not rows:
        return None
    return rows


def discover(platform, usage_url, login_url=None, keyword=None,
             headless=False, profile_dir=None, account=None):
    """One-time helper: open the platform, let the user log in and load the
    usage/export page, then capture the underlying REST request so it can be
    replayed directly later (no manual file download)."""
    if sync_playwright is None:
        raise RuntimeError("playwright not installed. Run: pip install playwright")
    kw = keyword or PLATFORM_KEYWORDS.get(platform.lower(), "usage")
    profile_dir = profile_dir or _default_profile_dir(platform, account)
    os.makedirs(profile_dir, exist_ok=True)

    candidates = []   # real data-API candidates (JSON XHR/fetch, not tracking)
    raw = []           # every request, for debugging when nothing is found

    TRACK = ("google", "doubleclick", "ping.", "tencent.com/traffic",
             "googletagmanager", "adservice", "hotjar", "segment", "m.qq.com",
             "beacon.qq.com")

    # Endpoints that are clearly NOT the usage-data API (login / auth / analytics).
    NON_DATA = ("login", "auth", "risk", "gray", "feature", "event",
                "track", "report", "/plugin", "oneid", "gray-decision")
    DATA_HINT = ("usage", "bill", "cost", "export", "stat", "consume",
                 "credit", "quota", "point", "history", "record", "list")
    # Field names that mark a REAL usage-records response (schema-agnostic).
    USAGE_FIELDS = ("model", "credit", "cost", "usage", "requesttime",
                    "requestid", "amount", "points", "consume", "records",
                    "histories", "sessions", "prompt", "tokencount", "fee",
                    "modelname", "creditcost")

    def _body_score(body):
        if body is None:
            return 0
        try:
            blob = json.dumps(body, ensure_ascii=False).lower()
        except Exception:
            return 0
        return sum(1 for h in USAGE_FIELDS if h in blob)

    def _data_cands():
        """Candidates that are not login/auth/tracking AND look like a usage
        records API (their response body contains usage-schema fields)."""
        out = []
        for c in candidates:
            u = c["url"].lower()
            if any(nd in u for nd in NON_DATA):
                continue
            if _body_score(c.get("body")) <= 0:
                continue
            out.append(c)
        return out

    def _is_track(url):
        return any(h in url for h in TRACK)

    def on_response(resp):
        url = resp.url
        raw.append((resp.request.method, url))
        # Real data APIs are almost always XHR/fetch returning JSON.
        if resp.request.resource_type not in ("xhr", "fetch"):
            return
        ct = resp.headers.get("content-type", "")
        if "application/json" not in ct or resp.status != 200:
            return
        if _is_track(url):
            return
        try:
            body = resp.json()
        except Exception:
            body = None
        try:
            req_body = resp.request.post_data
        except Exception:
            req_body = None
        try:
            req_headers = dict(resp.request.headers)
        except Exception:
            req_headers = {}
        candidates.append({"method": resp.request.method, "url": url,
                           "body": body, "req_body": req_body,
                           "req_headers": req_headers,
                           "score": _body_score(body)})

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir, channel="chrome", headless=headless)
        page = context.new_page()
        page.on("response", on_response)
        if login_url:
            page.goto(login_url)
            page.wait_for_load_state("domcontentloaded")
        if usage_url:
            try:
                page.goto(usage_url)
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"[discover] could not open {usage_url}: {e}")
                print("           open the correct usage page manually in the "
                      "browser window, then the data API will be captured.")
        print("\n[discover] Opened Chrome on the usage page.")
        print("        Log in MANUALLY (incl. OTP) if prompted. Once the usage "
              "table/export loads, the data API fires and is captured.\n")
        # Stay open until a REAL data API appears (login/auth/analytics no longer
        # count), or until the 10-minute timeout.
        deadline = time.time() + 600
        nudged = False
        while not _data_cands() and time.time() < deadline:
            page.wait_for_timeout(2000)
            # Nudge: after ~25s, if logged in but the table hasn't loaded,
            # re-open the usage page to trigger the API.
            if not nudged and time.time() - (deadline - 600) > 25 and usage_url:
                nudged = True
                try:
                    page.goto(usage_url)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
        page.wait_for_timeout(4000)  # catch pagination / range requests too
        context.close()

    if not candidates:
        print("[discover] no JSON API response captured (likely not logged in, "
              "or the data loads via a non-JSON channel).")
        same_host = [u for m, u in raw if platform.lower() in u or "codebuddy" in u]
        if same_host:
            print("[discover] requests seen on the platform host:")
            for u in same_host[:15]:
                print("           " + u[:140])
        print("[discover] re-run after logging in and letting the table load.")
        return

    data = _data_cands()
    if not data:
        print("[discover] only login/auth/analytics JSON endpoints were seen — "
              "the usage data API never fired.")
        print("           Log in fully and let the usage table load, then re-run.")
        print("[discover] JSON endpoints seen (for reference):")
        for c in candidates:
            print("           " + c["url"][:140])
        return

    print(f"\n[discover] captured {len(data)} usage-records API candidate(s):")
    for i, c in enumerate(data):
        print(f"  {i + 1}. [{c['method']}] score={c['score']} {c['url'][:130]}")

    # Prefer the candidate whose response body best matches the usage schema;
    # if tied, prefer the explicitly "request-usage" / "usage" endpoint.
    best_score = max(c["score"] for c in data)
    top = [c for c in data if c["score"] == best_score]
    pick = next((c for c in top
                 if re.search(r"request-usage|usage", c["url"], re.I)), top[0])
    print("[discover] picked:", pick["url"])
    print("[discover] picked request body (raw):", pick.get("req_body"))
    # Replay the exact request headers (minus cookie, which credentials:'include'
    # sends) so the API accepts our call just like the page's own fetch.
    import urllib.parse as _up
    parsed = _up.urlparse(pick["url"])
    q = _up.parse_qs(parsed.query)
    cleaned = {}
    dfmt = "date"
    for k, vals in q.items():
        v = vals[0] if vals else ""
        if re.search(r"(time|date|start|end|from|to)", k, re.I) and re.search(r"\d{4}", v):
            # epoch seconds (10 digits) or milliseconds (12+ digits)?
            if re.search(r"^\d{12,}$", v):
                dfmt = "ms"
            elif re.search(r"^\d{10}$", v):
                dfmt = "epoch"
            v = "{start}" if re.search(r"start|from", k, re.I) else "{end}"
        cleaned[k] = v
    new_q = "&".join(f"{k}={v}" for k, v in cleaned.items())
    stub_url = _up.urlunparse(parsed._replace(query=new_q))

    spec = {
        "note": f"Auto-discovered for {platform}. Replace date values with "
                f"{{start}}/{{end}} and add {{page}} if the API paginates. "
                f"date_format is guessed as 'date' (use 'ms'/'epoch' for unix).",
        "url": stub_url,
        "method": pick["method"],
        "date_format": dfmt,
        "pagination": {"page_param": "page", "size": 100,
                       "stop_when_less_than_size": True},
        "auth": "cookie",
    }
    # Replay the exact request headers (minus cookie, sent via credentials) so
    # the API accepts our call like the page's own fetch does.
    rh = pick.get("req_headers") or {}
    spec["headers"] = {k: v for k, v in rh.items()
                       if k.lower() not in ("cookie", "content-length")}
    # If it was a POST, keep the REQUEST body as a template and blank any
    # date-like / page fields so the caller can substitute {start}/{end}/{page}.
    if pick["method"] == "POST" and pick.get("req_body"):
        raw_b = pick["req_body"]
        try:
            bd = json.loads(raw_b) if isinstance(raw_b, str) else raw_b
        except Exception:
            bd = raw_b
        if isinstance(bd, dict):
            for k, v in list(bd.items()):
                kl = k.lower()
                if isinstance(v, (str, int)) and re.search(r"(time|date|start|end|from|to)", kl):
                    sv = str(v)
                    if re.search(r"\d{4}", sv):
                        # "yyyy-MM-dd HH:mm:ss" -> datetime (Beijing) format
                        if re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", sv):
                            spec["date_format"] = "datetime"
                            spec["tz_offset_hours"] = 8
                        # epoch milliseconds -> ms date_format
                        elif re.search(r"^\d{12,}$", sv):
                            spec["date_format"] = "ms"
                        bd[k] = "{start}" if re.search(r"start|from", kl) else "{end}"
                elif re.search(r"pagesize|perpage|limit|size", kl):
                    # Keep the original page-size value; align stop-detection.
                    try:
                        spec["pagination"]["size"] = int(v)
                    except Exception:
                        pass
                elif re.search(r"page", kl):
                    bd[k] = "{page}"
            spec["body"] = bd

    save_api_spec(platform, spec)
    print(f"[discover] saved stub spec (platform={platform}). Edit if needed:")
    print(f"           {_api_spec_path(platform)}")
    print("[discover] re-run capture normally; it will call the API directly.")


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
    biz = (payload.get("data") or {}).get("biz_data")
    if isinstance(biz, list):
        outer = biz
    elif isinstance(biz, dict):
        outer = biz.get("data") or []
    else:
        outer = []
    is_cost = "cost" in url
    # cost endpoint: data = [ {currency, series:[...]} ]
    # amount endpoint: data = [ {api_key, model, buckets:[...]} ]
    series = []
    if not outer:
        print(f"[ingest] is_cost={is_cost} outer_type={type(outer).__name__} "
              f"sample={str(outer)[:300]}")
    else:
        if not state.get("_dumped_outer"):
            print(f"[ingest] is_cost={is_cost} outer_type={type(outer).__name__} "
                  f"item0_type={type(outer[0]).__name__ if outer else 'n/a'} "
                  f"outer_sample={str(outer)[:400]}")
            state["_dumped_outer"] = True
    for item in outer:
        if isinstance(item, dict) and "series" not in item and "buckets" not in item:
            print(f"[ingest] unmatched item keys={list(item.keys())} "
                  f"sample={str(item)[:300]}")
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
                if not state.get("_dumped"):
                    print(f"[ingest] amount bucket keys={list(bucket.keys())} "
                          f"entry_keys={list(entry.keys())} sample={str(bucket)[:200]}")
                    state["_dumped"] = True
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
            start=None, end=None, account=None, label=None):
    if sync_playwright is None:
        raise RuntimeError("playwright not installed. Run: pip install playwright")
    kw = keyword or PLATFORM_KEYWORDS.get(platform.lower(), "usage")
    profile_dir = profile_dir or _default_profile_dir(platform, account)
    os.makedirs(profile_dir, exist_ok=True)
    state = {"collected": [], "start": start, "end": end}
    _fresh_auth = {"value": None}

    def on_request(req):
        # Capture a fresh session token the page sends, so our own API call
        # (which reuses the saved spec) stays authorized after token refresh.
        h = req.headers.get("authorization")
        if h:
            _fresh_auth["value"] = h
        if "by_api_key" in req.url:
            print(f"[debug] page request -> {req.url}")
            print(f"[debug]   auth present: {bool(h)}")

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
            if not records and isinstance(payload, dict):
                print(f"[api] {platform}: JSON but no list extracted; "
                      f"keys={list(payload.keys())[:8]} sample={str(payload)[:160]}")
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
        page.on("request", on_request)

        # Auto-download via direct API (cookie auth from the persistent
        # profile). Skips the UI entirely when the session is still valid;
        # falls back to the manual-login UI flow when cookies are missing /
        # expired (e.g. first run).
        if platform.lower() in ("codebuddy", "deepseek"):
            spec = load_api_spec(platform)
            if spec and spec.get("url") and start and end:
                # Land on a SAME-ORIGIN page first, otherwise page.evaluate's
                # fetch() is cross-origin and Chromium blocks it (CORS).
                _land = usage_url or _origin_of(spec["url"])
                if _land:
                    try:
                        page.goto(_land)
                        page.wait_for_load_state("domcontentloaded", timeout=30000)
                    except Exception:
                        pass
                    # Give the SPA a moment to fire its own API (which carries a
                    # fresh session token), then reuse that token for our call.
                    page.wait_for_timeout(2500)
                    print(f"[api] fresh auth captured: "
                          f"{'yes' if _fresh_auth['value'] else 'no'}")
                    if _fresh_auth["value"]:
                        spec.setdefault("headers", {})["authorization"] = \
                            _fresh_auth["value"]
                api_records = _capture_via_api(platform, page, start, end)
                if api_records:
                    print(f"[api] auto-downloaded {len(api_records)} records "
                          f"via API (no manual login / download).")
                    # Learn the real (masked) account name from the profile page
                    # while we're still on a same-origin, logged-in page.
                    data_label = _resolve_data_label(page, platform, account, label)
                    for r in api_records:
                        r["account"] = data_label
                    context.close()
                    warnings = _self_check(
                        platform, api_records, start, end,
                        keyword or PLATFORM_KEYWORDS.get(platform.lower(), "usage"))
                    return api_records, warnings, data_label
                print("[api] no data via API (session expired or empty range); "
                      "falling back to manual login + UI capture.")

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

        # Still logged in + on a same-origin page: read the real (masked)
        # account name from the profile page before we close the session.
        data_label = _resolve_data_label(page, platform, account, label)
        context.close()

    records = state["collected"]
    # Tag every record with the (masked) account we captured it for. Stamp here
    # (once) rather than in each capture branch, so UI-intercept, direct-API,
    # Qoder, TRAE and DeepSeek paths all get it. The label is the masked real
    # name when detectable, otherwise the cookie-profile placeholder.
    for r in records:
        r["account"] = data_label
    warnings = _self_check(platform, records, start, end, kw)
    return records, warnings, data_label


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
    # TRAE's pagination renders "1 2 3 … 7" with a Chinese "下一页" (next) button
    # and no per-page buttons for the hidden middle pages (4-6). Walk forward via
    # the "下一页" button from page 1 — it visits every page. Fall back to clicking
    # each number button only when no next button exists.
    def _click_next():
        return page.evaluate("""() => {
            const btn = Array.from(document.querySelectorAll('button')).find(b => {
                const t = (b.innerText || '').trim();
                const ar = (b.getAttribute('aria-label') || '').toLowerCase();
                return (b.getAttribute('aria-label')||'').includes('下一页') || /next/i.test(ar) || /^[›»]$/.test(t)
                    || /pagination.*next/i.test(b.className || '');
            });
            if (btn && !btn.disabled) { btn.click(); return true; }
            return false;
        }""")

    if page.evaluate("""() => !!Array.from(document.querySelectorAll('button')).find(b => {
        const t = (b.innerText || '').trim();
        const ar = (b.getAttribute('aria-label') || '').toLowerCase();
        return (b.getAttribute('aria-label')||'').includes('下一页') || /next/i.test(ar) || /^[›»]$/.test(t);
    })"""):
        for _ in range(60):
            if not _click_next():
                break
            page.wait_for_timeout(1500)
        print(f"[trae-pages] walked '下一页'; collected={len(state['collected'])}")
    else:
        for pno in page_numbers:
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
                if ok:
                    page.wait_for_timeout(1500)
                    print(f"[trae-pages] clicked page {pno}; collected={len(state['collected'])}")
            except Exception as e:
                print(f"[trae-pages] click {pno} failed: {e}")

    # Deduplicate. Prefer the platform-provided request_id; only fall back to
    # the (model, cost, prompt-prefix) triple when no id is available, so
    # genuinely distinct sessions are never collapsed.
    seen, uniq = set(), []
    for r in state["collected"]:
        key = (r.get("request_id") or "") or (
            r.get("model", ""),
            round(float(r.get("cost") or 0), 6),
            (r.get("prompt", "") or "")[:30],
        )
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    state["collected"] = uniq
    print(f"[trae-pages] final unique rows: {len(state['collected'])}")


# ---------------------------------------------------------------------------
# Multi-account setup wizard (--setup)
# ---------------------------------------------------------------------------
# We deliberately do NOT auto-detect the account count from the installed IDE
# (CodeBuddy / Qoder / TRAE). Their account lists live in opaque local stores
# with vendor-specific, undocumented layouts, and on a real machine the local
# trace under-counts the real accounts (e.g. 4 CodeBuddy logins left only 2
# local traces). So the wizard instead asks the user to declare how many
# accounts they have:
#     1) configs/accounts.json  (user-maintained label list, opt-in), or
#     2) a one-question prompt ("how many accounts?").
#   Either way the user never invents --account labels or logs in blindly: the
#   wizard loops N times, each in its own persistent profile, asking for a
#   manual login only the first time, then caches that session's cookies.
_ACCOUNT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "accounts.json",
)


def load_known_accounts(platform):
    """Return the user-maintained account label list for a platform, or [].

    Source: configs/accounts.json (opt-in). When empty/missing the setup
    wizard prompts the user for a count.
    """
    try:
        with open(_ACCOUNT_CONFIG, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    labels = data.get(platform.lower(), [])
    return [str(x) for x in labels] if isinstance(labels, list) else []


def setup_accounts(platform, usage_url, login_url=None, keyword=None,
                   scroll=20, headless=False, start=None, end=None,
                   account_count=None):
    """Guided account bootstrap.

    For each account we open a dedicated persistent Chrome profile and let the
    user log in once (manual — the client's token cannot be replayed as a web
    cookie). The session is cached, so later captures for that account reuse it
    automatically and never ask again.

    Account labels are chosen WITHOUT any interactive prompt:
      - configs/accounts.json (opt-in), if it lists labels for this platform;
      - else --accounts N (the count the caller passed), if given;
      - else a single default account (auto_1).
    The skill never blocks on a question, so it is safe to run non-interactively.
    """
    known = load_known_accounts(platform)
    if known:
        labels = known
        print(f"[setup] Using {len(labels)} account label(s) from "
              f"configs/accounts.json: {labels}")
    elif account_count and account_count >= 1:
        labels = [f"auto_{i}" for i in range(1, account_count + 1)]
        print(f"[setup] Using {len(labels)} account label(s) from "
              f"--accounts {account_count}: {labels}")
    else:
        labels = ["auto_1"]
        print("[setup] Defaulting to 1 account (auto_1). Provide "
              "configs/accounts.json or --accounts N for more.")

    total = len(labels)
    for i, label in enumerate(labels, 1):
        prof = _default_profile_dir(platform, label)
        print(f"\n[setup] ({i}/{total}) Account: {label}")
        print(f"        Profile : {prof}")
        print(f"        A Chrome window will open. Log in if prompted; "
              f"usage data loads automatically.")
        try:
            recs, warnings, data_label = capture(
                platform, usage_url, login_url, keyword, scroll,
                headless, prof, start=start, end=end, account=label,
                label=label)
            if data_label and data_label != label:
                print(f"        Detected account (masked): {data_label}")
        except Exception as e:
            print(f"[setup] account '{label}' failed: {e}")
            continue
        if warnings:
            for w in warnings:
                print("  ⚠ " + w)
        print(f"[setup] account '{label}': captured {len(recs)} records.")

    print(f"\n[setup] Done. {total} account(s) configured for {platform}.")
    print(f"        Verify : python3 verify_data.py --platform {platform} --all-accounts")
    print(f"        Report : python3 build_report.py --platform {platform} --account all")
    return labels


def _page_text(page):
    """Best-effort page text (visible body, falling back to raw HTML)."""
    try:
        return page.inner_text("body") or ""
    except Exception:
        pass
    try:
        return page.content() or ""
    except Exception:
        return ""


def _probe_account_label(platform, account, usage_url, login_url, keyword,
                         headless, profile_dir):
    """Open a logged-in browser just to read the (masked) real account name from
    the profile page. Reuses the persistent cookie profile (--account is the
    cookie-profile *placeholder*), so no manual login is needed when cookies are
    still valid. Returns the masked name, or None if it can't be read yet.
    """
    if sync_playwright is None:
        return None
    info = PROFILE_URLS.get(platform.lower())
    if not info:
        return None
    url, label = info
    profile_dir = profile_dir or _default_profile_dir(platform, account)
    os.makedirs(profile_dir, exist_ok=True)
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                profile_dir, channel="chrome", headless=headless)
            page = ctx.new_page()
            try:
                if login_url:
                    page.goto(login_url)
                    page.wait_for_load_state("domcontentloaded")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            # Poll the (already-loaded) profile page; do NOT re-navigate, so an
            # in-progress manual login / OTP isn't disrupted.
            deadline = time.time() + 180
            name = None
            while time.time() < deadline:
                name = _extract_profile_value(_page_text(page), label)
                if name:
                    break
                page.wait_for_timeout(3000)
            ctx.close()
            return mask_account_name(name) if name else None
    except Exception as e:
        print(f"[probe] account-name detection skipped ({e}); using cookie label.")
        return None


def _migrate_data_folder(platform, from_label, to_label):
    """Move data files from a placeholder / default folder into the real (masked)
    account folder so history isn't orphaned when the label changes (e.g. auto_1
    -> 王x二). from_label=None is the platform's default (unnamed) root; only its
    loose CSVs are moved (sub-account folders are left untouched).
    """
    if not to_label or (from_label or "") == to_label:
        return
    from_dir = data_store.platform_data_dir(platform, from_label)
    to_dir = data_store.platform_data_dir(platform, to_label)
    if from_dir == to_dir or not os.path.isdir(from_dir):
        return
    moved = False
    for name in os.listdir(from_dir):
        src = os.path.join(from_dir, name)
        if from_label is None and os.path.isdir(src):
            continue  # keep sub-accounts when migrating the default root
        dst = os.path.join(to_dir, name)
        if os.path.exists(dst):
            continue
        try:
            os.rename(src, dst)
            moved = True
        except OSError:
            pass
    try:
        if from_label is None:
            if not os.listdir(from_dir):
                os.rmdir(from_dir)
        else:
            os.rmdir(from_dir)
    except OSError:
        pass
    if moved:
        print(f"[migrate] data {from_label or '(default)'} -> {to_label}")


def _write_account_meta(platform, label, source_url=None):
    """Record the masked account name + its profile source for reference."""
    d = data_store.platform_data_dir(platform, label)
    meta = {
        "name": label,
        "masked": True,
        "source_url": source_url,
        "detected_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(os.path.join(d, "account.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _profile_has_session(profile_dir):
    """True if a persistent Chrome profile already holds cached login cookies,
    so a re-run can auto-authenticate without opening a manual login window."""
    if not profile_dir or not os.path.isdir(profile_dir):
        return False
    cookies = os.path.join(profile_dir, "Cookies")
    return os.path.exists(cookies) and os.path.getsize(cookies) > 0


def main():
    ap = argparse.ArgumentParser(description="Capture AI platform usage via Playwright.")
    ap.add_argument("--platform", required=True, help="qoder / trae / codebuddy / deepseek")
    ap.add_argument("--url", required=True, help="usage page URL")
    ap.add_argument("--account", default=None,
                    help="cookie/login PROFILE selector when you own several "
                         "accounts on this platform (e.g. account_1, account_2 — "
                         "a placeholder is fine). The on-disk data folder is named "
                         "after the real, MASKED account name auto-detected from "
                         "the profile page, not this value.")
    ap.add_argument("--label", default=None,
                    help="explicit (masked) data-folder name for this account "
                         "(e.g. deepseek-kylinlab). Takes precedence over auto-"
                         "detection; --account stays the cookie-profile selector. "
                         "Use this to keep captured data and imported exports under "
                         "one consistent label.")
    ap.add_argument("--login-url", default=None, help="login page URL (optional)")
    ap.add_argument("--keyword", default=None, help="override API URL keyword")
    ap.add_argument("--out", default=None, help="output CSV path (overrides data store)")
    ap.add_argument("--scroll", type=int, default=20, help="scroll iterations")
    ap.add_argument("--headless", action="store_true", help="run headless (risk of bot detection)")
    ap.add_argument("--profile-dir", default=None,
                    help="persistent Chrome profile dir (default: ~/Library/Caches/ai_usage_profile)")
    ap.add_argument("--start", default=None, help="requested range start yyyy-mm-dd (incremental)")
    ap.add_argument("--end", default=None, help="requested range end yyyy-mm-dd (incremental)")
    ap.add_argument("--no-backfill", action="store_true",
                    help="do not force re-fetch of the previous pull's final day "
                         "(set this only if you are certain that day is complete)")
    ap.add_argument("--discover", action="store_true",
                    help="capture the platform's usage API endpoint for future "
                         "automatic download (one-time setup)")
    ap.add_argument("--setup", action="store_true",
                    help="guided account bootstrap: configures N accounts "
                         "(count from configs/accounts.json or --accounts N, "
                         "default 1; no interactive prompt), logging in once "
                         "per account and caching the session cookies.")
    ap.add_argument("--accounts", type=int, default=None,
                    help="number of accounts to configure with --setup "
                         "(default 1 when omitted and configs/accounts.json is "
                         "empty). Non-interactive; never prompts.")
    args = ap.parse_args()

    if args.discover:
        discover(args.platform, args.url, args.login_url, args.keyword,
                 args.headless, args.profile_dir, args.account)
        return

    if args.setup:
        s = e = None
        if args.start:
            s = datetime.strptime(args.start, "%Y-%m-%d").date()
        if args.end:
            e = datetime.strptime(args.end, "%Y-%m-%d").date()
        if s and not e:
            e = date.today()
        if e and not s:
            s = e
        if not s or not e:
            e = date.today()
            s = e - timedelta(days=30)
        setup_accounts(args.platform, args.url, args.login_url, args.keyword,
                       args.scroll, args.headless, start=s, end=e,
                       account_count=args.accounts)
        return

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

    # On-disk account label: prefer the masked REAL name read from the profile
    # page; fall back to the --account cookie-profile placeholder, or the
    # default/unnamed store. final_label stays None until we know it.
    final_label = None
    capture_label = None

    # Incremental logic: when storing (no --out) and a range is given, probe the
    # real (masked) name FIRST so coverage + the data folder are keyed on it,
    # then fetch only the missing days.
    if not args.out and req_start and req_end:
        # Only probe the real (masked) name when the cookie profile already holds
        # a cached session — otherwise the probe would open a SECOND login window.
        # On a fresh profile, capture() performs the single login + name detection.
        _prof = args.profile_dir or _default_profile_dir(args.platform, args.account)
        probe_label = None
        if _profile_has_session(_prof):
            probe_label = _probe_account_label(
                args.platform, args.account, args.url, args.login_url,
                args.keyword, args.headless, args.profile_dir)
        final_label = args.label or probe_label or args.account
        force = set()
        if not args.no_backfill:
            prev = data_store.last_covered_date(args.platform, final_label)
            if prev is not None:
                force.add(prev)
        gaps = data_store.missing_ranges(
            req_start, req_end, args.platform, account=final_label,
            force_days=force)
        if not gaps:
            print(f"[store] range {req_start}~{req_end} already fully cached; "
                  f"skip fetching. Use build_report.py to build the report.")
            return
        print(f"[store] need to fetch gaps: {gaps}")
        # Fetch the union of gaps; Qoder/TRAE UIs accept a single range, so use
        # the outer bounds.
        g0, g1 = gaps[0][0], gaps[-1][1]
        recs, warnings, capture_label = capture(
            args.platform, args.url, args.login_url, args.keyword,
            args.scroll, args.headless, args.profile_dir,
            start=g0, end=g1, account=args.account, label=args.label)
    else:
        recs, warnings, capture_label = capture(
            args.platform, args.url, args.login_url, args.keyword,
            args.scroll, args.headless, args.profile_dir,
            start=req_start, end=req_end, account=args.account, label=args.label)

    # Prefer what capture detected (API-first, reliable); otherwise the probed
    # masked name; otherwise the cookie-profile placeholder.
    final_label = capture_label or final_label or args.account

    if warnings:
        print("\n" + "=" * 60)
        print("[capture: WARNINGS] 抓取结果可能不完整：")
        for w in warnings:
            print("  ⚠ " + w)
        print("=" * 60 + "\n")

    if not recs:
        print("[warn] no records captured. Check keyword / login / URL.")
        return

    # Re-stamp every record with the final (masked) label so raw + merged stores
    # agree, regardless of which path detected it.
    for r in recs:
        r["account"] = final_label

    # Per-request RAW snapshot: one self-contained CSV per capture invocation,
    # named by the range the user REQUESTED. Kept un-merged / un-deduped so a
    # buggy capture or a data-loss event can be diagnosed / recovered.
    raw_s, raw_e = req_start, req_end
    if not (raw_s and raw_e):
        ds = [datetime.strptime(r["date"], "%Y-%m-%d").date()
              for r in recs if r.get("date")]
        raw_s = raw_s or (min(ds) if ds else date.today())
        raw_e = raw_e or (max(ds) if ds else date.today())

    if args.out:
        out = args.out
        fields = ["date", "model", "cost", "free", "prompt", "platform",
                  "account", "requests"]
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(recs)
        print(f"[done] wrote {len(recs)} records -> {out}")
        return

    # Migrate any placeholder / default history into the real (masked) folder so
    # it isn't orphaned when the label changes from e.g. auto_1 to a name.
    if final_label:
        if args.account and args.account != final_label:
            _migrate_data_folder(args.platform, args.account, final_label)
        _migrate_data_folder(args.platform, "auto_1", final_label)  # legacy
        if not args.account:
            _migrate_data_folder(args.platform, None, final_label)  # default root

    if raw_s and raw_e:
        raw_path = data_store.save_raw_capture(
            args.platform, final_label, raw_s, raw_e, recs)
        print(f"[raw] per-request snapshot -> {raw_path}")

    # Persist via the incremental data store (merge + dedupe), keyed on the
    # masked account name.
    if not req_start or not req_end:
        # No range given: default to the widest range seen in captured data.
        ds = [datetime.strptime(r["date"], "%Y-%m-%d").date()
              for r in recs if r.get("date")]
        req_start = min(ds) if ds else date.today()
        req_end = max(ds) if ds else date.today()
    path = data_store.merge_and_save(args.platform, recs, req_start, req_end,
                                     account=final_label)
    print(f"[done] stored {len(recs)} records -> {path}")
    # Record the source profile URL + masked name for reference/reports.
    src = PROFILE_URLS.get(args.platform.lower(), (None, None))[0]
    _write_account_meta(args.platform, final_label, src)
    print(f"        data dir: {data_store.platform_data_dir(args.platform, final_label)}")
    acc_flag = f" --account {final_label}" if final_label else ""
    print(f"        next: python3 verify_data.py --platform {args.platform}"
          f"{acc_flag} --start {req_start} --end {req_end}")
    print(f"        then: python3 build_report.py --platform {args.platform}"
          f"{acc_flag} --start {req_start} --end {req_end}")


if __name__ == "__main__":
    main()
