#!/usr/bin/env python3
# /app/ntfy.py — UTF-8 safe ntfy publisher for Jarvis Prime
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
    """Return Authorization header if token is set."""
    h: Dict[str, str] = {}
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
    """
    Publish to an ntfy topic via HTTP POST.
    This version is fully UTF-8 safe and never throws Latin-1 encoding errors.
    Docs: https://docs.ntfy.sh/publish/
    """
    base = NTFY_URL or "https://ntfy.sh"
    t = topic or (NTFY_TOPIC or "jarvis")
    url = f"{base}/{t}"
    headers = _auth_headers()

    # -----------------------------
    # Metadata headers (force UTF-8)
    # -----------------------------
    if title:
        # Normalize to valid UTF-8, replacing any bad bytes safely
        title = title.encode("utf-8", errors="replace").decode("utf-8")
        headers["Title"] = title
    if click:
        headers["X-Click"] = click
    if tags:
        headers["X-Tags"] = tags
    if priority is not None:
        headers["X-Priority"] = str(priority)
    if attach:
        headers["X-Attach"] = attach

    # -----------------------------
    # Message body (UTF-8 strict)
    # -----------------------------
    utf8_message = (message or "").encode("utf-8", errors="replace")
    headers["Content-Type"] = "text/plain; charset=utf-8"

    # -----------------------------
    # Send POST
    # -----------------------------
    try:
        if NTFY_USER or NTFY_PASS:
            r = _session.post(
                url,
                headers=headers,
                data=utf8_message,
                auth=(NTFY_USER, NTFY_PASS),
                timeout=8,
            )
        else:
            r = _session.post(url, headers=headers, data=utf8_message, timeout=8)

        # Attempt to parse JSON response
        try:
            j = r.json()
        except Exception:
            j = {}

        return {
            "status": r.status_code,
            **({"id": j.get("id")} if isinstance(j, dict) else {}),
        }

    except Exception as e:
        # Explicitly log the failure with safe UTF-8 output
        print(f"[ntfy] push failed: {str(e)}")
        return {"error": str(e)}


# -----------------------------
# CLI quick test
# -----------------------------
if __name__ == "__main__":
    res = publish(
        "Jarvis test 🚀",
        "Hello from ntfy_client.py ✅ — UTF-8 verified with emoji 🌍🔥",
        tags="robot",
        priority=3,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))