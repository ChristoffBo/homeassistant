#!/usr/bin/env python3
# /app/ntfy_client.py — header-safe (Latin-1) + body-safe (UTF-8, no leading whitespace bug)

from __future__ import annotations
import os, json, requests
from typing import Optional, Dict, Any, Union

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
def _safe_header(val: Union[str, bytes, None]) -> str:
    """
    Make a value safe for HTTP headers.
    urllib3/requests encodes headers as ISO-8859-1 (latin-1).
    Strip CR/LF, leading spaces, and drop any chars not representable in latin-1.
    """
    if val is None:
        return ""
    if isinstance(val, bytes):
        try:
            s = val.decode("utf-8", errors="replace")
        except Exception:
            s = val.decode("latin-1", errors="replace")
    else:
        s = str(val)
    # headers cannot contain raw newlines or leading spaces
    s = s.replace("\r", " ").replace("\n", " ").lstrip()
    # force latin-1 safety: drop characters outside latin-1
    s = s.encode("latin-1", errors="ignore").decode("latin-1", errors="ignore")
    return s

def _safe_body_bytes(val: Union[str, bytes, None]) -> bytes:
    """
    UTF-8 body with replacement is OK for ntfy message content.
    """
    if val is None:
        return b""
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", errors="replace").encode("utf-8", errors="replace")
        except Exception:
            return val
    return str(val).encode("utf-8", errors="replace")

def _auth_headers() -> Dict[str, str]:
    h: Dict[str, str] = {}
    if NTFY_TOKEN:
        h["Authorization"] = f"Bearer {_safe_header(NTFY_TOKEN)}"
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
    Publish to an ntfy topic via HTTP POST with header/body encodings handled safely:
    - Headers: Latin-1 safe (no emojis, no leading spaces)
    - Body: UTF-8 safe (emojis preserved)
    """
    base = NTFY_URL or "https://ntfy.sh"
    t = topic or (NTFY_TOPIC or "jarvis")
    url = f"{base}/{t}"

    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        **_auth_headers(),
    }

    # Header metadata — must be latin-1 safe (no emojis or leading spaces)
    if title:
        headers["Title"] = _safe_header(title)
    if click:
        headers["X-Click"] = _safe_header(click)
    if tags:
        headers["X-Tags"] = _safe_header(tags)
    if priority is not None:
        headers["X-Priority"] = _safe_header(str(priority))
    if attach:
        headers["X-Attach"] = _safe_header(attach)

    data = _safe_body_bytes(message)

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
        try:
            err = str(e).encode("utf-8", errors="replace").decode("utf-8")
        except Exception:
            err = "unknown error"
        print(f"[ntfy] push failed (header-safe): {err}")
        return {"error": err}

# -----------------------------
# CLI quick test
# -----------------------------
if __name__ == "__main__":
    res = publish("Jarvis test 🚀", "Hello from ntfy_client.py ✅ — UTF-8 body 💡", tags="robot,jarvis", priority=3)
    print(json.dumps(res, indent=2, ensure_ascii=False))