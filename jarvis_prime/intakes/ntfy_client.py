#!/usr/bin/env python3
# /app/ntfy_client.py — FINAL: local file upload + image link preview + UTF-8 safety

from __future__ import annotations
import os, json, requests, mimetypes
from typing import Optional, Dict, Any, Union
from urllib.parse import urlparse

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
    """Make a value safe for HTTP headers (latin-1 safe, no CR/LF/whitespace)."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        try:
            s = val.decode("utf-8", errors="replace")
        except Exception:
            s = val.decode("latin-1", errors="replace")
    else:
        s = str(val)
    s = s.replace("\r", " ").replace("\n", " ").strip()
    s = s.encode("latin-1", errors="ignore").decode("latin-1", errors="ignore")
    return s

def _safe_body_bytes(val: Union[str, bytes, None]) -> bytes:
    """UTF-8 body (emojis preserved)."""
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

def _is_image_url(url: str) -> bool:
    """Detect if an attachment URL points to an image."""
    if not url:
        return False
    parsed = urlparse(url.lower())
    return any(parsed.path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))

def _upload_local_file(path: str) -> Optional[str]:
    """Upload a local file to ntfy and return its public URL."""
    if not os.path.exists(path):
        print(f"[ntfy] Local file not found: {path}")
        return None
    url = f"{NTFY_URL or 'https://ntfy.sh'}/file"
    headers = _auth_headers()
    mime_type, _ = mimetypes.guess_type(path)
    try:
        with open(path, "rb") as f:
            r = _session.post(url, headers=headers, files={"file": (os.path.basename(path), f, mime_type or "application/octet-stream")}, timeout=15)
        r.raise_for_status()
        data = r.json()
        file_url = data.get("url")
        print(f"[ntfy] Uploaded local file → {file_url}")
        return file_url
    except Exception as e:
        print(f"[ntfy] Upload failed: {e}")
        return None

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
    Publish to an ntfy topic:
    - Local files auto-uploaded to ntfy and turned into shareable links
    - Image URLs auto-previewed via clickable link
    - Full UTF-8 + Latin-1 safety
    """
    base = NTFY_URL or "https://ntfy.sh"
    t = topic or (NTFY_TOPIC or "jarvis")
    url = f"{base}/{t}"

    headers: Dict[str, str] = {
        "Content-Type": "text/plain; charset=utf-8",
        **_auth_headers(),
    }

    attach_url = None
    if attach:
        # If it's a local path, upload first
        if os.path.isfile(attach):
            uploaded = _upload_local_file(attach)
            if uploaded:
                attach_url = uploaded
        else:
            attach_url = attach

    if title:
        headers["Title"] = _safe_header(title)
    if click:
        headers["X-Click"] = _safe_header(click)
    if tags:
        headers["X-Tags"] = _safe_header(tags)
    if priority is not None:
        headers["X-Priority"] = _safe_header(str(priority))
    if attach_url:
        headers["X-Attach"] = _safe_header(attach_url)

    msg_text = str(message or "")
    if attach_url and _is_image_url(attach_url) and attach_url not in msg_text:
        msg_text += f"\n\n📸 Image: {attach_url}"

    data = _safe_body_bytes(msg_text)

    try:
        r = _session.post(
            url,
            headers=headers,
            data=data,
            auth=(NTFY_USER, NTFY_PASS) if (NTFY_USER or NTFY_PASS) else None,
            timeout=10,
        )
        try:
            j = r.json()
        except Exception:
            j = {}
        return {"status": r.status_code, **({"id": j.get("id")} if isinstance(j, dict) else {})}
    except Exception as e:
        err = str(e).encode("utf-8", errors="replace").decode("utf-8")
        print(f"[ntfy] push failed (header-safe): {err}")
        return {"error": err}

# -----------------------------
# CLI quick test
# -----------------------------
if __name__ == "__main__":
    # Will upload a local image or use link if provided
    test_file = "/share/jarvis_prime/images/test.png"
    res = publish(
        "Jarvis test 🚀",
        "Hello from ntfy_client.py ✅ — now with local upload 💡",
        tags="robot,jarvis",
        priority=3,
        attach=test_file
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))