#!/usr/bin/env python3
# /app/bot.py

import os
import json
import asyncio
import requests
import websockets
import re
import subprocess
import atexit
import time
import socket
import hashlib
from typing import List, Optional, Tuple

import re as _re_local, time as _time_local

_JUNK_LINE_RE = _re_local.compile(
    r'^\s*(Tone:|Context\s*\(|No\s+lists|No\s+numbers|No\s+JSON|No\s+labels)\b',
    _re_local.I
)

def _clean_payload(_s: str) -> str:
    if not _s:
        return ""
    s = _s.replace("\r", "").strip()
    # remove instruction/meta lines
    s = "\n".join(ln for ln in s.split("\n") if not _JUNK_LINE_RE.search(ln))
    # remove raw [poster](http...) lines (these should render as images separately if needed)
    s = "\n".join(ln for ln in s.split("\n") if not _re_local.search(r'\[poster\]\(https?://', ln, _re_local.I))
    # fix stray **http(s):** markdown artifacts
    s = _re_local.sub(r'\*+(https?://)', r'\1', s)
    # collapse excessive blank lines
    s = _re_local.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def _sanitize_riff(txt: str) -> str:
    """Keep riffs short and free of instruction lines; never let them pollute payload."""
    if not txt:
        return ""
    # strip instruction-ish lines and trim to 3 lines / 360 chars
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip() and not _JUNK_LINE_RE.search(ln)]
    out = "\n".join(lines[:3])[:360].rstrip()
    return out

def _append_riff_safe(base: str, context: str, timeout_s: int = 12) -> str:
    """
    Calls llm_client.riff_once(context, timeout_s) and appends as a quoted block
    only if a valid short riff is returned. If it fails/times out, returns base unchanged.
    """
    try:
        from llm_client import riff_once  # must return str|None
    except Exception:
        return base
    try:
        cand = riff_once(context=context or "", timeout_s=timeout_s)
        riff = _sanitize_riff(cand or "")
        if riff:
            return f"{base}\n\n> " + riff.replace("\n", "\n> ")
    except Exception:
        pass
    return base
# === /ADDITIVE ===


# --- ADDITIVE: import for persona switching ---
from personality_state import set_active_persona
# --- end additive ---

# ============================
# Inbox storage
# ============================
try:
    import storage  # /app/storage.py
    storage.init_db()
except Exception as _e:
    storage = None
    print(f"[bot] ⚠️ storage init failed: {_e}")

