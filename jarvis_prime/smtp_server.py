# /app/smtp_server.py
# LAN-only SMTP intake for Jarvis Prime (aiosmtpd).
# Accepts any AUTH creds when smtp_accept_any_auth = true.
# Parses subject/body, **LLM rewrite → beautify**, posts via send_message.
from __future__ import annotations
import re
import json
from typing import Callable, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from email import policy
from email.parser import BytesParser

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

# Beautify
try:
    from beautify import beautify_message
except Exception:
    def beautify_message(title, body, **kwargs):
        return body, None

# Optional LLM
try:
    import llm_client as _llm
except Exception:
    _llm = None

def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    html = re.sub(r"(?s)<[^>]+>", "", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = re.sub(r"[ \t\r\f\v]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()

def _choose_priority(headers: Dict[str, str], default_prio: int, prio_map: Dict[str, int]) -> int:
    for key in ("x-priority", "priority"):
        if key in headers:
            m = re.search(r"(\d+)", headers[key])
            if m:
                try:
                    n = int(m.group(1))
                    return max(1, min(10, n))
                except Exception:
                    pass
    imp = headers.get("importance", "").lower()
    if imp in prio_map:
        return max(1, min(10, int(prio_map[imp])))
    return max(1, min(10, int(default_prio)))

def _wake_word_present(title: str, message: str) -> bool:
    both = f"{title} {message}".strip().lower()
    return both.startswith("jarvis ") or both.startswith("jarvis:") or " jarvis " in both

class AnyAuthenticator:
    def __init__(self, accept_any_auth: bool):
        self.accept_any_auth = accept_any_auth

    async def __call__(self, server, session, envelope, mechanism, auth_data):
        if not self.accept_any_auth:
            return AuthResult(success=False)
        if isinstance(auth_data, LoginPassword):
            return AuthResult(success=True)
        return AuthResult(success=True)

class JarvisSMTPHandler:
    def __init__(self, cfg: dict, send_message_fn: Callable[[str, str, int, Optional[dict]], bool]):
        self.cfg = cfg
        self.send_message = send_message_fn
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

    def _llm_then_beautify(self, title: str, body: str):
        # If wake-word present or LLM disabled/missing → beautify only
        if _wake_word_present(title, body) or not (self.llm_enabled and _llm and hasattr(_llm, "rewrite")):
            return beautify_message(title, body, mood=self.mood, source_hint="smtp")

        def _call():
            try:
                rewritten = _llm.rewrite(
                    text=body,
                    mood=self.mood,
                    timeout=self.llm_timeout,
                    cpu_limit=self.llm_cpu,
                    model_path=self.llm_model_path,
                )
                return beautify_message(title, rewritten, mood=self.mood, source_hint="smtp")
            except Exception:
                return beautify_message(title, body, mood=self.mood, source_hint="smtp")

        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_call)
            try:
                return fut.result(timeout=max(1, self.llm_timeout))
            except FuturesTimeout:
                return beautify_message(title, body, mood=self.mood, source_hint="smtp")

    async def handle_DATA(self, server, session, envelope):
        try:
            if self.allowed_rcpt and all(rcpt.lower() != self.allowed_rcpt for rcpt in envelope.rcpt_tos):
                return "550 relaying denied"
            msg = BytesParser(policy=policy.default).parsebytes(envelope.content or b"")

            headers = {k.lower(): str(v) for (k, v) in msg.items()}
            subject = str(msg.get("subject", "") or "")
            priority = _choose_priority(headers, self.default_prio, self.prio_map)

            text_body = ""
            if self.allow_html:
                html = msg.get_body(preferencelist=("html",))
                if html:
                    text_body = _strip_html(str(html.get_content()))
            if not text_body:
                text = msg.get_body(preferencelist=("plain",))
                if text:
                    text_body = str(text.get_content())

            title = f"{self.rewrite_prefix} {subject}".strip() if self.rewrite_prefix else (subject or "Message")
            body = text_body or "(no content)"

            # LLM → Beautify with timeout fallback
            final, extras = self._llm_then_beautify(title, body)

            self.send_message(title, final, priority=priority, extras=extras)
            return "250 OK"
        except Exception as e:
            try:
                self.send_message("[SMTP]", f"Parse error: {e}", priority=3, extras=None)
            except Exception:
                pass
            return "451 internal error"

class JarvisSMTPServer(Controller):
    def __init__(self, cfg: dict, send_message_fn: Callable[[str, str, int, Optional[dict]], bool]):
        self.cfg = cfg
        self.handler = JarvisSMTPHandler(cfg, send_message_fn)
        bind = str(cfg.get("smtp_bind", "0.0.0.0"))
        port = int(cfg.get("smtp_port", 2525))
        max_bytes = int(cfg.get("smtp_max_bytes", 262144))
        auth = bool(cfg.get("smtp_accept_any_auth", False))
        super().__init__(self.handler, hostname=bind, port=port, auth_required=False, authenticator=AnyAuthenticator(auth), data_size_limit=max_bytes)
