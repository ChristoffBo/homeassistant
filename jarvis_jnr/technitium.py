import os, json, requests

# Config from env (exported by run.sh from /data/options.json)
TECH_URL = os.getenv("technitium_url", "").rstrip("/")
TECH_KEY = os.getenv("technitium_api_key", "")
ENABLED  = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")

HEADERS = {"Authorization": f"Bearer {TECH_KEY}"} if TECH_KEY else {}

def _get(url, timeout=8):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def _flush_cache():
    # Try common Technitium endpoints
    for path in ("/api/dns/flushcache", "/api/dns/cache/flush"):
        j = _get(f"{TECH_URL}{path}")
        if isinstance(j, dict) and "error" not in j:
            return True, j
    return False, None

def _read_stats():
    """
    Normalize to: total, blocked, allowed, cache
    """
    candidates = (
        "/api/dns/metrics",
        "/api/dns/statistics",
        "/api/dns/stats",
        "/api/metrics",
    )
    data = None
    for path in candidates:
        j = _get(f"{TECH_URL}{path}")
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

    # if nested metrics
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

def handle_dns_command(cmd: str):
    """
    Supported voice commands:
      - 'dns status'
      - 'dns flush'
    """
    if not ENABLED or not TECH_URL:
        return "⚠️ DNS module not enabled or misconfigured", None

    c = (cmd or "").strip().lower()

    if c.startswith("dns status") or c == "dns":
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
