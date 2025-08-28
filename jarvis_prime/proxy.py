# /app/proxy.py
# Tiny HTTP proxy so external systems can post JSON and still go through Jarvis pipeline.
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PORT = 2580
BIND = "0.0.0.0"

class _State:
    route_cb = None

STATE = _State()

class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/ping":
            self._send(200, {"ok": True})
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        try:
            ln = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(ln).decode("utf-8") if ln else ""
            data = {}
            try:
                data = json.loads(raw) if raw else {}
            except Exception:
                pass
            title = data.get("title") or "Proxy"
            message = data.get("message") or ""
            priority = int(data.get("priority") or 5)
            extras = data.get("extras")
            if STATE.route_cb:
                STATE.route_cb(title, message, priority=priority, extras=extras)
            self._send(200, {"ok": True})
        except Exception as e:
            self._send(500, {"ok": False, "error": str(e)})

def start_proxy(env: dict, route_cb):
    global PORT, BIND
    PORT = int(env.get("proxy_port", "2580"))
    BIND = env.get("proxy_bind", "0.0.0.0")
    STATE.route_cb = route_cb

    def _serve():
        httpd = HTTPServer((BIND, PORT), Handler)
        httpd.serve_forever()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
