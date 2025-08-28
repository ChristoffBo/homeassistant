# /app/proxy.py
import os, json, re, threading, http.server, socketserver, urllib.parse
from typing import Optional, Tuple

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")

# These are injected from bot.py via start_proxy(merged, send_message)
SEND = None
STATE = None

_llm = None
_beautify = None

def _load_helpers():
    global _llm, _beautify
    try:
        import importlib.util as _imp
        spec = _imp.spec_from_file_location("llm_client", "/app/llm_client.py")
        if spec and spec.loader:
            _llm = _imp.module_from_spec(spec)
            spec.loader.exec_module(_llm)
            print(f"[{BOT_NAME}] ✅ llm_client loaded")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ llm_client not loaded: {e}")

    try:
        import importlib.util as _imp
        bspec = _imp.spec_from_file_location("beautify", "/app/beautify.py")
        if bspec and bspec.loader:
            _beautify = _imp.module_from_spec(bspec)
            bspec.loader.exec_module(_beautify)
            print(f"[{BOT_NAME}] ✅ beautify.py loaded (proxy)")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ beautify not loaded: {e}")

def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _wake_word_present(title: str, message: str) -> bool:
    t = (title or "").lower().strip()
    m = (message or "").lower().strip()
    return t.startswith("jarvis") or m.startswith("jarvis")

def _llm_then_beautify(title: str, message: str) -> Tuple[str, Optional[dict]]:
    used_llm = False
    used_beautify = False
    final = message
    extras = None

    # Skip LLM if wake-word → commands should not be rewritten
    if not _wake_word_present(title, message) and (STATE and STATE.llm_enabled and _llm and hasattr(_llm, "rewrite")):
        try:
            print(f"[{BOT_NAME}] [Proxy] → LLM.rewrite start")
            msg = _llm.rewrite(
                text=message,
                mood=STATE.chat_mood,
                timeout=STATE.llm_timeout_seconds,
                cpu_limit=STATE.llm_max_cpu_percent,
                models_priority=STATE.llm_models_priority,
                base_url=STATE.ollama_base_url,
                model_url=STATE.llm_model_url,
                model_path=STATE.llm_model_path,
                model_sha256=STATE.llm_model_sha256,
                allow_profanity=STATE.personality_allow_profanity,
            )
            if msg:
                final = msg
                used_llm = True
                print(f"[{BOT_NAME}] [Proxy] ✓ LLM.rewrite done")
        except Exception as e:
            print(f"[{BOT_NAME}] [Proxy] ⚠️ LLM skipped: {e}")

    if _beautify and hasattr(_beautify, "beautify_message"):
        try:
            final, extras = _beautify.beautify_message(title, final, mood=STATE.chat_mood)
            used_beautify = True
        except Exception as e:
            print(f"[{BOT_NAME}] [Proxy] ⚠️ Beautify failed: {e}")

    # Footer tag
    final = f"{final}\n\n{_footer(used_llm, used_beautify)}"
    return final, extras

class Handler(http.server.BaseHTTPRequestHandler):
    def _ok(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok\n")

    def _bad(self, code=400, text="bad"):
        self.send_response(code)
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._ok()
            return
        self._bad(404, "not found")

    def do_POST(self):
        try:
            clen = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(clen).decode("utf-8", errors="ignore")
            # Accept JSON or form-urlencoded like Gotify
            if self.headers.get("Content-Type", "").startswith("application/json"):
                data = json.loads(raw or "{}")
            else:
                data = dict(urllib.parse.parse_qsl(raw))

            title   = data.get("title")   or "Message"
            message = data.get("message") or ""
            priority = int(data.get("priority", 5))

            # Pipeline
            final, extras = _llm_then_beautify(title, message)
            SEND(title, final, priority=priority, extras=extras)
            self._ok()
        except Exception as e:
            print(f"[{BOT_NAME}] [Proxy] error: {e}")
            self._bad(500, "error")

def start_proxy(merged_cfg, send_fn):
    global SEND, STATE
    SEND = send_fn

    class _State:
        pass
    STATE = _State()
    STATE.chat_mood = merged_cfg.get("personality_mood", merged_cfg.get("chat_mood", "serious"))
    STATE.llm_enabled = bool(merged_cfg.get("llm_enabled", False))
    STATE.llm_timeout_seconds = int(merged_cfg.get("llm_timeout_seconds", 12))
    STATE.llm_max_cpu_percent = int(merged_cfg.get("llm_max_cpu_percent", 70))
    STATE.llm_models_priority = merged_cfg.get("llm_models_priority", [])
    STATE.ollama_base_url     = merged_cfg.get("ollama_base_url", "")
    STATE.llm_model_url       = merged_cfg.get("llm_model_url", "")
    STATE.llm_model_path      = merged_cfg.get("llm_model_path", "")
    STATE.llm_model_sha256    = merged_cfg.get("llm_model_sha256", "")
    STATE.personality_allow_profanity = bool(merged_cfg.get("personality_allow_profanity", False))

    host = merged_cfg.get("proxy_bind", "0.0.0.0")
    port = int(merged_cfg.get("proxy_port", 2580))

    _load_helpers()

    class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    server = ThreadingHTTPServer((host, port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[{BOT_NAME}] 🔀 Proxy listening on {host}:{port} (endpoints: /message, /gotify, /ntfy, /health)")
