import os, json, requests, re, threading
from typing import Tuple, Optional

# =============================
# Config (set via run.sh env)
# =============================
TECH_URL  = (os.getenv("technitium_url", "") or "").rstrip("/")
TECH_KEY  = os.getenv("technitium_api_key", "") or ""
TECH_USER = os.getenv("technitium_user", "") or ""
TECH_PASS = os.getenv("technitium_pass", "") or ""
ENABLED   = os.getenv("technitium_enabled", "false").strip().lower() in ("1","true","yes")

# Token cache (thread-safe)
_token_lock = threading.RLock()
_token_value: Optional[str] = None

def _set_token(tok: Optional[str]):
    global _token_value
    with _token_lock:
        _token_value = tok

def _get_token() -> Optional[str]:
    with _token_lock:
        return _token_value

# -----------------------------------
# Low-level HTTP with auth handling
# -----------------------------------
def _login_if_needed() -> Optional[str]:
    """
    Ensure we have a working token.
    Priority:
      1) Use provided TECH_KEY directly (as token/header)
      2) Login with TECH_USER/TECH_PASS to obtain token
    """
    # 1) direct token provided
    if TECH_KEY:
        _set_token(TECH_KEY)
        return TECH_KEY

    # 2) try login
    tok = _get_token()
    if tok:
        return tok
    if not (TECH_USER and TECH_PASS and TECH_URL):
        return None
    try:
        # /api/user/login returns { status: "ok", token: "..." } on success
        url = f"{TECH_URL}/api/user/login"
        r = requests.post(url, data={"username": TECH_USER, "password": TECH_PASS}, timeout=8)
        j = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        if j.get("status") == "ok" and j.get("token"):
            _set_token(j["token"])
            return j["token"]
    except Exception:
        pass
    return None

def _auth_headers(tok: Optional[str]) -> dict:
    """
    Build headers accepted by Technitium. Most endpoints are fine
    with query ?token=... but we send a header too for good measure.
    """
    hdrs = {}
    if tok:
        # Both are accepted by various builds; neither hurts.
        hdrs["Authorization"] = f"Bearer {tok}"
        hdrs["X-Auth-Token"]  = tok
    return hdrs

def _with_token_query(url: str, tok: Optional[str]) -> str:
    if tok and "token=" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}token={tok}"
    return url

def _get(url_path: str, timeout: int = 8):
    tok = _login_if_needed()
    url = _with_token_query(f"{TECH_URL}{url_path}", tok)
    try:
        r = requests.get(url, headers=_auth_headers(tok), timeout=timeout)
        if r.headers.get("content-type","").startswith("application/json"):
            return r.json()
        # Prometheus text or other
        try:
            return r.json()
        except Exception:
            return r.text
    except Exception as e:
        return {"status":"error","errorMessage":str(e)}

def _post(url_path: str, data=None, timeout: int = 8):
    tok = _login_if_needed()
    url = _with_token_query(f"{TECH_URL}{url_path}", tok)
    try:
        r = requests.post(url, headers=_auth_headers(tok), data=(data or {}), timeout=timeout)
        if r.headers.get("content-type","").startswith("application/json"):
            return r.json()
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code, "text": r.text}
    except Exception as e:
        return {"status":"error","errorMessage":str(e)}

# -----------------------------------
# API calls (documented endpoints)
#   - stats: /api/dashboard/stats/get
#   - flush: /api/cache/flush
# -----------------------------------

