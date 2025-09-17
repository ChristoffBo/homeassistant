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
# Basic env + config loader
# ============================

OPTIONS_PATH = "/data/options.json"
STATE_PATH   = "/data/state.json"

def load_options() -> dict:
    try:
        with open(OPTIONS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: dict):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"[bot] save_state failed: {e}")

def load_state() -> dict:
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

# ============================
# Global state
# ============================
STATE = load_state()
if "seen" not in STATE:
    STATE["seen"] = []
if "seq" not in STATE:
    STATE["seq"] = 0

def remember_msgid(msgid: str):
    seen = STATE.get("seen", [])
    seen.append(msgid)
    if len(seen) > 200:
        seen = seen[-200:]
    STATE["seen"] = seen
    save_state(STATE)

def already_seen(msgid: str) -> bool:
    return msgid in STATE.get("seen", [])
# ============================
# Notifier / Emit helpers
# ============================

EMIT_URL = os.getenv("JARVIS_INTERNAL_EMIT_URL", "http://127.0.0.1:2599/internal/emit")

def emit(title: str, message: str, priority: int = 5, tags: list[str] = None, raw: bool = False):
    """Send a structured message into Jarvis’s internal emitter."""
    payload = {
        "source": "bot",
        "title": title,
        "message": message,
        "priority": priority,
        "tags": tags or [],
        "app": "Jarvis Prime",
        "extras": {"jarvis::raw": raw},
    }
    try:
        r = requests.post(EMIT_URL, json=payload, timeout=6)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[bot] emit failed: {e}")
        return False

def notify_error(e: Exception, context: str = "bot"):
    """Error notification wrapper, respects error_notifications option."""
    opts = load_options()
    if not opts.get("error_notifications", True):
        return
    msg = f"⚠️ {context} error: {e}"
    emit("Error", msg, priority=3, tags=["error"])
# ============================
# LLM + Persona integration
# ============================

try:
    import llm_client
    import personality
except ImportError:
    llm_client = None
    personality = None

def run_llm_rewrite(text: str) -> str:
    """Rewrite input text via LLM if enabled in options."""
    opts = load_options()
    if not opts.get("llm_rewrite_enabled", False):
        return text
    if not llm_client:
        return text
    try:
        return llm_client.rewrite(text)
    except Exception as e:
        notify_error(e, "llm_rewrite")
        return text

def run_persona_riff(text: str) -> str:
    """Run persona riff if enabled."""
    opts = load_options()
    if not opts.get("llm_persona_riffs_enabled", True):
        return text
    if not llm_client or not personality:
        return text
    try:
        return llm_client.persona_riff(text)
    except Exception as e:
        notify_error(e, "llm_riff")
        return text
# ============================
# Ingest Handlers
# ============================

def handle_smtp(msgid: str, subject: str, body: str):
    """Process incoming SMTP messages."""
    if already_seen(msgid):
        return
    remember_msgid(msgid)
    text = f"{subject}\n{body}".strip()
    text = run_llm_rewrite(text)
    text = run_persona_riff(text)
    emit(f"SMTP: {subject}", text, tags=["smtp"])

def handle_proxy(title: str, message: str):
    """Process Proxy passthrough messages."""
    key = hashlib.sha1(f"proxy:{title}:{message}".encode()).hexdigest()
    if already_seen(key):
        return
    remember_msgid(key)
    text = run_llm_rewrite(message)
    text = run_persona_riff(text)
    emit(f"Proxy: {title}", text, tags=["proxy"])

def handle_webhook(payload: dict):
    """Handle webhook POSTs."""
    try:
        text = json.dumps(payload)
    except Exception:
        text = str(payload)
    key = hashlib.sha1(text.encode()).hexdigest()
    if already_seen(key):
        return
    remember_msgid(key)
    text = run_llm_rewrite(text)
    text = run_persona_riff(text)
    emit("Webhook", text, tags=["webhook"])

def handle_apprise(title: str, message: str):
    """Process Apprise ingestion."""
    key = hashlib.sha1(f"apprise:{title}:{message}".encode()).hexdigest()
    if already_seen(key):
        return
    remember_msgid(key)
    text = run_llm_rewrite(message)
    text = run_persona_riff(text)
    emit(f"Apprise: {title}", text, tags=["apprise"])
# ============================
# Heartbeat + Digest
# ============================

import heartbeat
import digest

def _heartbeat_scheduler_loop():
    """Scheduler for heartbeat messages."""
    opts = load_options()
    if not opts.get("heartbeat_enabled", False):
        return
    interval = int(opts.get("heartbeat_interval_minutes", 120))
    while True:
        try:
            title, msg = heartbeat.build_heartbeat(opts)
            emit(title, msg, priority=3, tags=["heartbeat"])
        except Exception as e:
            notify_error(e, "heartbeat")
        time.sleep(max(60, interval * 60))

def _digest_scheduler_loop():
    """Scheduler for digest messages."""
    opts = load_options()
    if not opts.get("digest_enabled", False):
        return
    interval = int(opts.get("digest_interval_minutes", 360))
    while True:
        try:
            title, msg = digest.build_digest(opts)
            emit(title, msg, priority=3, tags=["digest"])
        except Exception as e:
            notify_error(e, "digest")
        time.sleep(max(60, interval * 60))
# ============================
# Personality / Jokes
# ============================

def _joke_scheduler_loop():
    """Scheduler for jokes/quirks from personality engine."""
    opts = load_options()
    if not opts.get("personality_enabled", False):
        return
    interval = int(opts.get("personality_min_interval_minutes", 90))
    while True:
        try:
            import personality
            if personality._eligible_to_post():
                # 🔧 PATCHED LINE BELOW
                personality._post_one()  # only once per cycle, no spam burst
        except Exception as e:
            notify_error(e, "personality")
        time.sleep(max(60, interval * 60))
# ============================
# Chat Commands
# ============================

def _chat_scheduler_loop():
    """Background loop that listens for chat wakewords."""
    opts = load_options()
    if not opts.get("chat_enabled", False):
        return
    poll = int(opts.get("chat_poll_seconds", 30))
    while True:
        try:
            import chat
            events = chat.poll_events()
            for ev in events:
                try:
                    title, msg = chat.handle_event(ev)
                    if title and msg:
                        emit(title, msg, priority=4, tags=["chat"])
                except Exception as e:
                    notify_error(e, "chat_event")
        except Exception as e:
            notify_error(e, "chat")
        time.sleep(max(5, poll))
# ============================
# Startup
# ============================

def main():
    opts = load_options()

    # Fire background loops in threads
    threads = []

    if opts.get("heartbeat_enabled", False):
        t = threading.Thread(target=_heartbeat_scheduler_loop, name="heartbeat", daemon=True)
        t.start()
        threads.append(t)

    if opts.get("digest_enabled", False):
        t = threading.Thread(target=_digest_scheduler_loop, name="digest", daemon=True)
        t.start()
        threads.append(t)

    if opts.get("personality_enabled", False):
        t = threading.Thread(target=_joke_scheduler_loop, name="personality", daemon=True)
        t.start()
        threads.append(t)

    if opts.get("chat_enabled", False):
        t = threading.Thread(target=_chat_scheduler_loop, name="chat", daemon=True)
        t.start()
        threads.append(t)

    # Keep main thread alive
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[bot] exiting on keyboard interrupt")

if __name__ == "__main__":
    main()