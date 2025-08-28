# /app/proxy.py
# HTTP intake/forwarder for Jarvis Prime.
#
# Endpoints:
#   POST /message[?token=...]  -> Gotify-compatible
#   POST /gotify               -> JSON {title, message, priority?, extras?}
#   POST /ntfy                 -> text/plain or JSON {"title","message"}
#   GET  /health               -> 200 OK
#
# Behavior:
#   - For every inbound payload: LLM rewrite → Beautify (unless wake-word).
#   - On timeout/error: Beautify-only fallback.
#   - Forwards to external servers if configured (proxy_gotify_url / proxy_ntfy_url).
#   - Always 200 OK to sender.
from __future__ import annotations
import json, urllib.parse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

try:
    from beautify import beautify_message
except Exception:
    def beautify_message(title, body, **kwargs):
        return body, None

try:
    import llm_client as _llm
except Exception:
    _llm = None

STATE = None

class ProxyState:
    def __init__(self, config, send_cb):
        self.cfg = config
        self.send_cb = send_cb
        self.bind = str(config.get("proxy_bind", "0.0.0.0"))
        self.port = int(config.get("proxy_port", 2580))
        self.forward_gotify = (config.get("proxy_gotify_url") or "").strip()
        self.forward_ntfy = (config.get("proxy_ntfy_url") or "").strip()
        self.mood = str(config.get("personality_mood", "serious"))
        self.llm_enabled = bool(config.get("llm_enabled", False))
        self.llm_timeout = int(config.get("llm_timeout_seconds", 5))
        self.llm_cpu = int(config.get("llm_max_cpu_percent", 70))
        self.llm_model_path = str(config.get("llm_model_path", ""))

def _merge_extras(a, b):
    if not a and not b: return None
    out = {}
    for d in (a or {}), (b or {}):
        try:
            for k, v in d.items(): out[k] = v
        except Exception:
            pass
    return out or None

def _wake_word_present(title: str, message: str) -> bool:
    # Only treat as a wake-word when the **message body** starts with "jarvis " or "jarvis:"
    # Do NOT consider the title (many sources brand with "Jarvis Prime:" which should not bypass the LLM)
    m = (message or "").strip().lower()
    return m.startswith("jarvis ") or m.startswith("jarvis:")

def _llm_then_beautify(title: str, message: str, mood: str):
    print(f"[LLM DEBUG][proxy] gate: wake={_wake_word_present(title, message)} en={bool(STATE and STATE.llm_enabled)} mod={bool(_llm)} hasinfo={hasattr(_llm, 'rewrite_with_info') if _llm else False}")
    if _wake_word_present(title, message) or not (STATE and STATE.llm_enabled and _llm and hasattr(_llm, "rewrite_with_info")):
        text, bx = beautify_message(title, message, mood=mood, source_hint="proxy")
        return f"{text}\n[Beautify fallback]", bx

    def _call():
        try:
            rewritten, used = _llm.rewrite_with_info(
                text=message,
                mood=mood,
                timeout=STATE.llm_timeout,
                cpu_limit=STATE.llm_cpu,
                model_path=STATE.llm_model_path,
            )
            if used:
                t, bx = beautify_message(title, rewritten, mood=mood, source_hint="proxy")
                return f"{t}\n[Neural Core ✓]", bx
            else:
                t, bx = beautify_message(title, message, mood=mood, source_hint="proxy")
                return f"{t}\n[Beautify fallback]", bx
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
    server_version = "JarvisProxy/1.4"

    def _set_headers(self, status=200, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._set_headers()
            self.wfile.write(b'{"ok":true}')
            return
        self._set_headers(404)
        self.wfile.write(b'{"ok":false,"error":"not found"}')

    def _handle_gotify_like(self, raw: bytes, qparams: dict):
        try:
            ct = self.headers.get("Content-Type", "") or ""
            if "application/json" in ct:
                data = json.loads(raw.decode("utf-8") or "{}")
                title = str(data.get("title") or data.get("topic") or "Notification")
                message = str(data.get("message") or data.get("body") or "")
                extras = data.get("extras") or {}
                priority = int(data.get("priority") or 5)
            else:
                form = urllib.parse.parse_qs(raw.decode("utf-8") or "")
                title = str((form.get("title") or ["Notification"])[0])
                message = str((form.get("message") or [""])[0])
                priority = int((form.get("priority") or [5])[0])
                extras = {}
        except Exception:
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
                title = str(data.get("title") or "Notification")
                message = str(data.get("message") or "")
                extras = data.get("extras") or {}
                priority = int(data.get("priority") or 5)
            except Exception:
                title = "Notification"
                message = raw.decode("utf-8", "ignore")
                extras = {}
                priority = 5

        # token in qparams is ignored locally (we're the intake)
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
                u = STATE.forward_gotify.rstrip("/") + "/message"
                json_payload = {"title": title, "message": final, "priority": priority, "extras": merged_extras}
                requests.post(u, json=json_payload, timeout=5)
            except Exception as e:
                print(f"[Proxy] ⚠️ forward (gotify) failed: {e}")

        # Optional forward to a real ntfy server
        if STATE and STATE.forward_ntfy:
            try:
                u = STATE.forward_ntfy.rstrip("/")
                headers = {"Title": title}
                requests.post(u, data=final.encode("utf-8"), headers=headers, timeout=5)
            except Exception as e:
                print(f"[Proxy] ⚠️ forward (ntfy) failed: {e}")

        self._set_headers()
        self.wfile.write(b'{"ok":true}')

    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b""
            path, _, query = self.path.partition("?")
            q = urllib.parse.parse_qs(query)

            if path == "/message":
                self._handle_gotify_like(raw, q)
                return

            if path == "/gotify":
                self._handle_gotify_like(raw, q)
                return

            if path == "/ntfy":
                ct = self.headers.get("Content-Type", "") or ""
                title = str((q.get("title") or ["Notification"])[0])
                message = raw.decode("utf-8", "ignore") if "text/plain" in ct else str(json.loads(raw.decode("utf-8") or "{}").get("message") or "")
                final, bx = _llm_then_beautify(title, message, mood=STATE.mood if STATE else "serious")
                if STATE and STATE.send_cb:
                    try:
                        STATE.send_cb(title, final, priority=5, extras=_merge_extras(bx, {}))
                    except Exception as e:
                        print(f"[Proxy] ❌ local post error: {e}")
                self._set_headers()
                self.wfile.write(b'{"ok":true}')
                return

            self._set_headers(404)
            self.wfile.write(b'{"ok":false,"error":"not found"}')
        except Exception as e:
            print(f"[Proxy] ❌ handler error: {e}")
            self._set_headers(500)
            self.wfile.write(b'{"ok":false}')

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
