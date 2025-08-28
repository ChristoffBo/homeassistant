import os
import re
import threading
import base64
import requests
from typing import Optional, Tuple, Dict, Any

# =============================
# Config (env set by run.sh)
# =============================
TECH_URL  = (os.getenv("technitium_url", "") or "").rstrip("/")
TECH_KEY  = os.getenv("technitium_api_key", "") or ""
TECH_USER = os.getenv("technitium_user", "") or ""
TECH_PASS = os.getenv("technitium_pass", "") or ""
ENABLED   = os.getenv("technitium_enabled", "false").strip().lower() in ("1","true","yes")

_session = requests.Session()
_token_lock = threading.RLock()
_token_value: Optional[str] = None  # api key or login token

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
    """Technitium v13+: /api/user/login (fields: user, pass) -> token"""
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
    """Robust request wrapper: try header/query/basic combinations."""
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
# Stats (Dashboard JSON preferred)
# =============================
def _read_stats() -> Optional[dict]:
    j = _get("/api/dashboard/stats/get")
    if not isinstance(j, dict):
        return None

    src: Dict[str, Any] = {}
    if j.get("status") == "ok" and isinstance(j.get("response"), dict):
        src = j["response"].get("stats") or {}
    else:
        src = j.get("stats", {})

    out = {
        "total":            int(src.get("totalQueries", 0) or 0),
        "no_error":         int(src.get("totalNoError", 0) or 0),
        "server_failure":   int(src.get("totalServerFailure", 0) or 0),
        "nx_domain":        int(src.get("totalNxDomain", 0) or 0),
        "refused":          int(src.get("totalRefused", 0) or 0),
        "authoritative":    int(src.get("totalAuthoritative", 0) or 0),
        "recursive":        int(src.get("totalRecursive", 0) or 0),
        "cached":           int(src.get("totalCached", 0) or 0),
        "blocked":          int(src.get("totalBlocked", 0) or 0),
        "dropped":          int(src.get("totalDropped", 0) or 0),
        "clients":          int(src.get("totalClients", 0) or 0),
        "zones":            int(src.get("zones", 0) or 0),
        "cachedEntries":    int(src.get("cachedEntries", 0) or 0),
        "allowedZones":     int(src.get("allowedZones", 0) or 0),
        "blockedZones":     int(src.get("blockedZones", 0) or 0),
        "allowListZones":   int(src.get("allowListZones", 0) or 0),
        "blockListZones":   int(src.get("blockListZones", 0) or 0),
    }

    out["allowed"] = max(0, out["total"] - out["blocked"])

    if out["total"] == 0 and not any(v > 0 for k, v in out.items() if k != "total"):
        return None

    return out

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
        lines.append(_kv("No Error",       s["no_error"],       _pct(s["no_error"], total)))
        lines.append(_kv("Server Failure", s["server_failure"], _pct(s["server_failure"], total)))
        lines.append(_kv("NX Domain",      s["nx_domain"],      _pct(s["nx_domain"], total)))
        lines.append(_kv("Refused",        s["refused"],        _pct(s["refused"], total)))
        lines.append(_kv("Authoritative",  s["authoritative"],  _pct(s["authoritative"], total)))
        lines.append(_kv("Recursive",      s["recursive"],      _pct(s["recursive"], total)))
        lines.append(_kv("Cached",         s["cached"],         _pct(s["cached"], total)))
        lines.append(_kv("Blocked",        s["blocked"],        _pct(s["blocked"], total)))
        lines.append(_kv("Dropped",        s["dropped"],        _pct(s["dropped"], total)))
        lines.append(_kv("Clients",        s["clients"]))
        lines.append(_kv("Allowed",        s["allowed"]))
        lines.append("")
        lines.append("🧠 Resolver — Details")
        lines.append(_kv("Zones",          s["zones"]))
        lines.append(_kv("Cached Entries", s["cachedEntries"]))
        lines.append(_kv("Allowed Zones",  s["allowedZones"]))
        lines.append(_kv("Blocked Zones",  s["blockedZones"]))
        lines.append(_kv("Allow-List Zones", s["allowListZones"]))
        lines.append(_kv("Block-List Zones", s["blockListZones"]))
        return "\n".join(lines), None

    return None

# =============================
# Public helpers for other modules
# =============================
def stats(options: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    try:
        s = _read_stats()
        if not isinstance(s, dict):
            return {}
        return {
            "total_queries":        int(s.get("total", 0)),
            "blocked_total":        int(s.get("blocked", 0)),
            "server_failure_total": int(s.get("server_failure", 0)),
        }
    except Exception:
        return {}

def brief(options: Optional[Dict[str, Any]] = None) -> str:
    try:
        st = stats(options) or {}
        def fmt_i(v):
            try:
                return f"{int(v):,}"
            except Exception:
                return str(v)
        total = fmt_i(st.get("total_queries", 0))
        blocked = fmt_i(st.get("blocked_total", 0))
        servfail = fmt_i(st.get("server_failure_total", 0))
        return f"Total: {total} | Blocked: {blocked} | Server Failure: {servfail}"
    except Exception:
        return ""
