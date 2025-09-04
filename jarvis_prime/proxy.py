#!/usr/bin/env python3
# /app/proxy.py
import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import requests
import time
from urllib.parse import urlparse, parse_qs

class ReuseHTTPServer(HTTPServer):
    allow_reuse_address = True
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()

# -----------------------------
# Inbox storage (optional)
# -----------------------------
try:
    import storage
    storage.init_db()
except Exception as _e:
    storage = None
    print(f"[proxy] ⚠️ storage init failed: {_e}")

# -----------------------------
# Config
# -----------------------------
def _load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

_config_fallback = _load_json("/data/config.json")
_options         = _load_json("/data/options.json")
merged           = {**_config_fallback, **_options}

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")

# Forward to Jarvis core (bot.py)
INTERNAL_EMIT_URL = os.getenv("JARVIS_INTERNAL_EMIT_URL", "http://127.0.0.1:2599/internal/emit")

def _emit_internal(title: str, body: str, priority: int = 5, source: str = "proxy", oid: str = ""):
    payload = {"title": title or "Proxy", "body": body or "", "priority": int(priority), "source": source, "id": oid}
    r = requests.post(INTERNAL_EMIT_URL, json=payload, timeout=5)
    r.raise_for_status()
    return r.status_code

# -----------------------------
# HTTP Server
# -----------------------------
class H(BaseHTTPRequestHandler):
    def _send(self, code, data="ok", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(data.encode("utf-8") if isinstance(data, str) else data)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, "ok")
        return self._send(404, "not found")

    def do_POST(self):
        try:
            parsed = urlparse(self.path or "")
            qmap = {k: v[0] if isinstance(v, list) and v else v for k, v in parse_qs(parsed.query).items()}

            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b""
            title = self.headers.get("X-Title") or "Proxy"
            ctype = (self.headers.get("Content-Type") or "").lower()

            if "application/json" in ctype:
                try:
                    data = json.loads(raw.decode("utf-8"))
                    body = data.get("message") or data.get("text") or data.get("body") or ""
                    if not title:
                        title = data.get("title") or "Proxy"
                except Exception:
                    body = raw.decode("utf-8", "ignore")
            else:
                body = raw.decode("utf-8", "ignore")

            # Forward to Jarvis core
            _emit_internal(title, body, priority=5, source="proxy", oid="")

            # Save to inbox (for observability)
            if storage:
                try:
                    storage.save_message(
                        title=title or "Proxy",
                        body=body or "",
                        source="proxy_intake",
                        priority=5,
                        extras={"forwarded_to_internal": True, "query": qmap},
                        created_at=int(time.time())
                    )
                except Exception as e:
                    print(f"[proxy] storage save failed: {e}")

            # Always return 200 so upstreams don't retry (Jarvis will handle output)
            return self._send(200, "ok")
        except Exception as e:
            print(f"[proxy] forward error: {e}")
            # Still 200 to avoid duplicate retries by callers; Jarvis is the single output path.
            return self._send(200, "ok")

def main():
    host = os.getenv("proxy_bind", "0.0.0.0")
    port = int(os.getenv("proxy_port", "2580"))
    srv = ReuseHTTPServer((host, port), H)
    print(f"[proxy] listening on {host}:{port} — forwarding to {INTERNAL_EMIT_URL}")
    srv.serve_forever()

if __name__ == "__main__":
    main()