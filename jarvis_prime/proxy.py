#!/usr/bin/env python3
# /app/proxy.py
import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    import importlib.util as _imp
    _bspec = _imp.spec_from_file_location("beautify", "/app/beautify.py")
    beautify = _imp.module_from_spec(_bspec); _bspec.loader.exec_module(beautify) if _bspec and _bspec.loader else None
except Exception:
    beautify = None

try:
    import importlib.util as _imp
    _lspec = _imp.spec_from_file_location("llm_client", "/app/llm_client.py")
    llm = _imp.module_from_spec(_lspec); _lspec.loader.exec_module(llm) if _lspec and _lspec.loader else None
except Exception:
    llm = None

import requests

GOTIFY_URL = os.getenv("GOTIFY_URL","").rstrip("/")
APP_TOKEN  = os.getenv("GOTIFY_APP_TOKEN","")
MOOD       = os.getenv("CHAT_MOOD","serious")

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

    # LLM FIRST
    if os.getenv("LLM_ENABLED","false").lower() in ("1","true","yes") and llm and hasattr(llm,"rewrite"):
        try:
            out = llm.rewrite(
                text=out, mood=mood, timeout=int(os.getenv("LLM_TIMEOUT_SECONDS","8")),
                cpu_limit=int(os.getenv("LLM_MAX_CPU_PERCENT","70")),
                models_priority=[], base_url=os.getenv("OLLAMA_BASE_URL",""),
                model_url=os.getenv("LLM_MODEL_URL",""), model_path=os.getenv("LLM_MODEL_PATH",""),
                model_sha256=os.getenv("LLM_MODEL_SHA256",""),
                allow_profanity=os.getenv("PERSONALITY_ALLOW_PROFANITY","false").lower() in ("1","true","yes"),
            )
            used_llm = True
        except Exception as e:
            print(f"[proxy] LLM skipped: {e}")

    # BEAUTIFY SECOND
    if beautify and hasattr(beautify, "beautify_message"):
        try:
            out, extras = beautify.beautify_message(title, out, mood=mood)
            used_beautify = True
        except Exception as e:
            print(f"[proxy] Beautify failed: {e}")

    foot = _footer(used_llm, used_beautify)
    if not out.rstrip().endswith(foot):
        out = f"{out.rstrip()}\n\n{foot}"
    return out, extras

def _post_gotify(title: str, message: str, extras=None):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    payload = {"title": title, "message": message, "priority": 5}
    if extras: payload["extras"] = extras
    r = requests.post(url, json=payload, timeout=8)
    r.raise_for_status()

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
            length = int(self.headers.get("Content-Length","0"))
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
                    body = raw.decode("utf-8","ignore")
            else:
                body = raw.decode("utf-8","ignore")

            out, extras = _pipeline(title, body, MOOD)
            _post_gotify(f"{os.getenv('BOT_ICON','🧠')} {os.getenv('BOT_NAME','Jarvis Prime')}: {title}", out, extras)
            return self._send(200, "ok")
        except Exception as e:
            print(f"[proxy] error: {e}")
            return self._send(500, "error")

def main():
    host = os.getenv("proxy_bind","0.0.0.0")
    port = int(os.getenv("proxy_port","2580"))
    srv = HTTPServer((host, port), H)
    print(f"[proxy] listening on {host}:{port}")
    srv.serve_forever()

if __name__ == "__main__":
    main()
