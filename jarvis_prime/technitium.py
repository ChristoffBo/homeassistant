import os
import re
import threading
import base64
import requests
from typing import Optional, Tuple, Dict

# =============================
# Config (set via run.sh env)
# =============================
TECH_URL  = (os.getenv("technitium_url", "") or "").rstrip("/")
TECH_KEY  = os.getenv("technitium_api_key", "") or ""
TECH_USER = os.getenv("technitium_user", "") or ""
TECH_PASS = os.getenv("technitium_pass", "") or ""
ENABLED   = os.getenv("technitium_enabled", "false").strip().lower() in ("1","true","yes")

_session = requests.Session()
_token_lock = threading.RLock()
_token_value: Optional[str] = None  # runtime token (api key or login token)

# =============================
# Auth helpers
# =============================
def _set_token(tok: Optional[str]) -> None:
    global _token_value
    with _token_lock:
        _token_value = tok

def _get_token() -> Optional[str]:
    with _token_lock:
        return _token_value

def _basic_auth_header() -> Optional[str]:
    if TECH_USER and TECH_PASS:
        raw = f"{TECH_USER}:{TECH_PASS}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")
    return None

def _auth_headers(token: Optional[str], variant: str) -> dict:
    """
    variant: 'both' -> Bearer + X-Auth-Token
             'bearer'
             'xauth'
             'none'
    """
    hdrs: Dict[str, str] = {}
    if token:
        if variant == "both":
            hdrs["Authorization"] = f"Bearer {token}"
            hdrs["X-Auth-Token"] = token
        elif variant == "bearer":
            hdrs["Authorization"] = f"Bearer {token}"
        elif variant == "xauth":
            hdrs["X-Auth-Token"] = token
    # Opportunistic Basic if not already set
    ba = _basic_auth_header()
    if ba and "Authorization" not in hdrs:
        hdrs["Authorization"] = ba
    return hdrs

def _append_token_query(url: str, token: Optional[str]) -> str:
    if token and "token=" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}token={token}"
    return url

def _try_login_for_token() -> Optional[str]:
    """Technitium v13+: /api/user/login (fields: user, pass)"""
    if not (TECH_URL and TECH_USER and TECH_PASS):
        return None
    try:
        r = _session.post(f"{TECH_URL}/api/user/login",
                          data={"user": TECH_USER, "pass": TECH_PASS}, timeout=8)
        j = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
        tok = (j or {}).get("token")
        if (j or {}).get("status") == "ok" and tok:
            _set_token(tok); return tok
    except Exception:
        pass
    try:
        r = _session.get(f"{TECH_URL}/api/user/login",
                         params={"user": TECH_USER, "pass": TECH_PASS}, timeout=8)
        if r.ok:
            j = r.json()
            tok = (j or {}).get("token")
            if (j or {}).get("status") == "ok" and tok:
                _set_token(tok); return tok
    except Exception:
        pass
    return None

def _ensure_token() -> Optional[str]:
    if TECH_KEY:
        _set_token(TECH_KEY); return TECH_KEY
    tok = _get_token()
    if tok:
        return tok
    return _try_login_for_token()

def _request(method: str, path: str, *, data=None, timeout: int = 8):
    """Robust request wrapper handling token/bearer/xauth/query/basic variants."""
    if not TECH_URL:
        return {"error": "Technitium URL not configured"}

    def _do(url, headers):
        try:
            if method == "GET":
                resp = _session.get(url, headers=headers, timeout=timeout)
            else:
                resp = _session.post(url, headers=headers, data=(data or {}), timeout=timeout)
        except Exception as e:
            return None, {"error": str(e)}
        # parse json if possible
        if resp.headers.get("content-type","").startswith("application/json"):
            try:
                payload = resp.json()
            except Exception:
                payload = {"status_code": resp.status_code, "text": resp.text}
        else:
            try:
                payload = resp.json()
            except Exception:
                payload = resp.text
        return resp, payload

    token = _ensure_token()
    variants = [("both", True), ("bearer", False), ("xauth", False), ("none", True)]

    def _run(tok):
        last = (None, None)
        for v, add_q in variants:
            url = f"{TECH_URL}{path}"
            if add_q:
                url = _append_token_query(url, tok)
            headers = _auth_headers(tok, v)
            last = _do(url, headers)
            resp, payload = last
            if resp is not None and 200 <= resp.status_code < 300:
                return payload
            if isinstance(payload, dict) and str(payload.get("status","")).lower() in ("ok","success"):
                return payload
            if resp is not None and resp.status_code in (401, 403):
                continue
        return last

    got = _run(token)
    if not isinstance(got, tuple):
        return got
    resp, payload = got

    if (getattr(resp, "status_code", None) in (401,403)) or (isinstance(payload, dict) and payload.get("error")):
        tok2 = _try_login_for_token()
        if tok2 and tok2 != token:
            got2 = _run(tok2)
            if not isinstance(got2, tuple):
                return got2
            resp, payload = got2

    # final basic-only attempt
    if TECH_USER and TECH_PASS:
        url = f"{TECH_URL}{path}"
        headers = {}
        ba = _basic_auth_header()
        if ba:
            headers["Authorization"] = ba
        resp2, payload2 = _do(url, headers)
        if resp2 is not None and 200 <= resp2.status_code < 300:
            return payload2
        payload = payload2

    return payload if payload is not None else {"error": "request failed"}

def _get(path: str, timeout: int = 8): return _request("GET", path, timeout=timeout)

