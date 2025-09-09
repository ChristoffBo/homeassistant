#!/usr/bin/env python3
from __future__ import annotations
import os, smtplib, ssl
from typing import Dict, Any
from email.message import EmailMessage

HOST = os.getenv("OUT_SMTP_HOST", "smtp.gmail.com")
PORT = int(os.getenv("OUT_SMTP_PORT", "587"))
USER = os.getenv("OUT_SMTP_USER", "")
PASS = os.getenv("OUT_SMTP_PASS", "")
TO   = os.getenv("OUT_SMTP_TO", USER or "")

def send_mail(subject: str, body: str, *, to: str | None = None) -> Dict[str, Any]:
    """
    Send an email using STARTTLS (TLS 587) or SSL (465).
    For Gmail, use an app password (docs: https://support.google.com/a/answer/176600).
    """
    msg = EmailMessage()
    sender = USER or "jarvis@local"
    rcpt = to or TO or USER
    if not rcpt:
        return {"error": "no recipient configured"}
    msg["From"] = sender
    msg["To"] = rcpt
    msg["Subject"] = subject or "(no subject)"
    msg.set_content(body or "")
    try:
        if PORT == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(HOST, PORT, context=context) as s:
                if USER and PASS:
                    s.login(USER, PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(HOST, PORT) as s:
                s.ehlo()
                try:
                    s.starttls(context=ssl.create_default_context())
                except Exception:
                    pass
                if USER and PASS:
                    s.login(USER, PASS)
                s.send_message(msg)
        return {"status": 250}
    except Exception as e:
        return {"error": str(e)}