# ============================
# Basic env
# ============================
BOT_NAME  = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON  = os.getenv("BOT_ICON", "🧠")
# Output (Gotify used as one of many outputs; not hardwired as the only intake)
GOTIFY_URL   = os.getenv("GOTIFY_URL", "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
APP_NAME     = os.getenv("JARVIS_APP_NAME", "Jarvis")

SILENT_REPOST    = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# Feature toggles (env defaults; can be overridden by /data/options.json or /data/config.json)
RADARR_ENABLED     = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED     = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED    = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV   = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED       = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")
SMTP_ENABLED       = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")
PROXY_ENABLED_ENV  = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")

# Ingest toggles (which intakes to listen to)
INGEST_GOTIFY_ENABLED  = os.getenv("ingest_gotify_enabled", "true").lower() in ("1","true","yes")
INGEST_APPRISE_ENABLED = os.getenv("ingest_apprise_enabled", "true").lower() in ("1","true","yes")
INGEST_SMTP_ENABLED    = os.getenv("ingest_smtp_enabled", "true").lower() in ("1","true","yes")
INGEST_NTFY_ENABLED    = os.getenv("ingest_ntfy_enabled", "false").lower() in ("1","true","yes")  # handled by proxy sidecar

# Webhook feature toggles
WEBHOOK_ENABLED    = os.getenv("webhook_enabled", "false").lower() in ("1","true","yes")
WEBHOOK_BIND       = os.getenv("webhook_bind", "0.0.0.0")
WEBHOOK_PORT       = int(os.getenv("webhook_port", "2590"))

# Apprise intake sidecar (separate process)
INTAKE_APPRISE_ENABLED = os.getenv("intake_apprise_enabled", "false").lower() in ("1","true","yes")
INTAKE_APPRISE_TOKEN = os.getenv("intake_apprise_token", "")
INTAKE_APPRISE_ACCEPT_ANY_KEY = os.getenv("intake_apprise_accept_any_key", "true").lower() in ("1","true","yes")
INTAKE_APPRISE_ALLOWED_KEYS = [k for k in os.getenv("intake_apprise_allowed_keys", "").split(",") if k.strip()]
INTAKE_APPRISE_PORT = int(os.getenv("intake_apprise_port", "2591"))
INTAKE_APPRISE_BIND = os.getenv("intake_apprise_bind", "0.0.0.0")

# LLM toggles
LLM_REWRITE_ENABLED = os.getenv("LLM_REWRITE_ENABLED", "false").lower() in ("1","true","yes")
BEAUTIFY_LLM_ENABLED_ENV = os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() in ("1","true","yes")

# Defaults that get finalized after config load
PROXY_ENABLED = PROXY_ENABLED_ENV
CHAT_ENABLED_FILE = CHAT_ENABLED_ENV
DIGEST_ENABLED_FILE = DIGEST_ENABLED_ENV
# ============================
# Helpers
# ============================
def _load_json(path: str, default: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(default)

def _save_json(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[bot] ⚠️ failed to save {path}: {e}")

def _load_module(name: str, path: str):
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    except Exception as e:
        print(f"[bot] ⚠️ failed to load module {name}: {e}")
    return None

# ============================
# External Modules
# ============================
_beautify = _load_module("beautify", "/app/beautify.py")
_digest   = _load_module("digest", "/app/digest.py")
_chat     = _load_module("chat", "/app/chat.py")
_weather  = _load_module("weather", "/app/weather.py")
_radarr   = _load_module("radarr", "/app/radarr.py")
_sonarr   = _load_module("sonarr", "/app/sonarr.py")
_technit  = _load_module("technitium", "/app/technitium.py")
_kuma     = _load_module("uptimekuma", "/app/uptimekuma.py")
_smtp     = _load_module("smtp_intake", "/app/smtp_intake.py")
_proxy    = _load_module("proxy_intake", "/app/proxy_intake.py")
_webhook  = _load_module("webhook", "/app/webhook.py")

# --- ADDITIVE: chatbot module loader ---
_chatbot  = _load_module("chatbot", "/app/chatbot.py")
# --- end additive ---

# ============================
# Send message helper
# ============================
def send_message(title: str, message: str, priority: int = 5, decorate: bool = True):
    """
    Dispatch a message to Gotify (primary push path).
    """
    if not GOTIFY_URL or not APP_TOKEN:
        print("[bot] ⚠️ Gotify not configured, cannot send")
        return
    msg = message
    if decorate and BOT_ICON:
        msg = f"{BOT_ICON} {message}"
    try:
        requests.post(
            f"{GOTIFY_URL}/message?token={APP_TOKEN}",
            json={"title": title, "message": msg, "priority": priority},
            timeout=10,
        )
    except Exception as e:
        print(f"[bot] ⚠️ send_message failed: {e}")

# ============================
# Core processing
# ============================
_recent_hashes = {}

def _seen_recent(service: str, title: str, body: str) -> bool:
    """Avoid duplicates (hash of service+title+body)."""
    h = hashlib.sha256(f"{service}|{title}|{body}".encode()).hexdigest()
    now = _time_local.time()
    # 30s duplicate window
    if h in _recent_hashes and now - _recent_hashes[h] < 30:
        return True
    _recent_hashes[h] = now
    # prune old
    for k in list(_recent_hashes.keys()):
        if now - _recent_hashes[k] > 60:
            del _recent_hashes[k]
    return False

def _process_incoming(service: str, title: str, body: str, priority=5, raw=None):
    if not body:
        return
    if _seen_recent(service, title, body):
        return

    # --- ADDITIVE: chatbot wakeword handling ---
    try:
        if bool(merged.get("chatbot_enabled", False)):
            if (title or "").strip().lower() in ("chat", "talk"):
                if _chatbot and hasattr(_chatbot, "handle_message"):
                    reply = _chatbot.handle_message("gotify", body)
                    if reply:
                        send_message("Chat", reply, priority=priority, decorate=False)
                # stop further processing
                return
    except Exception as e:
        print(f"[bot] chatbot handoff failed: {e}")
    # --- end additive ---

    # Normal beautify + riff path
    msg = body
    if BEAUTIFY_ENABLED and _beautify and hasattr(_beautify, "process"):
        try:
            msg = _beautify.process(service, title, body, raw=raw) or body
        except Exception as e:
            print(f"[bot] beautify failed: {e}")
            msg = body

    msg = _append_riff_safe(msg, context=body)

    send_message(title or service, msg, priority=priority)
    if storage:
        try:
            storage.insert_message(service, title or service, msg, priority)
        except Exception as e:
            print(f"[bot] ⚠️ storage insert failed: {e}")
# ============================
# Config merge
# ============================
merged = {}

def load_config():
    global merged
    base = {
        "bot_name": BOT_NAME,
        "bot_icon": BOT_ICON,
        "jarvis_app_name": APP_NAME,
        "beautify_enabled": BEAUTIFY_ENABLED,
        "silent_repost": SILENT_REPOST,
        "chat_enabled": CHAT_ENABLED_FILE,
        "digest_enabled": DIGEST_ENABLED_FILE,
        "proxy_enabled": PROXY_ENABLED,
    }
    file_opts = _load_json("/data/options.json", base)
    merged = {**base, **file_opts}
    return merged

load_config()

# ============================
# Help text
# ============================
HELP_TEXT = """
📖 Jarvis Prime — Available Commands

Wakewords:
  • chat | talk   → Initiate chatbot session (via Gotify/ntfy)
  • dude, chick, nerd, rager, comedian, action, jarvis, ops → Switch persona
  • weather       → Current weather
  • digest        → Morning digest
  • help          → Show this help

Notes:
  - Chat requires `chatbot_enabled` in config.
  - All wakewords are case-insensitive.
"""

def handle_help():
    return HELP_TEXT

# ============================
# Persona Switching
# ============================
def handle_persona_switch(word: str) -> Optional[str]:
    persona_map = {
        "dude": "dude",
        "chick": "chick",
        "nerd": "nerd",
        "rager": "rager",
        "comedian": "comedian",
        "action": "action",
        "jarvis": "jarvis",
        "ops": "ops",
    }
    key = word.strip().lower()
    if key in persona_map:
        try:
            set_active_persona(persona_map[key])
            return f"✅ Persona switched to {persona_map[key]}"
        except Exception as e:
            return f"⚠️ Failed to switch persona: {e}"
    return None

# ============================
# Startup banner
# ============================
def boot_banner():
    cfg = merged
    lines = []
    lines.append(f"{BOT_ICON} {BOT_NAME} — Online")
    lines.append("")
    lines.append("Features:")
    lines.append(f"• Beautify: {'ON' if cfg.get('beautify_enabled') else 'OFF'}")
    lines.append(f"• Chat: {'ON' if cfg.get('chat_enabled') else 'OFF'}")
    lines.append(f"• Chatbot: {'ON' if cfg.get('chatbot_enabled') else 'OFF'}")  # ADDITIVE
    lines.append(f"• Digest: {'ON' if cfg.get('digest_enabled') else 'OFF'}")
    lines.append(f"• Proxy: {'ON' if cfg.get('proxy_enabled') else 'OFF'}")
    lines.append("")
    return "\n".join(lines)
# ============================
# Main loop helpers
# ============================
async def process_gotify_message(msg: dict):
    try:
        title = msg.get("title", "")
        body = msg.get("message", "")
        priority = msg.get("priority", 5)
        _process_incoming("gotify", title, body, priority=priority, raw=msg)
    except Exception as e:
        print(f"[bot] ⚠️ gotify msg failed: {e}")

async def gotify_ws_loop():
    if not GOTIFY_URL or not CLIENT_TOKEN:
        print("[bot] ⚠️ Gotify not configured for WS intake")
        return
    url = f"{GOTIFY_URL}/stream?token={CLIENT_TOKEN}"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                print("[bot] ✅ Connected to Gotify WS")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if isinstance(msg, dict):
                            await process_gotify_message(msg)
                    except Exception as e:
                        print(f"[bot] ⚠️ gotify parse failed: {e}")
        except Exception as e:
            print(f"[bot] ⚠️ gotify WS loop error: {e}")
            await asyncio.sleep(5)

async def run_digest():
    if not merged.get("digest_enabled"):
        return
    if not _digest or not hasattr(_digest, "run_digest"):
        return
    try:
        out = _digest.run_digest()
        if out:
            send_message("Digest", out, priority=5)
    except Exception as e:
        print(f"[bot] ⚠️ digest failed: {e}")

async def run_weather():
    if not merged.get("weather_enabled"):
        return
    if not _weather or not hasattr(_weather, "get_weather"):
        return
    try:
        out = _weather.get_weather()
        if out:
            send_message("Weather", out, priority=5)
    except Exception as e:
        print(f"[bot] ⚠️ weather failed: {e}")

# ============================
# Background tasks
# ============================
async def background_tasks():
    while True:
        try:
            if merged.get("digest_enabled"):
                await run_digest()
            if merged.get("weather_enabled"):
                await run_weather()
        except Exception as e:
            print(f"[bot] ⚠️ background task error: {e}")
        await asyncio.sleep(60)

# ============================
# Entrypoint
# ============================
async def main():
    load_config()
    banner = boot_banner()
    send_message("Boot", banner, priority=5, decorate=False)

    tasks = []
    if INGEST_GOTIFY_ENABLED:
        tasks.append(asyncio.create_task(gotify_ws_loop()))
    if INTAKE_APPRISE_ENABLED and _proxy and hasattr(_proxy, "start_apprise_server"):
        try:
            _proxy.start_apprise_server()
        except Exception as e:
            print(f"[bot] ⚠️ apprise intake start failed: {e}")
    if WEBHOOK_ENABLED and _webhook and hasattr(_webhook, "start_webhook_server"):
        try:
            _webhook.start_webhook_server(WEBHOOK_BIND, WEBHOOK_PORT)
        except Exception as e:
            print(f"[bot] ⚠️ webhook start failed: {e}")
    if SMTP_ENABLED and _smtp and hasattr(_smtp, "start_smtp_server"):
        try:
            _smtp.start_smtp_server()
        except Exception as e:
            print(f"[bot] ⚠️ smtp intake start failed: {e}")
    if PROXY_ENABLED and _proxy and hasattr(_proxy, "start_proxy_server"):
        try:
            _proxy.start_proxy_server()
        except Exception as e:
            print(f"[bot] ⚠️ proxy start failed: {e}")

    tasks.append(asyncio.create_task(background_tasks()))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[bot] Stopped by user")
# ============================
# CLI entrypoint for manual test
# ============================
def _cli_test():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("title", help="Message title")
    ap.add_argument("body", help="Message body")
    ap.add_argument("--prio", type=int, default=5)
    args = ap.parse_args()

    load_config()
    print("[bot] Config loaded")
    print(json.dumps(merged, indent=2))
    _process_incoming("cli", args.title, args.body, priority=args.prio)

# allow: python3 bot.py -- test
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        _cli_test()
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("[bot] Interrupted")
        except Exception as e:
            print(f"[bot] Fatal error: {e}")
