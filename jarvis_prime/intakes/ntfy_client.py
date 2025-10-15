#!/usr/bin/env python3
from __future__ import annotations
import os, json, requests
from typing import Optional, Dict, Any

# -----------------------------
# Environment / Config
# -----------------------------
NTFY_URL   = (os.getenv("NTFY_URL", "") or "").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "jarvis")
NTFY_USER  = os.getenv("NTFY_USER", "")
NTFY_PASS  = os.getenv("NTFY_PASS", "")
NTFY_TOKEN = os.getenv("NTFY_TOKEN", "")

_session = requests.Session()

# -----------------------------
# Helpers
# -----------------------------
def _auth_headers() -> Dict[str, str]:
    h = {}
    if NTFY_TOKEN:
        h["Authorization"] = f"Bearer {NTFY_TOKEN}"
    return h


# -----------------------------
# Publish
# -----------------------------
def publish(
    title: str,
    message: str,
    *,
    topic: Optional[str] = None,
    click: Optional[str] = None,
    tags: Optional[str] = None,
    priority: Optional[int] = None,
    attach: Optional[str] = None
) -> Dict[str, Any]:
    """
    Publish to an ntfy topic via HTTP POST.
    Docs: https://docs.ntfy.sh/publish/

    Args:
        title: Notification title
        message: Notification message
        topic: Optional override for the topic
        click: Optional click URL
        tags: Comma-separated emoji tags or icons
        priority: 1–5 (low→max)
        attach: URL or file path to attach

    Returns:
        dict: {"status": http_status, "id": "..."} or {"error": "..."}
    """
    base = NTFY_URL or "https://ntfy.sh"
    t = topic or (NTFY_TOPIC or "jarvis")
    url = f"{base}/{t}"
    headers = _auth_headers()
    data = {"title": title or "", "message": message or ""}

    if click:
        headers["X-Click"] = click
    if tags:
        headers["X-Tags"] = tags
    if priority is not None:
        headers["X-Priority"] = str(priority)
    if attach:
        headers["X-Attach"] = attach

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


# -----------------------------
# CLI quick test (optional)
# -----------------------------
if __name__ == "__main__":
    res = publish("Jarvis test", "Hello from ntfy.py", tags="robot", priority=3)
    print(json.dumps(res, indent=2))