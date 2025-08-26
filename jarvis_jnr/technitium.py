import os, json, requests
from urllib.parse import urlencode

# Config from env (exported by run.sh from /data/options.json)
TECH_URL = (os.getenv("technitium_url", "") or "").rstrip("/")
TECH_KEY = os.getenv("technitium_api_key", "")
ENABLED  = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")

# ---- helpers ---------------------------------------------------------------
def _url(path: str) -> str:
    """
    Build URL with ?token=... appended (Technitium API expects token query param).
    Handles whether the path already contains a query string.
    """
    if not TECH_URL:
        return path
    sep = "&" if "?" in path else "?"
    q = urlencode({"token": TECH_KEY}) if TECH_KEY else ""
    return f"{TECH_URL}{path}{sep}{q}" if q else f"{TECH_URL}{path}"

def _get(full_or_path: str, timeout=8):
    """
    Accept either a full URL or a path like '/api/dns/metrics'.
    Always call with token in the query string.
    """
    url = full_or_path if full_or_path.startswith("http") else _url(full_or_path)
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        # Some endpoints may reply with plain text; try JSON first
        try:
            return r.json()
        except Exception:
            return {"text": r.text}
    except Exception as e:
        return {"error": str(e)}

# ---- actions ---------------------------------------------------------------
def _flush_cache():
    # Try common Technitium endpoints
    for path in ("/api/dns/flushcache", "/api/dns/cache/flush"):
        j = _get(path)
        if isinstance(j, dict) and "error" not in j:
            return True, j
    return False, None

def _read_stats():
    """
    Normalize to: total, blocked, allowed, cache
    Supports multiple possible endpoints/field names.
    """
    candidates = (
        "/api/dns/metrics",
        "/api/dns/statistics",
        "/api/dns/stats",
        "/api/metrics",
    )
    data = None
    for path in candidates:
        j = _get(path)
        if isinstance(j, dict) and "error" not in j:
            data = j
            break
    if not isinstance(data, dict):
        return None

    def pick(d, *keys, default=0):
        for k in keys:
            if k in d and isinstance(d[k], (int, float)):
                return int(d[k])
        return default

    total   = pick(data, "TotalQueryCount", "totalQueries", "queries", "total")
    blocked = pick(data, "TotalBlockedQueryCount", "blockedQueries", "blocked")
    cache   = pick(data, "CacheCount", "cacheSize", "cache", "cache_count")
    allowed = total - blocked if total and blocked is not None else pick(data, "allowed", default=0)

    # if nested
    if total == 0 and any(isinstance(v, dict) for v in data.values()):
        for v in data.values():
            if isinstance(v, dict):
                total   = total   or pick(v, "TotalQueryCount", "totalQueries", "queries", "total")
                blocked = blocked or pick(v, "TotalBlockedQueryCount", "blockedQueries", "blocked")
                cache   = cache   or pick(v, "CacheCount", "cacheSize", "cache", "cache_count")
        allowed = total - blocked if total and blocked is not None else allowed

    return {"total": total, "blocked": blocked, "allowed": allowed, "cache": cache}

def _kv(label, value):
    return f"    {label}: {value}"

# ---- public router ---------------------------------------------------------
def handle_dns_command(cmd: str):
    """
    Supported voice commands (title must begin with 'Jarvis'):
      - 'dns status' / 'dns stats'
      - 'dns flush'
    """
    if not ENABLED or not TECH_URL:
        return "⚠️ DNS module not enabled or misconfigured", None

    c = (cmd or "").strip().lower()

    if c.startswith("dns status") or c.startswith("dns stats") or c == "dns":
        stats = _read_stats()
        if not stats:
            return "⚠️ Could not read DNS stats", None
        total   = stats.get("total",   0)
        blocked = stats.get("blocked", 0)
        allowed = stats.get("allowed", max(0, total - blocked))
        cache   = stats.get("cache",   0)
        lines = []
        lines.append("🌐 Technitium DNS — Stats\n")
        lines.append(_kv("Total Queries", f"{total:,}"))
        lines.append(_kv("Blocked",       f"{blocked:,}"))
        lines.append(_kv("Allowed",       f"{allowed:,}"))
        lines.append(_kv("Cache Size",    f"{cache:,}"))
        return "\n".join(lines), None

    if c.startswith("dns flush"):
        ok, _ = _flush_cache()
        return ("🌐 DNS cache flushed successfully" if ok else "⚠️ DNS cache flush failed"), None

    # Not a DNS command → let other routers try
    return None
