# /app/smtp_server.py
# LAN-only SMTP intake for Jarvis Prime.
# - Accepts any username/password (AUTH is ignored if enabled upstream).
# - Parses Subject → title, body → message.
# - Runs the payload through beautify_message (unified Jarvis card).
# - Posts to Gotify via the send_message(title, text, extras) callback.

from __future__ import annotations
import threading
import json
import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional

from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime

try:
    from beautify import beautify_message
except Exception:
    def beautify_message(title, body, **kwargs):
        return body, None

# Prefer aiosmtpd if present, else stdlib smtpd
AIOSMTPD_AVAILABLE = False
try:
    import asyncio
    from aiosmtpd.controller import Controller
    AIOSMTPD_AVAILABLE = True
except Exception:
    AIOSMTPD_AVAILABLE = False
    import smtpd
    import asyncore

# Optional HTML to text
try:
    from html2text import html2text  # optional
except Exception:
    html2text = None  # type: ignore

def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        parts = decode_header(value)
        out = ""
        for text, enc in parts:
            if isinstance(text, bytes):
                out += text.decode(enc or "utf-8", errors="ignore")
            else:
                out += text
        return out
    except Exception:
        return str(value)

def _extract_body(msg, allow_html: bool) -> str:
    try:
        if msg.is_multipart():
            plain = None
            html = None
            for part in msg.walk():
                ctype = (part.get_content_type() or "").lower()
                cd = (part.get("Content-Disposition") or "").lower()
                if "attachment" in cd:
                    continue
                if ctype == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    plain = part.get_payload(decode=True).decode(charset, errors="ignore")
                elif ctype == "text/html":
                    charset = part.get_content_charset() or "utf-8"
                    html = part.get_payload(decode=True).decode(charset, errors="ignore")
            if plain:
                return plain.strip()
            if allow_html and html:
                if html2text:
                    try:
                        return html2text(html).strip()
                    except Exception:
                        pass
                return re.sub(r"<[^>]+>", "", html).strip()
            if html:
                return re.sub(r"<[^>]+>", "", html).strip()
            return ""
        else:
            ctype = (msg.get_content_type() or "").lower()
            payload = msg.get_payload(decode=True)
            if payload is None:
                payload = msg.get_payload()
                if isinstance(payload, str):
                    return payload.strip()
                return ""
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="ignore")
            if ctype == "text/html":
                if allow_html and html2text:
                    try:
                        return html2text(text).strip()
                    except Exception:
                        pass
                return re.sub(r"<[^>]+>", "", text).strip()
            return text.strip()
    except Exception:
        return ""

def _priority_from_subject(subject: str, default: int, pmap: Dict[str, int]) -> int:
    s = subject.lower()
    for key, val in pmap.items():
        if key.lower() in s:
            return int(val)
    return int(default)

class SMTPHandlerAIOSMTPD:
    def __init__(self, config: Dict[str, Any], send_cb):
        self.cfg = config
        self.send_cb = send_cb
        self.prefix = str(config.get("smtp_rewrite_title_prefix", "[SMTP]")).strip() + " "
        try:
            self.priority_map = json.loads(config.get("smtp_priority_map") or "{}")
            if not isinstance(self.priority_map, dict): self.priority_map = {}
        except Exception:
            self.priority_map = {}
        self.default_prio = int(config.get("smtp_priority_default", 5))
        self.allow_html = bool(config.get("smtp_allow_html", False))

    async def handle_DATA(self, server, session, envelope):
        try:
            data = envelope.original_content or envelope.content
        except Exception:
            data = envelope.content
        try:
            msg = message_from_bytes(data)
        except Exception:
            raw = data.decode("utf-8", errors="ignore")
            title = self.prefix + "Mail"
            final, bx = beautify_message(title, raw, mood=str(self.cfg.get("personality_mood","serious")), source_hint="mail")
            self.send_cb(title, final, extras=bx)
            return "250 Message accepted for delivery"

        subject = _decode_header(msg.get("Subject"))
        sender = _decode_header(msg.get("From"))
        date_hdr = msg.get("Date")
        try:
            ts = parsedate_to_datetime(date_hdr).strftime("%Y-%m-%d %H:%M") if date_hdr else None
        except Exception:
            ts = None

        body = _extract_body(msg, self.allow_html)
        title = self.prefix + (subject if subject else "Mail")

        lines = []
        if sender: lines.append(f"From: {sender}")
        if ts:     lines.append(f"Date: {ts}")
        if body:
            lines.append("")
            lines.append(body)
        text = "\n".join(lines).strip() or "(no content)"

        mood = str(self.cfg.get("personality_mood", "serious"))
        priority = _priority_from_subject(subject or "", self.default_prio, self.priority_map)

        final, bx = beautify_message(title, text, mood=mood, source_hint="mail")
        self.send_cb(title, final, priority=priority, extras=bx)
        return "250 Message accepted for delivery"

