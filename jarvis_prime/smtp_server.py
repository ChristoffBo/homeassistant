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
# Inbox storage (optional)
# -----------------------------
try:
    import storage
    storage.init_db()
except Exception as _e:
    storage = None
    print(f"[smtp] ⚠️ storage init failed: {_e}")

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

# Forward target: Jarvis internal emit (bot.py)
INTERNAL_EMIT_URL = os.getenv("JARVIS_INTERNAL_EMIT_URL", "http://127.0.0.1:2599/internal/emit")

def _emit_internal(title: str, body: str, priority: int = 5, source: str = "smtp", oid: str = ""):
    payload = {"title": title or "SMTP", "body": body or "", "priority": int(priority), "source": source, "id": oid}
    r = requests.post(INTERNAL_EMIT_URL, json=payload, timeout=5)
    r.raise_for_status()
    return r.status_code

class Handler:
    async def handle_DATA(self, server, session, envelope):
        try:
            # Parse the email
            msg = BytesParser().parsebytes(envelope.original_content or envelope.content)
            subject = msg.get("Subject", "SMTP")
            title = f"[SMTP] {subject}"

            # Extract a best-effort plain body
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

            # Forward to Jarvis core
            _emit_internal(title, body, priority=5, source="smtp", oid="")
            print(f"[smtp] forwarded to internal emit: {INTERNAL_EMIT_URL}")

            # Save to inbox (for observability)
            if storage:
                try:
                    storage.save_message(
                        title=title,
                        body=body or "",
                        source="smtp_intake",
                        priority=5,
                        extras={"forwarded_to_internal": True},
                        created_at=int(time.time())
                    )
                except Exception as e:
                    print(f"[smtp] storage save failed: {e}")

            # Always return "250 OK" so senders don't retry; Jarvis handles output.
            return "250 OK"
        except Exception as e:
            print(f"[smtp] forward error: {e}")
            # Still acknowledge OK to avoid mailer retries/duplicates
            return "250 OK"

def main():
    bind = os.getenv("smtp_bind","0.0.0.0")
    port = int(os.getenv("smtp_port","2525"))
    ctrl = Controller(Handler(), hostname=bind, port=port)
    ctrl.start()
    print(f"[smtp] listening on {bind}:{port} — forwarding to {INTERNAL_EMIT_URL}")
    try:
        asyncio.get_event_loop().run_forever()
    finally:
        ctrl.stop()

if __name__ == "__main__":
    main()