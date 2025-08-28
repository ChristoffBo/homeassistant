# /app/smtp_server.py
import asyncio, email, re
from email.message import EmailMessage
from typing import Optional, Tuple

from aiosmtpd.controller import Controller
from aiosmtpd.handlers import AsyncMessage

BOT_NAME = "Jarvis Prime"

SEND = None
STATE = None

_llm = None
_beautify = None

def _load_helpers():
    global _llm, _beautify
    try:
        import importlib.util as _imp
        spec = _imp.spec_from_file_location("llm_client", "/app/llm_client.py")
        if spec and spec.loader:
            _llm = _imp.module_from_spec(spec)
            spec.loader.exec_module(_llm)
            print(f"[{BOT_NAME}] ✅ llm_client loaded (smtp)")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ llm_client not loaded (smtp): {e}")

    try:
        import importlib.util as _imp
        bspec = _imp.spec_from_file_location("beautify", "/app/beautify.py")
        if bspec and bspec.loader:
            _beautify = _imp.module_from_spec(bspec)
            bspec.loader.exec_module(_beautify)
            print(f"[{BOT_NAME}] ✅ beautify.py loaded (smtp)")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ beautify not loaded (smtp): {e}")

def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _wake_word_present(title: str, message: str) -> bool:
    t = (title or "").lower().strip()
    m = (message or "").lower().strip()
    return t.startswith("jarvis") or m.startswith("jarvis")

def _llm_then_beautify(title: str, message: str) -> Tuple[str, Optional[dict]]:
    used_llm = False
    used_beautify = False
    final = message
    extras = None

    # Skip LLM for wake-word (so commands are not rewritten)
    if not _wake_word_present(title, message) and (STATE and STATE.llm_enabled and _llm and hasattr(_llm, "rewrite")):
        try:
            print(f"[{BOT_NAME}] [SMTP] → LLM.rewrite start")
            msg = _llm.rewrite(
                text=message,
                mood=STATE.chat_mood,
                timeout=STATE.llm_timeout_seconds,
                cpu_limit=STATE.llm_max_cpu_percent,
                models_priority=STATE.llm_models_priority,
                base_url=STATE.ollama_base_url,
                model_url=STATE.llm_model_url,
                model_path=STATE.llm_model_path,
                model_sha256=STATE.llm_model_sha256,
                allow_profanity=STATE.personality_allow_profanity,
            )
            if msg:
                final = msg
                used_llm = True
                print(f"[{BOT_NAME}] [SMTP] ✓ LLM.rewrite done")
        except Exception as e:
            print(f"[{BOT_NAME}] [SMTP] ⚠️ LLM skipped: {e}")

    if _beautify and hasattr(_beautify, "beautify_message"):
        try:
            final, extras = _beautify.beautify_message(title, final, mood=STATE.chat_mood)
            used_beautify = True
        except Exception as e:
            print(f"[{BOT_NAME}] [SMTP] ⚠️ Beautify failed: {e}")

    final = f"{final}\n\n{_footer(used_llm, used_beautify)}"
    return final, extras

class JarvisSMTPHandler(AsyncMessage):
    async def handle_message(self, message: EmailMessage) -> None:
        try:
            subject = message.get("Subject", "Email")
            # prefer plain text
            body = ""
            if message.is_multipart():
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
                        break
            else:
                body = message.get_payload(decode=True).decode(message.get_content_charset() or "utf-8", errors="ignore")

            final, extras = _llm_then_beautify(subject, body)
            SEND(subject, final, priority=5, extras=extras)
        except Exception as e:
            print(f"[{BOT_NAME}] [SMTP] handler error: {e}")

def start_smtp(cfg, send_fn):
    """
    Launch a local SMTP server for intake (no auth).
    """
    global SEND, STATE
    SEND = send_fn

    class _State:
        pass
    STATE = _State()
    STATE.chat_mood = cfg.get("personality_mood", cfg.get("chat_mood", "serious"))
    STATE.llm_enabled = bool(cfg.get("llm_enabled", False))
    STATE.llm_timeout_seconds = int(cfg.get("llm_timeout_seconds", 12))
    STATE.llm_max_cpu_percent = int(cfg.get("llm_max_cpu_percent", 70))
    STATE.llm_models_priority = cfg.get("llm_models_priority", [])
    STATE.ollama_base_url     = cfg.get("ollama_base_url", "")
    STATE.llm_model_url       = cfg.get("llm_model_url", "")
    STATE.llm_model_path      = cfg.get("llm_model_path", "")
    STATE.llm_model_sha256    = cfg.get("llm_model_sha256", "")
    STATE.personality_allow_profanity = bool(cfg.get("personality_allow_profanity", False))

    host = cfg.get("smtp_bind", "0.0.0.0")
    port = int(cfg.get("smtp_port", 2525))
    max_bytes = int(cfg.get("smtp_max_bytes", 262144))
    accept_any_auth = bool(cfg.get("smtp_accept_any_auth", True))

    _load_helpers()

    handler = JarvisSMTPHandler()
    controller = Controller(
        handler,
        hostname=host,
        port=port,
        decode_data=True,
        ident="JarvisSMTP",
        authenticator=None if accept_any_auth else lambda *_: False,
        data_size_limit=max_bytes,
    )
    controller.start()
    print(f"[{BOT_NAME}] [Jarvis SMTP] Listening on {host}:{port} (max {max_bytes} bytes, accept_any_auth={accept_any_auth})")
