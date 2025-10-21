#!/usr/bin/env python3
# /app/ntfy.py — FINAL UTF-8-SAFE VERSION (handles latin-1, bytes, emojis)

from __future__ import annotations
import os, json, requests
from typing import Optional, Dict, Any

NTFY_URL   = (os.getenv("NTFY_URL", "") or "").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "jarvis")
NTFY_USER  = os.getenv("NTFY_USER", "")
NTFY_PASS  = os.getenv("NTFY_PASS", "")
NTFY_TOKEN = os.getenv("NTFY_TOKEN", "")

_session = requests.Session()

# -----------------------------
# Helpers
# -----------------------------
def _safe_str(val: Any) -> str:
    """Return a clean UTF-8-safe string no matter the input type."""
    try:
        if isinstance(val, bytes):
            # Try UTF-8 first; fall back to latin-1
            try:
                return val.decode("utf-8")
            except UnicodeDecodeError:
                return val.decode("latin-1", errors="replace")
        return str(val)
    except Exception:
        return "(invalid string)"

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
    """Publish to an ntfy topic via HTTP POST (fully UTF-8 safe)."""
    base = NTFY_URL or "https://ntfy.sh"
    t = topic or (NTFY_TOPIC or "jarvis")
    url = f"{base}/{t}"
    headers = _auth_headers()

    # --- Sanitize metadata headers
    headers["Title"] = _safe_str(title)
    if click:
        headers["X-Click"] = _safe_str(click)
    if tags:
        headers["X-Tags"] = _safe_str(tags)
    if priority is not None:
        headers["X-Priority"] = str(priority)
    if attach:
        headers["X-Attach"] = _safe_str(attach)
    headers["Content-Type"] = "text/plain; charset=utf-8"

    # --- Sanitize body
    msg = _safe_str(message)
    data = msg.encode("utf-8", errors="replace")

    # --- Send
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
        safe_err = _safe_str(e)
        print(f"[ntfy] push failed (UTF-8 safe): {safe_err}")
        return {"error": safe_err}

# -----------------------------
# CLI quick test
# -----------------------------
if __name__ == "__main__":
    res = publish("Jarvis test 🚀", "Hello from ntfy.py ✅ — UTF-8 verified 💡", tags="robot", priority=3)
    print(json.dumps(res, indent=2, ensure_ascii=False))