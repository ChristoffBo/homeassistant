# /app/smtp_server.py
from __future__ import annotations

import threading
from aiosmtpd.controller import Controller
from email.parser import BytesParser
from email.policy import default

class JarvisHandler:
    def __init__(self, route_cb):
        self.route_cb = route_cb

    async def handle_DATA(self, server, session, envelope):
        try:
            msg = BytesParser(policy=default).parsebytes(envelope.content)
            subject = msg.get("subject") or "SMTP"
            # Prefer plain text
            body = msg.get_body(preferencelist=("plain",))
            text = body.get_content() if body else (msg.get_content() or "")
            self.route_cb(subject, text, priority=5, extras=None, source_hint="smtp")
            return "250 OK"
        except Exception as e:
            return f"451 processing error: {e}"

def start_smtp(env: dict, route_cb):
    bind = env.get("smtp_bind", "0.0.0.0")
    port = int(env.get("smtp_port", "2525"))
    handler = JarvisHandler(route_cb)
    ctrl = Controller(handler, hostname=bind, port=port)
    ctrl.start()
    # keep a ref
    globals()["_SMTP_CTRL"] = ctrl
