import os
import json
import re
import threading
import base64
import requests
from typing import Optional, Tuple

# =============================
# Config (set via run.sh env)
# =============================
TECH_URL  = (os.getenv("technitium_url", "") or "").rstrip("/")
TECH_KEY  = os.getenv("technitium_api_key", "") or ""
TECH_USER = os.getenv("technitium_user", "") or ""
TECH_PASS = os.getenv("technitium_pass", "") or ""
ENABLED   = os.getenv("technitium_enabled", "false").strip().lower() in ("1","true","yes")

# =============================
# Shared session + token cache
# =============================
_session = requests.Session()
_token_lock = threading.RLock()
_token_value: Optional[str] = None  # runtime token (api key or login token)

def _set_token(tok: Optional[str]) -> None:
    global _token_value
    with _token_lock:
        _token_value = tok

def _get_token() -> Optional[str]:
    with _token_lock:
        return _token_value

# =============================
# Auth helpers
# =============================
def _basic_auth_header() -> Optional[str]:
    if TECH_USER and TECH_PASS:
        raw = f"{TECH_USER}:{TECH_PASS}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")
    return None

def _auth_headers(token: Optional[str], variant: str) -> dict:
    """
    Build headers for a given variant:
      variant 'both'  -> Bearer + X-Auth-Token
      variant 'bearer'-> Bearer only
      variant 'xauth' -> X-Auth-Token only
      variant 'none'  -> no token headers
    Basic-Auth is added opportunistically when user/pass is present.
    """
    hdrs = {}
    if token:
        if variant == "both":
            hdrs["Authorization"] = f"Bearer {token}"
            hdrs["X-Auth-Token"] = token
        elif variant == "bearer":
            hdrs["Authorization"] = f"Bearer {token}"
        elif variant == "xauth":
            hdrs["X-Auth-Token"] = token

    # Some self-host setups accept Basic for login-protected endpoints.
    ba = _basic_auth_header()
    if ba:
        hdrs.setdefault("Authorization", ba)  # don't overwrite Bearer if set
    return hdrs

def _append_token_query(url: str, token: Optional[str]) -> str:
    if token and "token=" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}token={token}"
    return url

def _try_login_for_token() -> Optional[str]:
    """
    Login with username/password to obtain a token (v13+).
    Endpoint: POST /api/user/login -> {"status":"ok","token":"..."}
    Stores token for subsequent requests.
    """
    if not (TECH_URL and TECH_USER and TECH_PASS):
        return None
    try:
        r = _session.post(
            f"{TECH_URL}/api/user/login",
            data={"username": TECH_USER, "password": TECH_PASS},
            timeout=8,
        )
        if r.headers.get("content-type", "").startswith("application/json"):
            j = r.json()
        else:
            try:
                j = r.json()
            except Exception:
                j = {}
        tok = (j or {}).get("token")
        if (j or {}).get("status") == "ok" and tok:
            _set_token(tok)
            return tok
    except Exception:
        pass
    return None

def _ensure_token() -> Optional[str]:
    """
    Priority:
      1) API key if provided
      2) Cached token
      3) Login with user/pass (if present)
    """
    if TECH_KEY:
        _set_token(TECH_KEY)
        return TECH_KEY
    tok = _get_token()
    if tok:
        return tok
    return _try_login_for_token()

