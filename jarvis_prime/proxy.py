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
# Inbox storage
# -----------------------------
try:
    import storage
    storage.init_db()
except Exception as _e:
    storage = None
    print(f"[proxy] ⚠️ storage init failed: {_e}")

# -----------------------------
# Config load (match bot.py behavior)
# -----------------------------
def _load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _bool_env(name, default=False):
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

# options.json overrides config.json; env is fallback
_config_fallback = _load_json("/data/config.json")
_options         = _load_json("/data/options.json")
merged           = {**_config_fallback, **_options}

BOT_NAME   = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON   = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL", "").rstrip("/")
APP_TOKEN  = os.getenv("GOTIFY_APP_TOKEN", "")

# Mood + LLM flags like bot.py
CHAT_MOOD = str(merged.get("personality_mood",
               merged.get("chat_mood", os.getenv("CHAT_MOOD", "serious"))))
LLM_ENABLED         = bool(merged.get("llm_enabled", _bool_env("LLM_ENABLED", False)))
LLM_TIMEOUT_SECONDS = int(merged.get("llm_timeout_seconds", int(os.getenv("LLM_TIMEOUT_SECONDS", "12"))))
LLM_MAX_CPU_PERCENT = int(merged.get("llm_max_cpu_percent", int(os.getenv("LLM_MAX_CPU_PERCENT", "70"))))
LLM_MODEL_URL       = merged.get("llm_model_url",    os.getenv("LLM_MODEL_URL", ""))
LLM_MODEL_PATH      = merged.get("llm_model_path",   os.getenv("LLM_MODEL_PATH", ""))
LLM_MODEL_SHA256    = merged.get("llm_model_sha256", os.getenv("LLM_MODEL_SHA256", ""))
ALLOW_PROFANITY     = bool(merged.get("personality_allow_profanity",
                         _bool_env("PERSONALITY_ALLOW_PROFANITY", False)))

PUSH_GOTIFY_ENABLED = bool(merged.get("push_gotify_enabled", _bool_env("PUSH_GOTIFY_ENABLED", False)))
PUSH_NTFY_ENABLED = bool(merged.get("push_ntfy_enabled", _bool_env("PUSH_NTFY_ENABLED", False)))

# Forwarding to core beautifier/LLM in bot.py
INTERNAL_EMIT_URL = os.getenv("JARVIS_INTERNAL_EMIT_URL", "http://127.0.0.1:2599/internal/emit")

# -----------------------------
# Optional modules (used only on fallback)
# -----------------------------
try:
    import importlib.util as _imp
    _bspec = _imp.spec_from_file_location("beautify", "/app/beautify.py")
    beautify = _imp.module_from_spec(_bspec); _bspec.loader.exec_module(beautify) if _bspec and _bspec.loader else None
    print("[proxy] beautify loaded")
except Exception as e:
    beautify = None
    print(f"[proxy] beautify load failed: {e}")

llm = None
try:
    import importlib.util as _imp
    _lspec = _imp.spec_from_file_location("llm_client", "/app/llm_client.py")
    llm = _imp.module_from_spec(_lspec); _lspec.loader.exec_module(llm) if _lspec and _lspec.loader else None
    print(f"[proxy] llm_client loaded (enabled={LLM_ENABLED})")
    if LLM_ENABLED and llm and hasattr(llm, "prefetch_model"):
        llm.prefetch_model()
except Exception as e:
    llm = None
    print(f"[proxy] llm_client load failed: {e}")

# -----------------------------
# Helpers
# -----------------------------
def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _pipeline(title: str, body: str, mood: str):
    used_llm = False
    used_beautify = False
    out = body or ""
    extras = None

    if LLM_ENABLED and llm and hasattr(llm, "rewrite"):
        try:
            out = llm.rewrite(
                text=out,
                mood=mood,
                timeout=LLM_TIMEOUT_SECONDS,
                cpu_limit=LLM_MAX_CPU_PERCENT,
                models_priority=None,
                base_url="",
                model_url=LLM_MODEL_URL,
                model_path=LLM_MODEL_PATH,
                model_sha256=LLM_MODEL_SHA256,
                allow_profanity=ALLOW_PROFANITY,
            )
            used_llm = True
            print("[proxy] LLM rewrite applied (fallback)")
        except Exception as e:
            print(f"[proxy] LLM skipped: {e}")

    if beautify and hasattr(beautify, "beautify_message"):
        try:
            out, extras = beautify.beautify_message(title, out, mood=mood)
            used_beautify = True
        except Exception as e:
            print(f"[proxy] Beautify failed: {e}")

    foot = _footer(used_llm, used_beautify)
    if not out.rstrip().endswith(foot):
        out = f"{out.rstrip()}\n\n{foot}"
    return out, extras, used_llm, used_beautify

def _post_gotify(title: str, message: str, extras=None):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": 5}
    if extras: payload["extras"] = extras
    if PUSH_GOTIFY_ENABLED and GOTIFY_URL and APP_TOKEN:
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        return r.status_code
    return 0

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
            body = ""
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

            # Primary path: forward to core internal emit (bot.py) so persona riffs apply uniformly
            try:
                _emit_internal(title, body, priority=5, source="proxy", oid="")
                if storage:
                    try:
                        storage.save_message(
                            title=title or "Proxy",
                            body=body or "",
                            source="proxy_intake",
                            priority=5,
                            extras={"forwarded_to_internal": True},
                            created_at=int(time.time())
                        )
                    except Exception as e:
                        print(f"[proxy] storage save failed: {e}")
                return self._send(200, "ok")
            except Exception as e:
                print(f"[proxy] internal emit failed ({e}); falling back to local pipeline → gotify")

            # Fallback path: do local beautify/LLM and push to Gotify
            out, extras, used_llm, used_beautify = _pipeline(title, body, CHAT_MOOD)
            status = _post_gotify(title, out, extras)

            if storage:
                try:
                    storage.save_message(
                        title=title or "Proxy",
                        body=out or "",
                        source="proxy_fallback",
                        priority=5,
                        extras={"extras": extras or {}, "mood": CHAT_MOOD, "used_llm": used_llm, "used_beautify": used_beautify, "status": int(status)},
                        created_at=int(time.time())
                    )
                except Exception as e:
                    print(f"[proxy] storage save failed: {e}")

            return self._send(200, "ok")
        except Exception as e:
            print(f"[proxy] error: {e}")
            return self._send(500, "error")

def main():
    host = os.getenv("proxy_bind", "0.0.0.0")
    port = int(os.getenv("proxy_port", "2580"))
    srv = ReuseHTTPServer((host, port), H)
    print(f"[proxy] listening on {host}:{port} (LLM_ENABLED={LLM_ENABLED}, mood={CHAT_MOOD}) — forwarding to {INTERNAL_EMIT_URL}")
    srv.serve_forever()

if __name__ == "__main__":
    main()