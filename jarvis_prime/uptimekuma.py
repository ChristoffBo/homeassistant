import os, requests, re
from typing import Tuple, Optional, Dict, Any, List

# --- Config via env (set by run.sh from options.json) ---
KUMA_URL  = (os.getenv("uptimekuma_url", "") or "").rstrip("/")
KUMA_KEY  = os.getenv("uptimekuma_api_key", "") or ""
ENABLED   = os.getenv("uptimekuma_enabled", "false").lower() in ("1", "true", "yes")

# OPTIONAL: if you use a Status Page "slug" in Kuma, set this env manually (not required):
# export uptimekuma_status_slug="public"
KUMA_SLUG = os.getenv("uptimekuma_status_slug", "").strip()

_DEF_TIMEOUT = 10

def _get_json(path: str, params: Optional[dict] = None) -> Any:
    """GET JSON with optional Bearer header; return dict/list or error str."""
    if not KUMA_URL:
        return {"error": "Kuma URL not configured"}
    try:
        url = f"{KUMA_URL}{path}"
        headers = {"Authorization": f"Bearer {KUMA_KEY}"} if KUMA_KEY else {}
        r = requests.get(url, headers=headers, params=params or {}, timeout=_DEF_TIMEOUT)
        if "application/json" in r.headers.get("content-type", ""):
            return r.json()
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code, "text": r.text}
    except Exception as e:
        return {"error": str(e)}

# --- Parsers for different Kuma JSON shapes ---
def _parse_summary(obj: Dict[str, Any]) -> Optional[List[Tuple[str, str]]]:
    """
    Expect a shape like: {"monitors":[{"name":"X","status":"up"|"down"|...}, ...]}
    Returns list of (name, status) or None if not matching.
    """
    mons = obj.get("monitors")
    if isinstance(mons, list):
        out = []
        for m in mons:
            name = str(m.get("name", "?"))
            status = str(m.get("status", "unknown")).lower()
            out.append((name, status))
        return out
    return None

def _parse_heartbeat(obj: Dict[str, Any]) -> Optional[List[Tuple[str, str]]]:
    """
    Some status pages expose {"heartbeatList": {"<id>":[{status:1|0|2, ...}, ...]}, "monitorList":[{id,name}, ...]}
    """
    hb = obj.get("heartbeatList")
    ml = obj.get("monitorList")
    if isinstance(hb, dict) and isinstance(ml, list):
        id_to_name = {str(m.get("id")): m.get("name", f"id:{m.get('id')}") for m in ml}
        out = []
        for mid, events in hb.items():
            if isinstance(events, list) and events:
                last = events[0]  # typically newest-first
                st_i = events[0].get("status")
                if st_i in (0, 1, 2):
                    status = {0: "down", 1: "up", 2: "pending"}.get(st_i, "unknown")
                else:
                    status = str(st_i or "unknown")
                out.append((id_to_name.get(str(mid), f"id:{mid}"), status))
        return out
    return None

def _status_icon(s: str) -> str:
    s = (s or "").lower()
    if s in ("up", "ok", "healthy", "operational", "online"):
        return "✅"
    if s in ("pending", "paused", "maintenance"):
        return "⏸"
    return "❌"

def _format_status_list(pairs: List[Tuple[str, str]]) -> str:
    lines = ["📡 Uptime Kuma — Status"]
    for name, status in pairs:
        lines.append(f"- {_status_icon(status)} {name}: {status}")
    return "\n".join(lines)

def _format_incidents(obj: Dict[str, Any]) -> Optional[str]:
    inc = obj.get("incidents")
    if isinstance(inc, list):
        if not inc:
            return "✅ No active incidents"
        out = ["🚨 Active Incidents:"]
        for i in inc:
            title = i.get("title", "?")
            st = i.get("status", "unknown")
            out.append(f"- {title} — {st}")
        return "\n".join(out)
    return None

# --- Public router used by bot.py ---
def handle_kuma_command(cmd: str):
    """
    Supports:
      • 'kuma status'     → list monitors up/down
      • 'kuma incidents'  → list active incidents (if configured in status page)
      • 'kuma summary'    → alias of status
    """
    if not ENABLED or not KUMA_URL:
        return "⚠️ Uptime Kuma not enabled or misconfigured", None

    c = (cmd or "").strip().lower()
    wants_status = ("kuma" in c and ("status" in c or "summary" in c))
    wants_incidents = ("kuma" in c and "incident" in c)

    # Try multiple endpoints for robustness (different Kuma setups)
    endpoints = []
    # Preferred public status page JSON (if you set a slug)
    if KUMA_SLUG:
        endpoints.extend([
            ("/api/status-page/summary", {"slug": KUMA_SLUG}),
            ("/api/status-page/heartbeat", {"slug": KUMA_SLUG}),
        ])
    # Generic endpoints some setups expose:
    endpoints.extend([
        ("/api/status-page/summary", None),
        ("/api/status-page/heartbeat", None)
    ])

    last_obj = None
    for path, params in endpoints:
        obj = _get_json(path, params=params)
        last_obj = obj
        if not isinstance(obj, (dict, list)):
            continue

        if isinstance(obj, dict):
            # Incidents request
            if wants_incidents:
                formatted = _format_incidents(obj)
                if formatted:
                    return formatted, None

            # Status request
            if wants_status:
                pairs = _parse_summary(obj)
                if not pairs:
                    pairs = _parse_heartbeat(obj)
                if pairs:
                    return _format_status_list(pairs), None

    if wants_incidents:
        return "⚠️ Could not read incidents (status page may be disabled or not public).", None
    if wants_status:
        hint = "" if KUMA_SLUG else "\n💡 Tip: set env `uptimekuma_status_slug` if you use a public status page."
        return f"⚠️ Could not read Kuma status.{hint}", None

    return None, None