# =============================
# Robust request wrapper
# =============================
def _request(method: str, path: str, *, data=None, timeout: int = 8):
    """
    Try several auth combinations to maximize compatibility across
    Technitium builds and proxies.
    Order:
      (A) token from _ensure_token()
          1. header both + query
          2. header bearer only
          3. header xauth only
          4. query only
      (B) if unauthorized → attempt login token then repeat (A)
      (C) final fallback: Basic only (if set), no token
    Returns JSON (dict) when possible, otherwise text, or {"error": "..."}.
    """
    if not TECH_URL:
        return {"error": "Technitium URL not configured"}

    def _do(url, headers):
        try:
            if method == "GET":
                resp = _session.get(url, headers=headers, timeout=timeout)
            else:
                # Prefer JSON for newer endpoints; form is okay too
                resp = _session.post(url, headers=headers, data=(data or {}), timeout=timeout)
        except Exception as e:
            return None, {"error": str(e)}

        # Try to parse JSON; otherwise return text
        payload = None
        if resp.headers.get("content-type", "").startswith("application/json"):
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

    # (A) token we already have (key or cached/login)
    token = _ensure_token()
    variants = [
        ("both", True),    # both headers + ?token=
        ("bearer", False),
        ("xauth", False),
        ("none", True),    # query only
    ]

    # helper to run all variants once with a given token
    def _run_variants(tok: Optional[str]):
        last_payload = None
        last_status = None
        for v, add_q in variants:
            url = f"{TECH_URL}{path}"
            if add_q:
                url = _append_token_query(url, tok)
            headers = _auth_headers(tok, v)
            resp, payload = _do(url, headers)
            last_payload = payload
            last_status = getattr(resp, "status_code", None)

            # Consider success on 2xx
            if resp is not None and 200 <= resp.status_code < 300:
                return payload
            # Some endpoints return {"status":"ok"} with 200/204
            if isinstance(payload, dict) and str(payload.get("status","")).lower() in ("ok","success"):
                return payload
            # If explicit unauthorized, try next plan
            if resp is not None and resp.status_code in (401, 403):
                continue
        return (last_status, last_payload)

    # First pass with whatever token we have
    status_payload = _run_variants(token)
    if not isinstance(status_payload, tuple):
        return status_payload  # success

    status_code, last_payload = status_payload

    # (B) If unauthorized → try to login and repeat
    if status_code in (401, 403) or (isinstance(last_payload, dict) and last_payload.get("error")):
        new_tok = _try_login_for_token()
        if new_tok and new_tok != token:
            status_payload = _run_variants(new_tok)
            if not isinstance(status_payload, tuple):
                return status_payload  # success

            status_code, last_payload = status_payload

    # (C) Fallback: Basic only, no token
    if TECH_USER and TECH_PASS:
        url = f"{TECH_URL}{path}"
        headers = {}
        ba = _basic_auth_header()
        if ba:
            headers["Authorization"] = ba
        resp, payload = _do(url, headers)
        if resp is not None and 200 <= resp.status_code < 300:
            return payload
        last_payload = payload

    # Still no luck
    return last_payload if last_payload is not None else {"error": "request failed"}

# Convenience wrappers
def _get(path: str, timeout: int = 8):
    return _request("GET", path, timeout=timeout)

def _post(path: str, data=None, timeout: int = 8):
    return _request("POST", path, data=data, timeout=timeout)

# =============================
# Stats + Flush
# =============================
_DASH_KEYS = {
    "total": [
        "TotalQueryCount", "totalQueries", "dnsQueryCount",
        "queries", "total", "dns_queries_total"
    ],
    "no_error": [
        "NoErrorCount", "noError", "okCount", "no_error"
    ],
    "server_failure": [
        "ServerFailureCount", "servfail", "serverFailure"
    ],
    "nx_domain": [
        "NXDomainCount", "nxDomain", "nxdomain"
    ],
    "refused": [
        "RefusedCount", "refused"
    ],
    "authoritative": [
        "AuthoritativeCount", "authoritative"
    ],
    "recursive": [
        "RecursiveCount", "recursive"
    ],
    "cached": [
        "CacheCount", "cacheCount", "cacheSize", "cached"
    ],
    "blocked": [
        "BlockedQueryCount", "blockedQueries", "blocked"
    ],
    "dropped": [
        "DroppedCount", "dropped"
    ],
    "clients": [
        "UniqueClientCount", "clients", "uniqueClients"
    ],
}

def _pick_num(d: dict, keys) -> int:
    for k in keys:
        if k in d and isinstance(d[k], (int, float)):
            return int(d[k])
    return 0

