# /app/proxy.py
# Simple HTTP proxy/intake for Jarvis Prime.
#
# Endpoints:
#   POST /message?token=XXXX   -> Gotify-compatible
#   POST /gotify               -> JSON {title, message, priority?, extras?}
#   POST /ntfy                 -> text/plain or JSON {"title","message"}
#   GET  /health               -> 200 OK
#
# Behavior:
#   - Every inbound payload is **LLM rewrite → Beautify** (unless wake-word).
#   - If LLM fails or exceeds timeout, we **fall back** to Beautify only.
#   - Forwards to real servers if configured: proxy_gotify_url, proxy_ntfy_url.
#   - Always 200 OK to the sender.
from __future__ import annotations
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

try:
    from beautify import beautify_message
except Exception:
    def beautify_message(title, body, **kwargs):
        return body, None  # soft fallback

# Optional Neural Core (llm_client) — graceful if missing
try:
    import llm_client as _llm
except Exception:
    _llm = None

class ProxyState:
    def __init__(self, config, send_cb):
        self.cfg = config
        self.send_cb = send_cb
        self.bind = str(config.get("proxy_bind", "0.0.0.0"))
        self.port = int(config.get("proxy_port", 8099))
        self.forward_gotify = (config.get("proxy_gotify_url") or "").strip()
        self.forward_ntfy = (config.get("proxy_ntfy_url") or "").strip()
        self.mood = str(config.get("personality_mood", "serious"))
        self.llm_enabled = bool(config.get("llm_enabled", False))
        self.llm_timeout = int(config.get("llm_timeout_seconds", 5))
        self.llm_cpu = int(config.get("llm_max_cpu_percent", 70))
        self.llm_model_path = str(config.get("llm_model_path", ""))

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

def _wake_word_present(title: str, message: str) -> bool:
    both = f"{title} {message}".strip().lower()
    return both.startswith("jarvis ") or both.startswith("jarvis:") or " jarvis " in both

def _llm_then_beautify(title: str, message: str, mood: str):
    """Run LLM.rewrite with timeout. On any issue → beautify raw message."""
    # Skip LLM for wake-word commands
    if _wake_word_present(title, message) or not (STATE and STATE.llm_enabled and _llm and hasattr(_llm, "rewrite")):
        text, bx = beautify_message(title, message, mood=mood, source_hint="proxy")
        return f"{text}\n[Beautify fallback]", bx

    def _call():
        try:
            rewritten = _llm.rewrite(
                text=message,
                mood=mood,
                timeout=STATE.llm_timeout,
                cpu_limit=STATE.llm_cpu,
                model_path=STATE.llm_model_path,
            )
            t, bx = beautify_message(title, rewritten, mood=mood, source_hint="proxy")
            return f"{t}\n[Neural Core ✓]", bx
        except Exception:
            t, bx = beautify_message(title, message, mood=mood, source_hint="proxy")
            return f"{t}\n[Beautify fallback]", bx

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_call)
        try:
            return fut.result(timeout=max(1, STATE.llm_timeout))
        except FuturesTimeout:
            t, bx = beautify_message(title, message, mood=mood, source_hint="proxy")
            return f"{t}\n[Beautify fallback]", bx

class Handler(BaseHTTPRequestHandler):
    server_version = "JarvisProxy/1.3"

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
            payload = json.loads(raw.decode("utf-8", errors="ignore")) if raw else {}
        except Exception:
            payload = {}

        title = str(payload.get("title") or "Message")
        message = str(payload.get("message") or "")
        priority = int(payload.get("priority") or 5)
        extras = payload.get("extras") if isinstance(payload.get("extras"), dict) else None

        final, bx = _llm_then_beautify(title, message, mood=STATE.mood if STATE else "serious")
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

        final, bx = _llm_then_beautify(title, text, mood=STATE.mood if STATE else "serious")
        if STATE and STATE.send_cb:
            try:
                STATE.send_cb(title, final, priority=priority, extras=bx)
            except Exception as e:
                print(f"[Proxy] ❌ local post error: {e}")

def start_proxy(config: dict, send_message_fn):
    """Start the proxy HTTP server in a background thread."""
    global STATE
    STATE = ProxyState(config, send_message_fn)
    addr = (STATE.bind, STATE.port)
    httpd = ThreadingHTTPServer(addr, Handler)
    print(f"[Jarvis Proxy] Listening on {STATE.bind}:{STATE.port}")
    import threading as _t
    t = _t.Thread(target=httpd.serve_forever, name="JarvisProxy", daemon=True)
    t.start()
    return httpd
