import os, json, requests, re
from typing import Tuple, Optional

# -----------------------------
# Config from env (/data/options.json is exported by run.sh)
# -----------------------------
TECH_URL = (os.getenv("technitium_url", "") or "").rstrip("/")
TECH_KEY = os.getenv("technitium_api_key", "") or ""
ENABLED  = os.getenv("technitium_enabled", "false").strip().lower() in ("1","true","yes")

# Accept all common auth styles used by Technitium
HDRS = {
    "Authorization": f"Bearer {TECH_KEY}" if TECH_KEY else "",
    "X-Auth-Token": TECH_KEY if TECH_KEY else "",
}
# Drop empty header entries (requests will choke on empty Authorization)
HDRS = {k: v for k, v in HDRS.items() if v}

def _with_token(url: str) -> str:
    """Append ?token= if caller is using query based auth (some setups require it)."""
    if TECH_KEY and "token=" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}token={TECH_KEY}"
    return url

# -----------------------------
# HTTP helpers
# -----------------------------
def _get_json(url: str, timeout: int = 8):
    try:
        u = _with_token(url)
        r = requests.get(u, headers=HDRS, timeout=timeout)
        # Some instances return text for /metrics; let caller handle non-JSON
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        try:
            return r.json()
        except Exception:
            return r.text  # return raw for non-JSON endpoints
    except Exception as e:
        return {"error": str(e)}

def _post_json(url: str, timeout: int = 8, data=None):
    try:
        u = _with_token(url)
        r = requests.post(u, headers=HDRS, json=(data or {}), timeout=timeout)
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code, "text": r.text}
    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Cache flush (try both old/new paths & methods)
# -----------------------------
def _flush_cache() -> Tuple[bool, Optional[object]]:
    candidates = (
        ("POST", "/api/dns/cache/flush"),   # newer path (pref)
        ("GET",  "/api/dns/cache/flush"),
        ("POST", "/api/dns/flushcache"),    # older path alias
        ("GET",  "/api/dns/flushcache"),
    )
    for method, path in candidates:
        url = f"{TECH_URL}{path}"
        resp = _post_json(url) if method == "POST" else _get_json(url)
        if isinstance(resp, dict) and "error" in resp:
            continue
        # Consider any 200-ish, or a dict/ok text, as success
        if isinstance(resp, dict):
            # Some builds return {"success":true} or {"status":"ok"}
            if str(resp.get("success", "")).lower() == "true" or str(resp.get("status","")).lower() in ("ok","success"):
                return True, resp
        if isinstance(resp, str) and re.search(r"\bok\b|\bsuccess\b|\bflushed\b", resp, re.I):
            return True, resp
    return False, None

# -----------------------------
# Stats readers
# -----------------------------
def _parse_json_stats(obj: dict):
    """
    Normalize keys that Technitium exposes across versions.
    We try multiple likely field names and also dig into nested dicts.
    """
    def pick(d, *keys, default=0):
        for k in keys:
            if k in d and isinstance(d[k], (int, float)):
                return int(d[k])
        return default

    total   = pick(obj, "TotalQueryCount", "totalQueries", "queries", "total", "dns_queries_total")
    blocked = pick(obj, "TotalBlockedQueryCount", "blockedQueries", "blocked", "dns_blocked_total")
    cache   = pick(obj, "CacheCount", "cacheSize", "cache", "cache_count")

    if (total == 0 and blocked == 0 and cache == 0) and any(isinstance(v, dict) for v in obj.values()):
        # Some versions nest counters by section
        for v in obj.values():
            if isinstance(v, dict):
                total   = total   or pick(v, "TotalQueryCount", "totalQueries", "queries", "total", "dns_queries_total")
                blocked = blocked or pick(v, "TotalBlockedQueryCount", "blockedQueries", "blocked", "dns_blocked_total")
                cache   = cache   or pick(v, "CacheCount", "cacheSize", "cache", "cache_count")

    allowed = total - blocked if total and blocked is not None else pick(obj, "allowed", default=0)
    return {"total": total, "blocked": blocked, "allowed": max(0, allowed), "cache": cache}

_METRIC_LINE = re.compile(r"^\s*([a-zA-Z_:][a-zA-Z0-9_:]*)\s*{[^}]*}\s*([0-9]+(?:\.[0-9]+)?)\s*$")
def _parse_prometheus_metrics(text: str):
    """
    Very small Prometheus text parser; looks for common Technitium counters.
    """
    total = blocked = cache = 0
    for line in (text or "").splitlines():
        m = _METRIC_LINE.match(line)
        if not m:
            continue
        name, val_s = m.group(1), m.group(2)
        try:
            val = int(float(val_s))
        except Exception:
            continue
        lname = name.lower()
        if "query" in lname and "total" in lname:
            # dnsserver_queries_total or similar
            total = max(total, val)
        if "blocked" in lname and "total" in lname:
            blocked = max(blocked, val)
        if "cache" in lname and ("count" in lname or "entries" in lname or "size" in lname):
            cache = max(cache, val)
    allowed = max(0, total - blocked) if total else 0
    return {"total": total, "blocked": blocked, "allowed": allowed, "cache": cache}

def _read_stats():
    """
    Try JSON endpoints first, then Prometheus /metrics as fallback.
    """
    json_candidates = (
        "/api/dns/metrics",      # newer
        "/api/dns/statistics",   # older
        "/api/dns/stats",        # alias
        "/api/metrics",          # some builds
    )
    for path in json_candidates:
        resp = _get_json(f"{TECH_URL}{path}")
        if isinstance(resp, dict) and "error" not in resp:
            return _parse_json_stats(resp)
        # sometimes a JSON list might be wrapped or text returned; ignore here
    # Prometheus text fallback
    text_candidates = ("/metrics", "/api/metrics")
    for path in text_candidates:
        resp = _get_json(f"{TECH_URL}{path}")
        if isinstance(resp, str) and resp.strip():
            return _parse_prometheus_metrics(resp)
    return None

# -----------------------------
# Pretty helpers
# -----------------------------
def _kv(label, value): return f"    {label}: {value:,}" if isinstance(value, int) else f"    {label}: {value}"

# -----------------------------
# Public command router (called by bot.py)
# -----------------------------
def handle_dns_command(cmd: str):
    """
    Supported voice commands (under the Jarvis wake word):
      • 'dns status' / 'dns'
      • 'dns flush'
    """
    if not ENABLED or not TECH_URL:
        return "⚠️ DNS module not enabled or misconfigured", None

    c = (cmd or "").strip().lower()

    if c == "dns" or c.startswith("dns status"):
        stats = _read_stats()
        if not stats:
            return "⚠️ Could not read DNS stats", None
        total   = stats.get("total", 0)
        blocked = stats.get("blocked", 0)
        allowed = stats.get("allowed", max(0, total - blocked))
        cache   = stats.get("cache", 0)
        lines = []
        lines.append("🌐 Technitium DNS — Stats\n")
        lines.append(_kv("Total Queries", total))
        lines.append(_kv("Blocked",       blocked))
        lines.append(_kv("Allowed",       allowed))
        lines.append(_kv("Cache Size",    cache))
        return "\n".join(lines), None

    if c.startswith("dns flush"):
        ok, _ = _flush_cache()
        return ("🌐 DNS cache flushed successfully" if ok else "⚠️ DNS cache flush failed"), None

    # Not a DNS command → let other routers try
    return None
