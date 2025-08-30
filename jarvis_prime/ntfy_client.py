#!/usr/bin/env python3
# /app/ntfy_client.py — tiny publisher for ntfy (self-hosted or ntfy.sh)
import os, base64, requests
from typing import Optional, Dict, Any

NTFY_URL   = (os.getenv("NTFY_URL","") or "").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC","") or ""
NTFY_USER  = os.getenv("NTFY_USER","") or ""
NTFY_PASS  = os.getenv("NTFY_PASS","") or ""
NTFY_TOKEN = os.getenv("NTFY_TOKEN","") or ""
NTFY_ENABLED = (os.getenv("NTFY_ENABLED","false").strip().lower() in ("1","true","yes"))

_session = requests.Session()

def _headers(priority: int = 3, tags: Optional[str] = None, extras: Optional[Dict[str,Any]] = None):
    h = {"X-Priority": str(priority)}
    if tags: h["X-Tags"] = tags
    if NTFY_TOKEN:
        h["Authorization"] = f"Bearer {NTFY_TOKEN}"
    elif NTFY_USER and NTFY_PASS:
        tok = base64.b64encode(f"{NTFY_USER}:{NTFY_PASS}".encode("utf-8")).decode("ascii")
        h["Authorization"] = "Basic " + tok
    if extras:
        try:
            # Attach extras as json in a custom header (visible in payload in some clients)
            import json as _json
            h["X-Attachments"] = _json.dumps(extras)[:1500]
        except Exception:
            pass
    return h

def publish(title: str, message: str, priority: int = 3, tags: Optional[str] = None, extras=None) -> bool:
    if not NTFY_ENABLED or not NTFY_URL or not NTFY_TOPIC:
        return False
    try:
        url = f"{NTFY_URL}/{NTFY_TOPIC}"
        data = message or ""
        h = _headers(priority=priority, tags=tags, extras=extras)
        if title: h["Title"] = title
        r = _session.post(url, data=data.encode("utf-8"), headers=h, timeout=8)
        return 200 <= r.status_code < 300
    except Exception:
        return False