def _read_stats() -> Optional[dict]:
    """
    v13+: /api/dashboard/stats/get → {"status":"ok","response":{...}}
    Fallback: /metrics (Prometheus text)
    Returns dict with all dashboard fields.
    """
    # JSON dashboard
    j = _get("/api/dashboard/stats/get")
    if isinstance(j, dict) and (j.get("status") == "ok" or "response" in j or "TotalQueryCount" in j):
        src = j.get("response", j)
        out = {}
        for label, keys in _DASH_KEYS.items():
            out[label] = _pick_num(src, keys)

        # If everything is zero, probe nested objects once
        if sum(out.values()) == 0:
            for v in src.values():
                if isinstance(v, dict):
                    for label, keys in _DASH_KEYS.items():
                        out[label] = out[label] or _pick_num(v, keys)

        # Derived: allowed = total - blocked
        out["allowed"] = max(0, out.get("total", 0) - out.get("blocked", 0))
        return out

    # Prometheus fallback
    text = _get("/metrics")
    if isinstance(text, str) and text.strip():
        pat = re.compile(r"^\s*([a-zA-Z_:][a-zA-Z0-9_:]*)\s*(?:\{[^}]*\})?\s+([0-9]+(?:\.[0-9]+)?)\s*$")
        vals = {k: 0 for k in _DASH_KEYS.keys()}
        for line in text.splitlines():
            m = pat.match(line)
            if not m:
                continue
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
            # Best-effort heuristics for others if present in metrics exposition:
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

        vals["allowed"] = max(0, vals["total"] - vals["blocked"])
        return vals

    return None

def _flush_cache() -> Tuple[bool, Optional[object]]:
    """
    v13+: POST /api/cache/flush → {"status":"ok"}
    Also try legacy paths for older builds.
    """
    for path in ("/api/cache/flush", "/api/flushDnsCache", "/api/dns/cache/flush", "/api/dns/flushcache"):
        resp = _post(path)
        if isinstance(resp, dict) and str(resp.get("status", "")).lower() in ("ok", "success"):
            return True, resp
        if isinstance(resp, str) and re.search(r"\bok\b|\bsuccess\b|\bflushed\b", resp, re.I):
            return True, resp
    return False, None

# =============================
# Public router
# =============================
def _kv(label, value):
    return f"    {label}: {value:,}" if isinstance(value, int) else f"    {label}: {value}"

def handle_dns_command(cmd: str):
    """
    Voice commands (triggered by bot.py):
      • 'dns' / 'dns status' / 'DNS status'
      • 'dns flush' / 'DNS flush'
    """
    if not ENABLED or not TECH_URL:
        return "⚠️ DNS module not enabled or misconfigured", None

    c = (cmd or "").strip().lower()

    if c == "dns" or c.startswith("dns status"):
        s = _read_stats()
        if not s:
            return "⚠️ Could not read DNS stats", None

        # Pretty dashboard-style output
        lines = []
        lines.append("🌐 Technitium DNS — Stats\n")
        lines.append(_kv("Total Queries",  s.get("total", 0)))
        lines.append(_kv("No Error",       s.get("no_error", 0)))
        lines.append(_kv("Server Failure", s.get("server_failure", 0)))
        lines.append(_kv("NX Domain",      s.get("nx_domain", 0)))
        lines.append(_kv("Refused",        s.get("refused", 0)))
        lines.append(_kv("Authoritative",  s.get("authoritative", 0)))
        lines.append(_kv("Recursive",      s.get("recursive", 0)))
        lines.append(_kv("Cached",         s.get("cached", 0)))
        lines.append(_kv("Blocked",        s.get("blocked", 0)))
        lines.append(_kv("Dropped",        s.get("dropped", 0)))
        lines.append(_kv("Clients",        s.get("clients", 0)))
        lines.append(_kv("Allowed",        s.get("allowed", max(0, s.get("total", 0) - s.get("blocked", 0)))))
        return "\n".join(lines), None

    if c.startswith("dns flush"):
        ok, _ = _flush_cache()
        return ("🌐 DNS cache flushed successfully" if ok else "⚠️ DNS cache flush failed"), None

    # Not a DNS command → let other routers try
    return None
