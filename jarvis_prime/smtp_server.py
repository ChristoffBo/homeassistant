#!/usr/bin/env python3
# /app/smtp_server.py
import os
import asyncio
from email.parser import BytesParser
from aiosmtpd.controller import Controller

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

BOT_NAME   = os.getenv("BOT_NAME","Jarvis Prime")
BOT_ICON   = os.getenv("BOT_ICON","🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL","").rstrip("/")
APP_TOKEN  = os.getenv("GOTIFY_APP_TOKEN","")
MOOD       = os.getenv("CHAT_MOOD","serious")

def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _transform(title: str, body: str, mood: str):
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
            print(f"[smtp] LLM skipped: {e}")

    # BEAUTIFY SECOND
    if beautify and hasattr(beautify, "beautify_message"):
        try:
            out, extras = beautify.beautify_message(title, out, mood=mood)
            used_beautify = True
        except Exception as e:
            print(f"[smtp] Beautify failed: {e}")

    footer = _footer(used_llm, used_beautify)
    if not out.rstrip().endswith(footer):
        out = f"{out.rstrip()}\n\n{footer}"
    return out, extras

def _post(title: str, message: str, extras=None):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": 5}
    if extras: payload["extras"] = extras
    r = requests.post(url, json=payload, timeout=8); r.raise_for_status()

class Handler:
    async def handle_DATA(self, server, session, envelope):
        try:
            msg = BytesParser().parsebytes(envelope.original_content or envelope.content)
            subject = msg.get("Subject", "SMTP")
            title = f"[SMTP] {subject}"
            # prefer plain text part
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = (part.get_content_type() or "").lower()
                    if ctype == "text/plain":
                        body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8","ignore")
                        break
                if not body:
                    body = (msg.get_payload(decode=True) or b"").decode("utf-8","ignore")
            else:
                body = (msg.get_payload(decode=True) or b"").decode("utf-8","ignore")

            out, extras = _transform(title, body, MOOD)
            _post(title, out, extras)
            return "250 OK"
        except Exception as e:
            print(f"[smtp] error: {e}")
            return "451 Internal error"

def main():
    bind = os.getenv("smtp_bind","0.0.0.0")
    port = int(os.getenv("smtp_port","2525"))
    ctrl = Controller(Handler(), hostname=bind, port=port)
    ctrl.start()
    print(f"[smtp] listening on {bind}:{port}")
    try:
        asyncio.get_event_loop().run_forever()
    finally:
        ctrl.stop()

if __name__ == "__main__":
    main()