def _read_stats() -> Optional[dict]:
    """
    Normalizes dashboard stats across versions.
    Docs: /api/dashboard/stats/get?token=...
    Fallback: /metrics (Prometheus) if JSON unavailable.
    """
    # Primary JSON endpoint
    j = _get("/api/dashboard/stats/get")
    if isinstance(j, dict) and j.get("status") == "ok":
        resp = j.get("response") or j  # some builds put values at root/response
        # Try several likely keys
        def pick(d, *ks):
            for k in ks:
                v = d.get(k)
                if isinstance(v, (int, float)):
                    return int(v)
            return 0

        total   = pick(resp,
                       "TotalQueryCount","totalQueries","dnsQueryCount",
                       "queries","total","dns_queries_total")
        blocked = pick(resp,
                       "TotalBlockedQueryCount","blockedQueries","blockedQueryCount",
                       "blocked","dns_blocked_total")
        cache   = pick(resp,
                       "CacheCount","cacheSize","cacheCount","cache","cache_count")

        # nested dictionaries? scan once
        if (total == 0 and blocked == 0 and cache == 0):
            for v in resp.values():
                if isinstance(v, dict):
                    total   = total   or pick(v,"TotalQueryCount","totalQueries","dnsQueryCount","queries","total")
                    blocked = blocked or pick(v,"TotalBlockedQueryCount","blockedQueries","blockedQueryCount","blocked")
                    cache   = cache   or pick(v,"CacheCount","cacheSize","cacheCount","cache")

        allowed = max(0, total - blocked) if total else 0
        return {"total": total, "blocked": blocked, "allowed": allowed, "cache": cache}

    # Prometheus text fallback
    text = _get("/metrics")
    if isinstance(text, str) and text.strip():
        pat = re.compile(r"^\s*([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?:\{[^}]*\})?\s+([0-9]+(?:\.[0-9]+)?)\s*$")
        total = blocked = cache = 0
        for line in text.splitlines():
            m = pat.match(line)
            if not m: continue
            name, val_s = m.group(1).lower(), m.group(2)
            try:
                val = int(float(val_s))
            except Exception:
                continue
            if "query" in name and "total" in name:
                total = max(total, val)
            if "blocked" in name and "total" in name:
                blocked = max(blocked, val)
            if "cache" in name and ("count" in name or "entries" in name or "size" in name):
                cache = max(cache, val)
        return {"total": total, "blocked": blocked, "allowed": max(0,total-blocked), "cache": cache}
    return None

def _flush_cache() -> Tuple[bool, Optional[object]]:
    """
    Docs: /api/cache/flush?token=...
    Also tries known obsolete/legacy paths just in case.
    """
    for path in ("/api/cache/flush", "/api/flushDnsCache", "/api/dns/cache/flush", "/api/dns/flushcache"):
        resp = _post(path)
        if isinstance(resp, dict) and resp.get("status") == "ok":
            return True, resp
        if isinstance(resp, str) and re.search(r"\bok\b|\bsuccess\b|\bflushed\b", resp, re.I):
            return True, resp
    return False, None

# -----------------------------------
# Public command router
# -----------------------------------
def _kv(label, value):
    if isinstance(value, int):
        return f"    {label}: {value:,}"
    return f"    {label}: {value}"

def handle_dns_command(cmd: str):
    """
    Voice commands under "jarvis ...":
      • 'dns' / 'dns status' / 'DNS status'
      • 'dns flush' / 'DNS flush'
    """
    if not ENABLED or not TECH_URL:
        return "⚠️ DNS module not enabled or misconfigured", None

    c = (cmd or "").strip().lower()

    if c == "dns" or c.startswith("dns status"):
        stats = _read_stats()
        if not stats:
            return "⚠️ Could not read DNS stats", None
        lines = []
        lines.append("🌐 Technitium DNS — Stats\n")
        lines.append(_kv("Total Queries", stats.get("total", 0)))
        lines.append(_kv("Blocked",       stats.get("blocked", 0)))
        lines.append(_kv("Allowed",       stats.get("allowed", 0)))
        lines.append(_kv("Cache Size",    stats.get("cache", 0)))
        return "\n".join(lines), None

    if c.startswith("dns flush"):
        ok, _ = _flush_cache()
        return ("🌐 DNS cache flushed successfully" if ok else "⚠️ DNS cache flush failed"), None

    # not ours → let other routers try
    return None
