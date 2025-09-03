#!/usr/bin/env python3
# /app/smtp_server.py
import os
import asyncio
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
import json
import requests
import time
from aiosmtpd.controller import Controller

# -----------------------------
# Inbox storage
# -----------------------------
try:
    import storage
    storage.init_db()
except Exception as _e:
    storage = None
    print(f"[smtp] ⚠️ storage init failed: {_e}")

# -----------------------------
# Config load (match bot/proxy behavior)
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

_config_fallback = _load_json("/data/config.json")
_options         = _load_json("/data/options.json")
merged           = {**_config_fallback, **_options}

BOT_NAME   = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON   = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL", "").rstrip("/")
APP_TOKEN  = os.getenv("GOTIFY_APP_TOKEN", "")

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

# Beautify
try:
    import importlib.util as _imp
    _bspec = _imp.spec_from_file_location("beautify", "/app/beautify.py")
    beautify = _imp.module_from_spec(_bspec); _bspec.loader.exec_module(beautify) if _bspec and _bspec.loader else None
    print("[smtp] beautify loaded")
except Exception as e:
    beautify = None
    print(f"[smtp] beautify load failed: {e}")

# LLM client (prefetch if enabled)
llm = None
try:
    import importlib.util as _imp
    _lspec = _imp.spec_from_file_location("llm_client", "/app/llm_client.py")
    llm = _imp.module_from_spec(_lspec); _lspec.loader.exec_module(llm) if _lspec and _lspec.loader else None
    print(f"[smtp] llm_client loaded (enabled={LLM_ENABLED})")
    if LLM_ENABLED and llm and hasattr(llm, "prefetch_model"):
        llm.prefetch_model()
except Exception as e:
    llm = None
    print(f"[smtp] llm_client load failed: {e}")

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
            print("[smtp] LLM rewrite applied")
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
    return out, extras, used_llm, used_beautify

def _post(title: str, message: str, extras=None):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": 5}
    if extras: payload["extras"] = extras
    if PUSH_GOTIFY_ENABLED and GOTIFY_URL and APP_TOKEN:
        r = requests.post(url, json=payload, timeout=8); r.raise_for_status(); return r.status_code
    return 0

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

            # ---------- ADDITIVE: build riff facts + hint (safe even if beautify/LLM off) ----------
            from_hdr = msg.get("From", "")
            to_hdr   = msg.get("To", "")
            date_hdr = msg.get("Date", "")
            try:
                dt_val = parsedate_to_datetime(date_hdr).isoformat() if date_hdr else ""
            except Exception:
                dt_val = ""
            riff_facts = {
                "time": dt_val or time.strftime("%Y-%m-%dT%H:%M:%S"),
                "subject": subject,
                "from": from_hdr,
                "to": to_hdr,
                "provider": "SMTP"
            }
            base_extras = {"riff_hint": True, "source": "smtp", "facts": riff_facts}

            out, extras, used_llm, used_beautify = _transform(title, body, CHAT_MOOD)

            # merge any beautify extras
            final_extras = dict(base_extras)
            if isinstance(extras, dict):
                # keep our hint/facts; allow beautify to add visuals, etc.
                final_extras.update(extras)
            print("[smtp] riff hint attached")

            status = _post(title, out, final_extras)

            # Mirror to Inbox DB (UI-first)
            if storage:
                try:
                    storage.save_message(
                        title=title,
                        body=out or "",
                        source="smtp",
                        priority=5,
                        extras={
                            "extras": final_extras or {},
                            "mood": CHAT_MOOD,
                            "used_llm": used_llm,
                            "used_beautify": used_beautify,
                            "status": int(status)
                        },
                        created_at=int(time.time())
                    )
                except Exception as e:
                    print(f"[smtp] storage save failed: {e}")

            return "250 OK"
        except Exception as e:
            print(f"[smtp] error: {e}")
            return "451 Internal error"

def main():
    bind = os.getenv("smtp_bind","0.0.0.0")
    port = int(os.getenv("smtp_port","2525"))
    ctrl = Controller(Handler(), hostname=bind, port=port)
    ctrl.start()
    print(f"[smtp] listening on {bind}:{port} (LLM_ENABLED={LLM_ENABLED}, mood={CHAT_MOOD})")
    try:
        asyncio.get_event_loop().run_forever()
    finally:
        ctrl.stop()

if __name__ == "__main__":
    main()