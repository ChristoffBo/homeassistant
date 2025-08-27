# /app/proxy.py
# Minimal HTTP forwarder for Gotify and ntfy.
# - Listens on proxy_bind:proxy_port (defaults 0.0.0.0:2580)
# - For Gotify:   accepts /message?token=...  → forwards to <proxy_gotify_url>/message?token=...
# - For ntfy:     accepts /<topic> and /<topic>/... → forwards to <proxy_ntfy_url>/<same_path>
# - Everything else: 404
#
# Notes:
# - Runs in its own thread; non-blocking for bot.py
# - Uses 'requests' to forward original method, headers (sanitized), and body
# - Adds small log lines for visibility

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import requests
import json
import io

# Will be filled by start_proxy()
_CFG = {}
_send_fn = None

def _log(msg: str):
    print(f"[Proxy] {msg}")

def _target_base(path: str):
    """Decide whether to forward to Gotify or ntfy based on path."""
    got = (_CFG.get("proxy_gotify_url") or "").rstrip("/")
    ntf = (_CFG.get("proxy_ntfy_url") or "").rstrip("/")

    # Gotify compatibility: /message?token=...
    if path.startswith("/message"):
        return got
    # ntfy-style: /topic or /topic/...
    if path.startswith("/") and len(path) > 1 and not path.startswith("/message"):
        return ntf
    return None

def _sanitize_headers(headers):
    """Drop hop-by-hop headers and any Host header (requests sets its own)."""
    drop = {
        "host","connection","keep-alive","proxy-authenticate","proxy-authorization",
        "te","trailers","transfer-encoding","upgrade"
    }
    clean = {}
    for k, v in headers.items():
        if k.lower() not in drop:
            clean[k] = v
    return clean

class _ProxyHandler(BaseHTTPRequestHandler):
    # We only need POST and PUT for Gotify/Ntfy, but accept GET for testing.
    def _handle(self):
        try:
            base = _target_base(self.path)
            if not base:
                self.send_response(404); self.end_headers()
                self.wfile.write(b"Not Found")
                _log(f"404 {self.command} {self.path}")
                return

            # Build upstream URL
            url = f"{base}{self.path}"

            # Body
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b""

            # Headers
            headers = _sanitize_headers({k: v for k, v in self.headers.items()})

            # Forward using same verb
            method = self.command.upper()
            resp = requests.request(method, url, data=body, headers=headers, timeout=10)

            # Mirror status + body
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                # Avoid chunked issues
                if k.lower() not in ("transfer-encoding", "content-encoding", "content-length", "connection"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp.content)))
            self.end_headers()
            self.wfile.write(resp.content)

            _log(f"{method} {self.path} -> {url} [{resp.status_code}]")
        except Exception as e:
            _log(f"Error handling {self.command} {self.path}: {e}")
            try:
                self.send_response(502); self.end_headers()
                self.wfile.write(b"Bad Gateway")
            except Exception:
                pass

    def do_POST(self): self._handle()
    def do_PUT(self): self._handle()
    def do_GET(self): self._handle()  # optional for quick testing (e.g., curl)

def _serve(bind: str, port: int):
    httpd = HTTPServer((bind, port), _ProxyHandler)
    _log(f"listening on http://{bind}:{port}")
    httpd.serve_forever()

def start_proxy(options: dict, send_fn):
    global _CFG, _send_fn
    _CFG = options or {}
    _send_fn = send_fn

    bind = str(_CFG.get("proxy_bind", "0.0.0.0"))
    try:
        port = int(_CFG.get("proxy_port", 2580))
    except Exception:
        port = 2580

    # Validate targets (warn only)
    if not (_CFG.get("proxy_gotify_url") or "").startswith("http"):
        _log("⚠️ proxy_gotify_url is empty or invalid")
    if not (_CFG.get("proxy_ntfy_url") or "").startswith("http"):
        _log("⚠️ proxy_ntfy_url is empty or invalid")

    t = threading.Thread(target=_serve, args=(bind, port), daemon=True)
    t.start()
    return True
