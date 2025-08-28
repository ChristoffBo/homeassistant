# /app/smtp_server.py
# LAN-only SMTP intake for Jarvis Prime (aiosmtpd).
# Accepts any AUTH creds when smtp_accept_any_auth = true.
# Parses subject/body, LLM → Beautify with timeout fallback, then posts via send_message.

from __future__ import annotations

import re
import json
from typing import Callable, Dict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from email import policy
from email.parser import BytesParser

from aiosmtpd.controller import Controller

try:
    from beautify import beautify_message
except Exception:
    def beautify_message(title, body, **kwargs):
        return body, None

try:
    import llm_client as _llm
except Exception:
    _llm = None

def _wake_word_present(message: str) -> bool:
    m = (message or "").strip().lower()
    return m.startswith("jarvis ") or m.startswith("jarvis:")

class AnyAuthenticator:
    def __init__(self, accept_any_auth: bool):
        self.accept_any = accept_any_auth
    def authenticate(self, server, session, envelope, mechanism, auth_data):
        return "OK" if self.accept_any else "NO"

def _strip_html(html: str) -> str:
    try:
        body = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        body = re.sub(r"(?is)<br\s*/?>", "\n", body)
        body = re.sub(r"(?is)</p>", "\n", body)
        body = re.sub(r"(?is)<[^>]+>", " ", body)
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
        return body.strip()
    except Exception:
        return html

class JarvisSMTPHandler:
    def __init__(self, cfg: Dict, send_cb: Callable):
        self.cfg = cfg
        self.send_cb = send_cb

        self.bind = str(cfg.get("smtp_bind", "0.0.0.0"))
        self.port = int(cfg.get("smtp_port", 2525))
        self.accept_any_auth = bool(cfg.get("smtp_accept_any_auth", True))
        self.allowed_rcpt = (str(cfg.get("smtp_dummy_rcpt", "alerts@jarvis.local")) or "").lower()

        self.rewrite_prefix = str(cfg.get("smtp_rewrite_title_prefix", "[SMTP]")).strip()
        self.allow_html = bool(cfg.get("smtp_allow_html", False))
        self.default_prio = int(cfg.get("smtp_priority_default", 5))
        raw_map = cfg.get("smtp_priority_map", {"high": 7, "urgent": 8, "critical": 9, "low": 3, "normal": 5})
        if isinstance(raw_map, str):
            try:
                raw_map = json.loads(raw_map)
            except Exception:
                raw_map = {"high": 7, "urgent": 8, "critical": 9, "low": 3, "normal": 5}
        self.prio_map = {str(k).lower(): int(v) for k, v in (raw_map or {}).items()}

        # Neural Core settings
        self.mood = str(cfg.get("personality_mood", "serious"))
        self.llm_enabled = bool(cfg.get("llm_enabled", False))
        self.llm_timeout = int(cfg.get("llm_timeout_seconds", 5))
        self.llm_cpu = int(cfg.get("llm_max_cpu_percent", 70))
        self.llm_model_path = str(cfg.get("llm_model_path", ""))

        self.show_engine_footer = True

    def _priority_for(self, subject: str) -> int:
        default_prio = self.default_prio
        prio_map = self.prio_map
        subj = (subject or "").lower()
        if "!" in subj and "test" not in subj:
            return min(10, default_prio + 1)
        imp = "normal"
        for w in ("urgent", "critical", "down", "error", "failed", "warning", "high", "low"):
            if w in subj:
                imp = w
                break
        try:
            return max(1, min(10, int(prio_map.get(imp, default_prio))))
        except Exception:
            return max(1, min(10, int(default_prio)))

    def _llm_then_beautify(self, title: str, body: str):
        print(f"[LLM DEBUG][smtp] gate: wake={_wake_word_present(body)} en={self.llm_enabled} mod={bool(_llm)} has_info={hasattr(_llm, 'rewrite_with_info') if _llm else False} has_legacy={hasattr(_llm, 'rewrite_text') if _llm else False}")
        mood = self.mood or "serious"

        # Wake-word or LLM unavailable -> beautify only
        if _wake_word_present(body) or not (self.llm_enabled and _llm):
            text, bx = beautify_message(title, body, mood=mood, source_hint="mail")
            if self.show_engine_footer:
                text = f"{text}\n[Beautify fallback]"
            return text, bx

        def call_core():
            try:
                if hasattr(_llm, "rewrite_with_info"):
                    rewritten, used = _llm.rewrite_with_info(
                        text=body,
                        mood=mood,
                        timeout=self.llm_timeout,
                        cpu_limit=self.llm_cpu,
                        model_path=self.llm_model_path,
                    )
                    if used:
                        t, bx = beautify_message(title, rewritten, mood=mood, source_hint="mail")
                        if self.show_engine_footer:
                            t = f"{t}\n[Neural Core ✓]"
                        return t, bx
                    else:
                        t, bx = beautify_message(title, body, mood=mood, source_hint="mail")
                        if self.show_engine_footer:
                            t = f"{t}\n[Beautify fallback]"
                        return t, bx
                elif hasattr(_llm, "rewrite_text"):
                    rewritten = _llm.rewrite_text(body, mood=mood, timeout_s=self.llm_timeout)
                    t, bx = beautify_message(title, rewritten, mood=mood, source_hint="mail")
                    if self.show_engine_footer:
                        t = f"{t}\n[Neural Core ✓]"
                    return t, bx
                else:
                    t, bx = beautify_message(title, body, mood=mood, source_hint="mail")
                    if self.show_engine_footer:
                        t = f"{t}\n[Beautify fallback]"
                    return t, bx
            except Exception:
                t, bx = beautify_message(title, body, mood=mood, source_hint="mail")
                if self.show_engine_footer:
                    t = f"{t}\n[Beautify fallback]"
                return t, bx

        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(call_core)
            try:
                return fut.result(timeout=max(1, self.llm_timeout))
            except FuturesTimeout:
                t, bx = beautify_message(title, body, mood=mood, source_hint="mail")
                if self.show_engine_footer:
                    t = f"{t}\n[Beautify fallback]"
                return t, bx

def _parse_message(data: bytes):
    msg = BytesParser(policy=policy.default).parsebytes(data)
    subject = msg["subject"] or "Notification"
    sender = msg["from"] or ""
    rcpttos = msg["to"] or ""
    body = ""

    if msg.is_multipart():
        # prefer text/plain; fallback to stripped HTML
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                break
        if not body:
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/html":
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                    body = _strip_html(html)
                    break
    else:
        ct = msg.get_content_type()
        if ct == "text/plain":
            body = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "ignore")
        elif ct == "text/html":
            html = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "ignore")
            body = _strip_html(html)

    title = f"{subject}"
    return title, body, sender, rcpttos

def start_smtp(config: dict, send_cb: Callable):
    handler = JarvisSMTPHandler(config, send_cb)
    controller = Controller(handler, hostname=handler.bind, port=handler.port, authenticator=AnyAuthenticator(bool(config.get("smtp_accept_any_auth", True))))
    controller.start()
    return controller
