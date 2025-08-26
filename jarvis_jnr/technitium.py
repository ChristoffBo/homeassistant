import os, requests, re
from typing import Tuple, Optional

# -----------------------------
# Config from env
# -----------------------------
TECH_URL = (os.getenv("technitium_url", "") or "").rstrip("/")
TECH_USER = os.getenv("technitium_user", "")
TECH_PASS = os.getenv("technitium_pass", "")
TECH_KEY  = os.getenv("technitium_api_key", "")
ENABLED   = os.getenv("technitium_enabled", "false").strip().lower() in ("1","true","yes")

_session_token: Optional[str] = None

def _login_if_needed() -> str:
    """Get a valid token: prefer permanent API key, else login with user/pass."""
    global _session_token
    if TECH_KEY:
        return TECH_KEY
    if _session_token:
        return _session_token
    if not (TECH_USER and TECH_PASS and TECH_URL):
        return ""
    try:
        url = f"{TECH_URL}/api/user/login?user={TECH_USER}&pass={TECH_PASS}&includeInfo=true"
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        j = r.json()
        tok = j.get("token") or j.get("Token")
        if tok:
            _session_token = tok
            return tok
    except Exception as e:
        print(f"[Technitium] Login failed: {e}")
    return ""

def _with_token(url: str) -> str:
    tok = _login_if_needed()
    if tok and "token=" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}token={tok}"
    return url

# -----------------------------
# HTTP helpers
# -----------------------------
def _get_json(url: str, timeout: int = 8):
    try:
        r = requests.get(_with_token(url), timeout=timeout)
        if "application/json" in r.headers.get("content-type",""):
            return r.json()
        try: return r.json()
        except: return r.text
    except Exception as e:
        return {"error": str(e)}

def _post_json(url: str, timeout: int = 8, data=None):
    try:
        r = requests.post(_with_token(url), json=(data or {}), timeout=timeout)
        try: return r.json()
        except: return {"status_code": r.status_code, "text": r.text}
    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Cache flush
# -----------------------------
def _flush_cache() -> Tuple[bool, Optional[object]]:
    for method, path in (("POST","/api/dns/cache/flush"),
                         ("GET","/api/dns/cache/flush"),
                         ("POST","/api/dns/flushcache"),
                         ("GET","/api/dns/flushcache")):
        resp = _post_json(f"{TECH_URL}{path}") if method=="POST" else _get_json(f"{TECH_URL}{path}")
        if isinstance(resp, dict) and "error" in resp:
            continue
        if isinstance(resp, dict):
            if str(resp.get("success","")).lower()=="true" or str(resp.get("status","")).lower() in ("ok","success"):
                return True, resp
        if isinstance(resp, str) and re.search(r"\bok\b|\bsuccess\b|\bflushed\b", resp, re.I):
            return True, resp
    return False, None

# -----------------------------
# Stats readers
# -----------------------------
def _parse_json_stats(obj: dict):
    def pick(d,*keys,default=0):
        for k in keys:
            if k in d and isinstance(d[k],(int,float)):
                return int(d[k])
        return default
    total   = pick(obj,"TotalQueryCount","totalQueries","queries","total")
    blocked = pick(obj,"TotalBlockedQueryCount","blockedQueries","blocked")
    cache   = pick(obj,"CacheCount","cacheSize","cache","cache_count")
    if (total==0 and blocked==0 and cache==0) and any(isinstance(v,dict) for v in obj.values()):
        for v in obj.values():
            if isinstance(v,dict):
                total   = total   or pick(v,"TotalQueryCount","totalQueries","queries","total")
                blocked = blocked or pick(v,"TotalBlockedQueryCount","blockedQueries","blocked")
                cache   = cache   or pick(v,"CacheCount","cacheSize","cache","cache_count")
    allowed = total-blocked if total and blocked is not None else 0
    return {"total":total,"blocked":blocked,"allowed":max(0,allowed),"cache":cache}

_METRIC_LINE = re.compile(r"^\s*([a-zA-Z_:][\w:]*)\s*{[^}]*}\s*([0-9]+(?:\.[0-9]+)?)\s*$")
def _parse_prometheus_metrics(text: str):
    total=blocked=cache=0
    for line in (text or "").splitlines():
        m=_METRIC_LINE.match(line)
        if not m: continue
        name,val_s=m.group(1),m.group(2)
        try: val=int(float(val_s))
        except: continue
        lname=name.lower()
        if "query" in lname and "total" in lname: total=max(total,val)
        if "blocked" in lname and "total" in lname: blocked=max(blocked,val)
        if "cache" in lname: cache=max(cache,val)
    allowed=max(0,total-blocked) if total else 0
    return {"total":total,"blocked":blocked,"allowed":allowed,"cache":cache}

def _read_stats():
    for path in ("/api/dns/metrics","/api/dns/statistics","/api/dns/stats","/api/metrics"):
        resp=_get_json(f"{TECH_URL}{path}")
        if isinstance(resp,dict) and "error" not in resp:
            return _parse_json_stats(resp)
    for path in ("/metrics","/api/metrics"):
        resp=_get_json(f"{TECH_URL}{path}")
        if isinstance(resp,str) and resp.strip():
            return _parse_prometheus_metrics(resp)
    return None

# -----------------------------
# Command router
# -----------------------------
def handle_dns_command(cmd: str):
    if not ENABLED or not TECH_URL:
        return "⚠️ DNS module not enabled or misconfigured", None
    c=(cmd or "").strip().lower()
    if c=="dns" or c.startswith("dns status"):
        stats=_read_stats()
        if not stats: return "⚠️ Could not read DNS stats",None
        lines=["🌐 Technitium DNS — Stats\n",
               f"    Total Queries: {stats.get('total',0):,}",
               f"    Blocked: {stats.get('blocked',0):,}",
               f"    Allowed: {stats.get('allowed',0):,}",
               f"    Cache Size: {stats.get('cache',0):,}"]
        return "\n".join(lines),None
    if c.startswith("dns flush"):
        ok,_=_flush_cache()
        return ("🌐 DNS cache flushed successfully" if ok else "⚠️ DNS cache flush failed"),None
    return None