class SMTPHandlerSMPTD(smtpd.SMTPServer):  # type: ignore
    def __init__(self, localaddr, remoteaddr, config: Dict[str, Any], send_cb):
        super().__init__(localaddr, remoteaddr, decode_data=False)
        self.cfg = config
        self.send_cb = send_cb
        self.prefix = str(config.get("smtp_rewrite_title_prefix", "[SMTP]")).strip() + " "
        try:
            self.priority_map = json.loads(config.get("smtp_priority_map") or "{}")
            if not isinstance(self.priority_map, dict): self.priority_map = {}
        except Exception:
            self.priority_map = {}
        self.default_prio = int(config.get("smtp_priority_default", 5))
        self.allow_html = bool(config.get("smtp_allow_html", False))

    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        try:
            msg = message_from_bytes(data)
        except Exception:
            raw = data.decode("utf-8", errors="ignore") if isinstance(data, (bytes, bytearray)) else str(data)
            title = self.prefix + "Mail"
            final, bx = beautify_message(title, raw, mood=str(self.cfg.get("personality_mood","serious")), source_hint="mail")
            self.send_cb(title, final, extras=bx)
            return

        subject = _decode_header(msg.get("Subject"))
        sender = _decode_header(msg.get("From"))
        date_hdr = msg.get("Date")
        try:
            ts = parsedate_to_datetime(date_hdr).strftime("%Y-%m-%d %H:%M") if date_hdr else None
        except Exception:
            ts = None

        body = _extract_body(msg, self.allow_html)
        title = self.prefix + (subject if subject else "Mail")

        lines = []
        if sender: lines.append(f"From: {sender}")
        if ts:     lines.append(f"Date: {ts}")
        if body:
            lines.append("")
            lines.append(body)
        text = "\n".join(lines).strip() or "(no content)"

        mood = str(self.cfg.get("personality_mood", "serious"))
        priority = _priority_from_subject(subject or "", self.default_prio, self.priority_map)

        final, bx = beautify_message(title, text, mood=mood, source_hint="mail")
        self.send_cb(title, final, priority=priority, extras=bx)

def _run_aiosmtpd(bind: str, port: int, handler: SMTPHandlerAIOSMTPD):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    controller = Controller(handler, hostname=bind, port=port)
    controller.start()
    print(f"[Jarvis Prime] 📮 SMTP (aiosmtpd) running on {bind}:{port}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        controller.stop()

def _run_smtpd(bind: str, port: int, factory):
    server = factory((bind, port), None)  # type: ignore
    print(f"[Jarvis Prime] 📮 SMTP (smtpd) running on {bind}:{port}")
    try:
        asyncore.loop()  # type: ignore
    except KeyboardInterrupt:
        pass

def start_smtp(config: Dict[str, Any], send_cb):
    bind = str(config.get("smtp_bind", "0.0.0.0"))
    port = int(config.get("smtp_port", 2525))
    if AIOSMTPD_AVAILABLE:
        handler = SMTPHandlerAIOSMTPD(config, send_cb)
        t = threading.Thread(target=_run_aiosmtpd, args=(bind, port, handler), daemon=True)
        t.start()
    else:
        factory = lambda addr, remote: SMTPHandlerSMPTD(addr, remote, config, send_cb)  # noqa: E731
        t = threading.Thread(target=_run_smtpd, args=(bind, port, factory), daemon=True)
        t.start()
