#!/usr/bin/env python3
from __future__ import annotations
import os, json, requests
from typing import Optional, Dict, Any

NTFY_URL   = (os.getenv("NTFY_URL", "") or "").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "jarvis")
NTFY_USER  = os.getenv("NTFY_USER", "")
NTFY_PASS  = os.getenv("NTFY_PASS", "")
NTFY_TOKEN = os.getenv("NTFY_TOKEN", "")

_session = requests.Session()

def _auth_headers() -> Dict[str,str]:
    h = {}
    if NTFY_TOKEN:
        h["Authorization"] = f"Bearer {NTFY_TOKEN}"
    return h

def publish(title: str, message: str, *, topic: Optional[str] = None,
            click: Optional[str] = None, tags: Optional[str] = None) -> Dict[str, Any]:
    """
    Publish to ntfy topic via HTTP POST (docs: https://docs.ntfy.sh/publish/).
    Returns dict: {"status": http_status, "id": "..."} or {"error": "..."}.
    """
    base = NTFY_URL or "https://ntfy.sh"
    t = topic or (NTFY_TOPIC or "jarvis")
    url = f"{base}/{t}"
    headers = _auth_headers()
    data = {"title": title or "", "message": message or ""}
    if click: headers["X-Click"] = click
    if tags:  headers["X-Tags"] = tags
    try:
        if NTFY_USER or NTFY_PASS:
            r = _session.post(url, headers=headers, data=data, auth=(NTFY_USER, NTFY_PASS), timeout=8)
        else:
            r = _session.post(url, headers=headers, data=data, timeout=8)
        try:
            j = r.json()
        except Exception:
            j = {}
        return {"status": r.status_code, **({"id": j.get("id")} if isinstance(j, dict) else {})}
    except Exception as e:
        return {"error": str(e)}
