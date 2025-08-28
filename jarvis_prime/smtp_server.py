# /app/smtp_server.py
# LAN-only SMTP intake for Jarvis Prime (aiosmtpd).
# Accepts any AUTH creds when smtp_accept_any_auth = true.
# Parses subject/body, LLM → Beautify with timeout fallback, then posts via send_message.
# Preserves: recipient gate, priority mapping, HTML stripping, inline image handling.

from __future__ import annotations
import re
import json
from typing import Callable, Optional, Dict
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

# ---------------- Utilities ----------------

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
        try:
            return max(1, min(10, int(prio_map[imp])))
        except Exception:
            pass
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

# ---------------- SMTP Handler ----------------

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

        # Neural Core settings (from options.json)
        self.mood = str(cfg.get("personality_mood", "serious"))
        self.llm_enabled = bool(cfg.get("llm_enabled", False))
        self.llm_timeout = int(cfg.get("llm_timeout_seconds", 5))
        self.llm_cpu = int(cfg.get("llm_max_cpu_percent", 70))
        self.llm_model_path = str(cfg.get("llm_model_path", ""))

        # Footer (always on per your instruction)
        self.show_engine_footer = True

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        # Preserve original: collect RCPTs; gate in DATA
        envelope.rcpt_tos.append(address)
        return "250 OK"

    def _llm_then_beautify(self, title: str, body: str):
        mood = self.mood or "serious"

        # Wake-word or LLM unavailable -> beautify only
        if _wake_word_present(title, body) or not (self.llm_enabled and _llm and hasattr(_llm, "rewrite_with_info")):
            text, bx = beautify_message(title, body, mood=mood, source_hint="mail")
            if self.show_engine_footer:
                text = f"{text}\n[Beautify fallback]"
            return text, bx

        def _call():
            try:
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
            except Exception:
                t, bx = beautify_message(title, body, mood=mood, source_hint="mail")
                if self.show_engine_footer:
                    t = f"{t}\n[Beautify fallback]"
                return t, bx

        # Hard timeout using a thread (keeps aiosmtpd loop responsive)
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_call)
            try:
                return fut.result(timeout=max(1, self.llm_timeout))
            except FuturesTimeout:
                t, bx = beautify_message(title, body, mood=mood, source_hint="mail")
                if self.show_engine_footer:
                    t = f"{t}\n[Beautify fallback]"
                return t, bx

    async def handle_DATA(self, server, session, envelope):
        # Gate by recipient
        rcpts = [r.lower() for r in (envelope.rcpt_tos or [])]
        if self.allowed_rcpt and self.allowed_rcpt not in rcpts:
            return f"550 No valid recipient for Jarvis (expected {self.allowed_rcpt})"

        try:
            msg = BytesParser(policy=policy.default).parsebytes(
                getattr(envelope, "original_content", None) or envelope.content
            )
        except Exception:
            return "451 Unable to parse message"

        subject = (msg.get("subject", "") or "").strip()
        from_addr = msg.get("from", "") or ""
        title = subject or "(no subject)"
        if self.rewrite_prefix:
            title = f"{self.rewrite_prefix} {title}"

        headers = {k.lower(): str(v) for (k, v) in msg.items()}

        text_body: Optional[str] = None
        html_body: Optional[str] = None
        attach_count = 0

        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdispo = (part.get_content_disposition() or "").lower()
                if cdispo == "attachment":
                    attach_count += 1
                    continue
                try:
                    payload = part.get_content()
                except Exception:
                    payload = None
                if payload is None:
                    continue
                if ctype == "text/plain" and text_body is None:
                    text_body = str(payload)
                elif ctype == "text/html" and html_body is None:
                    html_body = str(payload)
        else:
            ctype = msg.get_content_type()
            try:
                payload = msg.get_content()
            except Exception:
                payload = None
            if ctype == "text/plain":
                text_body = str(payload or "")
            elif ctype == "text/html":
                html_body = str(payload or "")

        if not text_body and html_body and self.allow_html:
            text_body = _strip_html(html_body)
        if not text_body:
            text_body = "(no content)"

        # Optional notes
        notes = []
        if from_addr:
            notes.append(f"From: {from_addr}")
        if attach_count > 0:
            notes.append(f"(+{attach_count} attachments ignored)")
        if notes:
            text_body = f"{text_body}\n\n" + "\n".join(notes)

        priority = _choose_priority(headers, self.default_prio, self.prio_map)

        # ---------- LLM → Beautifier (with timeout + footer) ----------
        final, bx = self._llm_then_beautify(title, text_body)

        # Inline big image if beautifier exposed one and inlining is allowed
        if bool(self.cfg.get("beautify_inline_images", False)) and bx and bx.get("client::notification", {}).get("bigImageUrl"):
            img = bx["client::notification"]["bigImageUrl"]
            final = f"![image]({img})\n\n{final}"

        # Post to Gotify
        self.send_message(title, final, priority=priority, extras=bx)
        return "250 Accepted"

# ---------------- Controller ----------------

class JarvisSMTPController:
    def __init__(self, cfg: dict, send_message_fn: Callable[[str, str, int, Optional[dict]], bool]):
        self.cfg = cfg
        self.handler = JarvisSMTPHandler(cfg, send_message_fn)
        self.controller: Optional[Controller] = None

    def start(self):
        host = str(self.cfg.get("smtp_bind", "0.0.0.0"))
        port = int(self.cfg.get("smtp_port", 2525))
        max_bytes = int(self.cfg.get("smtp_max_bytes", 262144))
        accept_any_auth = bool(self.cfg.get("smtp_accept_any_auth", True))
        self.controller = Controller(
            self.handler,
            hostname=host,
            port=port,
            authenticator=AnyAuthenticator(accept_any_auth),
            auth_required=False,
            data_size_limit=max_bytes,
        )
        self.controller.start()
        print(f"[Jarvis SMTP] Listening on {host}:{port} (max {max_bytes} bytes, accept_any_auth={accept_any_auth})")

    def stop(self):
        try:
            if self.controller:
                self.controller.stop()
                print("[Jarvis SMTP] Stopped")
        except Exception:
            pass

_controller: Optional[JarvisSMTPController] = None

def start_smtp(cfg: dict, send_message_fn: Callable[[str, str, int, Optional[dict]], bool]) -> None:
    """Start the SMTP controller exactly once."""
    global _controller
    if _controller:
        return
    _controller = JarvisSMTPController(cfg, send_message_fn)
    _controller.start()