# =============================
# Stats (Dashboard JSON or Prometheus /metrics)
# =============================
_DASH_KEYS = {
    "total": ["TotalQueryCount","totalQueries","dnsQueryCount","queries","total","dns_queries_total"],
    "no_error": ["NoErrorCount","noError","okCount","no_error"],
    "server_failure": ["ServerFailureCount","servfail","serverFailure"],
    "nx_domain": ["NXDomainCount","nxDomain","nxdomain"],
    "refused": ["RefusedCount","refused"],
    "authoritative": ["AuthoritativeCount","authoritative"],
    "recursive": ["RecursiveCount","recursive"],
    "cached": ["CacheCount","cacheCount","cacheSize","cached"],
    "blocked": ["BlockedQueryCount","blockedQueries","blocked","TotalBlockedQueryCount"],
    "dropped": ["DroppedCount","dropped"],
    "clients": ["UniqueClientCount","clients","uniqueClients"],
}

_PROM_RE = re.compile(r'^\s*([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?:\{[^}]*\})?\s+([0-9]+(?:\.[0-9]+)?)\s*$')

def _pick_num(d: dict, keys) -> int:
    for k in keys:
        if k in d and isinstance(d[k], (int, float)):
            return int(d[k])
    return 0

def _read_stats() -> Optional[dict]:
    # Preferred: JSON dashboard (v13+)
    j = _get("/api/dashboard/stats/get")
    if isinstance(j, dict) and ((j.get("status") == "ok" and isinstance(j.get("response"), dict)) or "TotalQueryCount" in j or "totalQueries" in j):
        src = j.get("response", j)
        out = {}
        for label, keys in _DASH_KEYS.items():
            out[label] = _pick_num(src, keys)
        if sum(out.values()) == 0:
            for v in src.values():
                if isinstance(v, dict):
                    for label, keys in _DASH_KEYS.items():
                        out[label] = out[label] or _pick_num(v, keys)
        out["allowed"] = max(0, out.get("total", 0) - out.get("blocked", 0))
        return out

    # Fallback: Prometheus metrics
    text = _get("/metrics")
    if isinstance(text, str) and text.strip():
        vals = {k: 0 for k in _DASH_KEYS.keys()}
        for line in text.splitlines():
            m = _PROM_RE.match(line)
            if not m: continue
            name = m.group(1).lower()
            try:
                val = int(float(m.group(2)))
            except Exception:
                continue
            if "queries_total" in name or (("query" in name) and ("total" in name)):
                vals["total"] = max(vals["total"], val)
            if "blocked" in name and "total" in name:
                vals["blocked"] = max(vals["blocked"], val)
            if "cache" in name and ("count" in name or "entries" in name or "size" in name):
                vals["cached"] = max(vals["cached"], val)
            if "clients" in name or "unique_clients" in name:
                vals["clients"] = max(vals["clients"], val)
            if "nxdomain" in name:
                vals["nx_domain"] = max(vals["nx_domain"], val)
            if "refused" in name:
                vals["refused"] = max(vals["refused"], val)
            if "servfail" in name or "server_failure" in name:
                vals["server_failure"] = max(vals["server_failure"], val)
            if "authoritative" in name:
                vals["authoritative"] = max(vals["authoritative"], val)
            if "recursive" in name:
                vals["recursive"] = max(vals["recursive"], val)
            if "noerror" in name or "no_error" in name:
                vals["no_error"] = max(vals["no_error"], val)
            if "dropped" in name:
                vals["dropped"] = max(vals["dropped"], val)
        vals["allowed"] = max(0, vals.get("total", 0) - vals.get("blocked", 0))
        return vals

    return None

# =============================
# Presentation
# =============================
def _pct(part: int, total: int) -> str:
    if total <= 0: return "0.00%"
    return f"{(part/total)*100:.2f}%"

def _kv(label, value, pct=None):
    if pct is None:
        return f"    {label}: {value}"
    return f"    {label}: {value} ({pct})"

def handle_dns_command(cmd: str):
    """
    Voice:
      • 'dns'
      • 'dns status'
    Returns a dashboard-style summary (counts + % of total).
    """
    if not ENABLED or not TECH_URL:
        return "⚠️ DNS module not enabled or misconfigured", None

    c = (cmd or "").strip().lower()
    if c == "dns" or c.startswith("dns status"):
        s = _read_stats()
        if not s:
            return "⚠️ Could not read DNS stats", None

        total = s.get("total", 0)
        lines = []
        lines.append("🌐 Technitium DNS — Overview\n")
        lines.append(_kv("Total Queries",  total, "100%"))
        lines.append(_kv("No Error",       s.get("no_error", 0),       _pct(s.get("no_error",0), total)))
        lines.append(_kv("Server Failure", s.get("server_failure", 0), _pct(s.get("server_failure",0), total)))
        lines.append(_kv("NX Domain",      s.get("nx_domain", 0),      _pct(s.get("nx_domain",0), total)))
        lines.append(_kv("Refused",        s.get("refused", 0),        _pct(s.get("refused",0), total)))
        lines.append(_kv("Authoritative",  s.get("authoritative", 0),  _pct(s.get("authoritative",0), total)))
        lines.append(_kv("Recursive",      s.get("recursive", 0),      _pct(s.get("recursive",0), total)))
        lines.append(_kv("Cached",         s.get("cached", 0),         _pct(s.get("cached",0), total)))
        lines.append(_kv("Blocked",        s.get("blocked", 0),        _pct(s.get("blocked",0), total)))
        lines.append(_kv("Dropped",        s.get("dropped", 0),        _pct(s.get("dropped",0), total)))
        lines.append(_kv("Clients",        s.get("clients", 0)))
        lines.append(_kv("Allowed",        s.get("allowed", max(0,total - s.get('blocked',0)))))
        return "\n".join(lines), None

    # Not a DNS command → let other routers try
    return None
