# /app/proxy.py
# Simple HTTP proxy/intake for Jarvis Prime.
#
# Endpoints:
#   POST /message?token=XXXX   -> 100% Gotify-compatible (Sonarr/Radarr plugins)
#   POST /gotify               -> JSON {title, message, priority?, extras?}
#   POST /ntfy                 -> text/plain or JSON {"title","message"} (basic)
#   GET  /health               -> 200 OK
#
# Behavior:
#   - Every inbound payload is beautified via beautify_message (Jarvis Card).
#   - Also forwards (best-effort) to real servers if configured:
#       proxy_gotify_url (full /message?token=... URL), proxy_ntfy_url
#   - Always 200 OK to the sender (logs errors).
#
from __future__ import annotations
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import requests

try:
    from beautify import beautify_message
except Exception:
    def beautify_message(title, body, **kwargs):
        return body, None  # soft fallback

class ProxyState:
    def __init__(self, config, send_cb):
        self.cfg = config
        self.send_cb = send_cb
        self.bind = str(config.get("proxy_bind", "0.0.0.0"))
        self.port = int(config.get("proxy_port", 8099))
        self.forward_gotify = (config.get("proxy_gotify_url") or "").strip()
        self.forward_ntfy = (config.get("proxy_ntfy_url") or "").strip()
        self.mood = str(config.get("personality_mood", "serious"))

STATE: ProxyState | None = None

def _json(data: dict, code: int = 200):
    return (code, "application/json; charset=utf-8", json.dumps(data).encode("utf-8"))

def _text(data: str, code: int = 200):
    return (code, "text/plain; charset=utf-8", data.encode("utf-8"))

def _merge_extras(a, b):
    if not a and not b:
        return None
    if not a:
        return b
    if not b:
        return a
    out = dict(a)
    ca = dict(out.get("client::notification", {}))
    cb = dict((b.get("client::notification") or {}))
    # Prefer image from A, else B
    if "bigImageUrl" not in ca and "bigImageUrl" in cb:
        ca["bigImageUrl"] = cb["bigImageUrl"]
    if ca:
        out["client::notification"] = ca
    for k, v in b.items():
        if k == "client::notification":
            continue
        out[k] = v
    return out

class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisProxy/1.1"

    def _send(self, tup):
        code, ctype, payload = tup
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/health"):
            self._send(_text("ok"))
            return
        self._send(_json({"error": "not found"}, 404))

    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b""
            path = self.path.split("?", 1)[0]

            if path == "/message":
                # Gotify compatible: /message?token=xxx  (token ignored here)
                self._handle_gotify_like(raw)
                return

            if path == "/gotify":
                self._handle_gotify_like(raw)
                return

            if path == "/ntfy":
                self._handle_ntfy(raw)
                return

            self._send(_json({"error": "unknown endpoint"}, 404))
        except Exception as e:
            self._send(_json({"error": str(e)}, 500))

    def _handle_gotify_like(self, raw: bytes):
        global STATE
        ctype = (self.headers.get("Content-Type") or "").lower()
        try:
            if "application/json" in ctype:
                payload = json.loads(raw.decode("utf-8", errors="ignore")) if raw else {}
            else:
                # some clients still send JSON but omit content-type
                payload = json.loads(raw.decode("utf-8", errors="ignore")) if raw else {}
        except Exception:
            payload = {}

        title = str(payload.get("title") or "Message")
        message = str(payload.get("message") or "")
        priority = int(payload.get("priority") or 5)
        extras = payload.get("extras") if isinstance(payload.get("extras"), dict) else None

        # Beautify + post into our Gotify via callback
        final, bx = beautify_message(title, message, mood=STATE.mood if STATE else "serious", source_hint="sonarr" if "sonarr" in (title + " " + message).lower() else None)
        merged_extras = _merge_extras(bx, extras)
        if STATE and STATE.send_cb:
            try:
                STATE.send_cb(title, final, priority=priority, extras=merged_extras)
            except Exception as e:
                print(f"[Proxy] ❌ local post error: {e}")

        # Optional forward to a real Gotify server
        if STATE and STATE.forward_gotify:
            try:
                r = requests.post(STATE.forward_gotify, json={"title": title, "message": message, "priority": priority, "extras": extras}, timeout=8)
                if not r.ok:
                    print(f"[Proxy] ⚠️ forward gotify failed: {r.status_code} {r.text[:200]}")
            except Exception as e:
                print(f"[Proxy] ⚠️ forward gotify error: {e}")

        self._send(_json({"status": "ok"}))

    def _handle_ntfy(self, raw: bytes):
        global STATE
        ctype = (self.headers.get("Content-Type") or "").lower()
        title = self.headers.get("Title") or "ntfy"
        priority = int(self.headers.get("Priority") or 5)
        text = ""

        if "application/json" in ctype:
            try:
                payload = json.loads(raw.decode("utf-8", errors="ignore"))
            except Exception:
                payload = {}
            title = payload.get("title") or title
            text = payload.get("message") or ""
        else:
            text = raw.decode("utf-8", errors="ignore")

        final, bx = beautify_message(title, text, mood=STATE.mood if STATE else "serious", source_hint="proxy")
        if STATE and STATE.send_cb:
            try:
                STATE.send_cb(title, final, priority=priority, extras=bx)
            except Exception as e:
                print(f"[Proxy] ❌ local post error: {e}")

        if STATE and STATE.forward_ntfy:
            try:
                headers = {}
                if title: headers["Title"] = str(title)
                if priority: headers["Priority"] = str(priority)
                r = requests.post(STATE.forward_ntfy, data=text.encode("utf-8"), headers=headers, timeout=8)
                if not r.ok:
                    print(f"[Proxy] ⚠️ forward ntfy failed: {r.status_code} {r.text[:200]}")
            except Exception as e:
                print(f"[Proxy] ⚠️ forward ntfy error: {e}")

        self._send(_json({"status": "ok"}))

def start_proxy(config, send_cb):
    global STATE
    STATE = ProxyState(config, send_cb)
    addr = (STATE.bind, STATE.port)
    print(f"[Jarvis Prime] 🔀 Proxy listening on {STATE.bind}:{STATE.port} (endpoints: /message, /gotify, /ntfy, /health)")
    server = ThreadingHTTPServer(addr, Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
