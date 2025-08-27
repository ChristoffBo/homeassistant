import asyncio
import re
from email import policy
from email.parser import BytesParser
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword
from typing import Callable, Optional, Dict, Any


class AnyAuthenticator:
    """
    Accept ANY username/password if enabled.
    aiosmtpd will advertise AUTH when an authenticator is provided.
    """

    def __init__(self, accept_any_auth: bool):
        self.accept_any_auth = accept_any_auth

    async def __call__(self, server, session, envelope, mechanism, auth_data):
        # If disabled, refuse and let clients fall back to no-auth
        if not self.accept_any_auth:
            return AuthResult(success=False)

        # LOGIN: auth_data is LoginPassword(login=..., password=...)
        # PLAIN: auth_data is LoginPassword as well
        if isinstance(auth_data, LoginPassword):
            # Accept anything
            return AuthResult(success=True)
        # Other mechanisms: also accept
        return AuthResult(success=True)


def _strip_html(html: str) -> str:
    # Super-simple fallback sanitizer (keeps text only)
    # Avoids extra dependencies; good enough for alerts
    # Remove scripts/styles
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    # Remove tags
    html = re.sub(r"(?s)<[^>]+>", "", html)
    # Unescape common entities
    html = html.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    # Collapse whitespace
    html = re.sub(r"[ \t\r\f\v]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _choose_priority(headers: Dict[str, str], default_prio: int, prio_map: Dict[str, int]) -> int:
    # 1) Numeric from X-Priority / Priority (1..10)
    for key in ("x-priority", "priority"):
        if key in headers:
            m = re.search(r"(\d+)", headers[key])
            if m:
                try:
                    n = int(m.group(1))
                    return max(1, min(10, n))
                except Exception:
                    pass
    # 2) Importance mapping: high|normal|low
    imp = headers.get("importance", "").lower()
    if imp in prio_map:
        return max(1, min(10, int(prio_map[imp])))
    return max(1, min(10, int(default_prio)))


class JarvisSMTPHandler:
    """
    Minimal handler:
      - Enforce at least one RCPT == dummy_rcpt
      - Parse Subject/Body
      - Size limit enforced by Controller(data_size_limit)
      - Call send_message_fn(title, message, priority, extras=None)
    """
    def __init__(self, cfg: dict, send_message_fn: Callable[[str, str, int, Optional[dict]], bool]):
        self.cfg = cfg
        self.send_message = send_message_fn
        self.allowed_rcpt = (str(cfg.get("smtp_dummy_rcpt", "alerts@jarvis.local")) or "").lower()
        self.rewrite_prefix = str(cfg.get("smtp_rewrite_title_prefix", "[SMTP]")).strip()
        self.allow_html = bool(cfg.get("smtp_allow_html", False))
        self.default_prio = int(cfg.get("smtp_priority_default", 5))
        # priority map is stored as JSON string in options; but if it arrives as dict, handle both
        raw_map = cfg.get("smtp_priority_map", {"high": 7, "urgent": 8, "critical": 9, "low": 3, "normal": 5})
        if isinstance(raw_map, str):
            try:
                import json
                raw_map = json.loads(raw_map)
            except Exception:
                raw_map = {"high": 7, "urgent": 8, "critical": 9, "low": 3, "normal": 5}
        self.prio_map = {str(k).lower(): int(v) for k, v in (raw_map or {}).items()}

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        # Accept only if at least one RCPT equals dummy_rcpt
        rcpt_l = (address or "").lower()
        if rcpt_l == self.allowed_rcpt:
            envelope.rcpt_tos.append(address)
            return "250 OK"
        # Allow other recipients through, but we’ll check final set in DATA
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        # Enforce our rcpt rule: must include allowed_rcpt
        rcpts = [r.lower() for r in (envelope.rcpt_tos or [])]
        if self.allowed_rcpt not in rcpts:
            return "550 No valid recipient for Jarvis (expected %s)" % self.allowed_rcpt

        try:
            msg = BytesParser(policy=policy.default).parsebytes(envelope.original_content or envelope.content)
        except Exception:
            return "451 Unable to parse message"

        subject = msg.get("subject", "").strip()
        from_addr = msg.get("from", "")
        # Title
        title = subject or "(no subject)"
        if self.rewrite_prefix:
            title = f"{self.rewrite_prefix} {title}"

        # Headers map (lower-cased)
        headers = {k.lower(): str(v) for (k, v) in msg.items()}

        # Body: prefer text/plain
        text_body = None
        html_body = None
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

        # Optional footer notes
        notes = []
        if from_addr:
            notes.append(f"From: {from_addr}")
        if attach_count > 0:
            notes.append(f"(+{attach_count} attachments ignored)")
        if notes:
            text_body = f"{text_body}\n\n" + "\n".join(notes)

        # Priority mapping
        priority = _choose_priority(headers, self.default_prio, self.prio_map)

        # Send through Jarvis pipeline (beautify + personality happen inside)
        self.send_message(title, text_body, priority=priority, extras=None)
        return "250 Accepted"


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

        authenticator = AnyAuthenticator(accept_any_auth)
        # Controller will advertise AUTH if authenticator is provided
        self.controller = Controller(
            self.handler,
            hostname=host,
            port=port,
            authenticator=authenticator,
            auth_required=False,  # don’t force AUTH
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
    global _controller
    if _controller:
        return
    _controller = JarvisSMTPController(cfg, send_message_fn)
    _controller.start()
