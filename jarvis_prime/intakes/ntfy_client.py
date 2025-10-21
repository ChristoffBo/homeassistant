#!/usr/bin/env python3
# /app/ntfy.py — UTF-8 safe notification client

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
# Publish (UTF-8 safe)
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
    """Publish to an ntfy topic via HTTP POST."""
    base = NTFY_URL or "https://ntfy.sh"
    t = topic or (NTFY_TOPIC or "jarvis")
    url = f"{base}/{t}"
    headers = _auth_headers()

    # Metadata headers (UTF-8 safe)
    if title:
        headers["Title"] = str(title).encode("utf-8", errors="replace").decode("utf-8")
    if click:
        headers["X-Click"] = str(click)
    if tags:
        headers["X-Tags"] = str(tags)
    if priority is not None:
        headers["X-Priority"] = str(priority)
    if attach:
        headers["X-Attach"] = str(attach)
    headers["Content-Type"] = "text/plain; charset=utf-8"

    # Encode message body to UTF-8
    data = (message or "").encode("utf-8", errors="replace")

    try:
        r = _session.post(
            url,
            headers=headers,
            data=data,
            auth=(NTFY_USER, NTFY_PASS) if (NTFY_USER or NTFY_PASS) else None,
            timeout=8,
        )
        try:
            j = r.json()
        except Exception:
            j = {}
        return {"status": r.status_code, **({"id": j.get("id")} if isinstance(j, dict) else {})}
    except Exception as e:
        # Ensure even this log prints safely
        print(f"[ntfy] push failed (UTF-8 safe): {str(e).encode('utf-8', errors='replace').decode('utf-8')}")
        return {"error": str(e)}


# -----------------------------
# CLI quick test
# -----------------------------
if __name__ == "__main__":
    res = publish("Jarvis test 🚀", "Hello from ntfy_client.py ✅ — UTF-8 verified 💡", tags="robot", priority=3)
    print(json.dumps(res, indent=2, ensure_ascii=False))