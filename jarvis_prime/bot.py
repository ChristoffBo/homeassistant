#!/usr/bin/env python3
# /app/bot.py
# Jarvis Prime – Bot Core (Neural Core edition)
#
# Key behaviors:
# - Cool boot card with Neural Core section (model path + memory) and pipeline line.
# - LLM-first (rewrite with mood/personality) ➜ Beautifier polish.
# - Fallbacks: when LLM disabled/unavailable/timeout ➜ Beautifier full pipeline.
# - SMTP & Proxy route into the SAME pipeline.
# - Wake-words/commands:
#     jarvis mood <angry|playful|serious|sarcastic|hacker-noir>
#     jarvis what happened today
#     jarvis what broke today
# - Footer: "[Neural Core ✓]" only if LLM actually rewrote; else "[Beautifier]".
# - Silent repost: delete original Gotify message after repost.
#
from __future__ import annotations

import os
import re
import json
import time
import asyncio
import schedule
import requests
import websockets

from pathlib import Path
from typing import Optional, Dict, Any

# -------------------------------
# Environment / Config
# -------------------------------
def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "")
    if v == "" or v is None:
        return default
    return str(v).lower() in ("1", "true", "yes", "on")

BOT_NAME   = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON   = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = (os.getenv("GOTIFY_URL", "") or "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
JARVIS_APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS        = int(os.getenv("RETENTION_HOURS", "24"))
BEAUTIFY_ENABLED       = _env_bool("BEAUTIFY_ENABLED", True)
SILENT_REPOST          = _env_bool("SILENT_REPOST", True)

# Modules toggles (for boot card display)
RADARR_ENABLED     = _env_bool("RADARR_ENABLED", False)
SONARR_ENABLED     = _env_bool("SONARR_ENABLED", False)
WEATHER_ENABLED    = _env_bool("WEATHER_ENABLED", False)
UPTIMEKUMA_ENABLED = _env_bool("uptimekuma_enabled", False)
SMTP_ENABLED       = _env_bool("smtp_enabled", False)
PROXY_ENABLED      = _env_bool("proxy_enabled", False)
TECHNITIUM_ENABLED = _env_bool("technitium_enabled", False)

# Heartbeat window (not scheduling here—just placeholders for future use)
HEARTBEAT_ENABLED       = _env_bool("heartbeat_enabled", False)
HEARTBEAT_INTERVAL_MIN  = int(os.getenv("heartbeat_interval_minutes", "120"))
HEARTBEAT_START         = os.getenv("heartbeat_start", "06:00")
HEARTBEAT_END           = os.getenv("heartbeat_end", "20:00")

# Personality / Neural Core
PERSONALITY_PERSISTENT  = _env_bool("PERSONALITY_PERSISTENT", True)
CHAT_MOOD               = (os.getenv("personality_mood", "serious").strip().lower() or "serious")

LLM_ENABLED          = _env_bool("LLM_ENABLED", False)
LLM_MEMORY_ENABLED   = _env_bool("LLM_MEMORY_ENABLED", True)
LLM_TIMEOUT_SEC      = int(os.getenv("LLM_TIMEOUT_SECONDS", "5"))
LLM_MAX_CPU_PERCENT  = int(os.getenv("LLM_MAX_CPU_PERCENT", "70"))  # reserved, not enforced
LLM_MODEL_URL        = os.getenv("LLM_MODEL_URL", "")
LLM_MODEL_PATH       = os.getenv("LLM_MODEL_PATH", "/share/jarvis_prime/models/tinyllama-1.1b-chat.Q4_K_M.gguf")
LLM_MODEL_SHA256     = (os.getenv("LLM_MODEL_SHA256", "") or "")

# Storage paths
BASE_DIR    = Path("/share/jarvis_prime")
MEM_DIR     = BASE_DIR / "memory"
STATE_PATH  = BASE_DIR / "state.json"
MEM_EVENTS  = MEM_DIR / "events.json"

# -------------------------------
# Optional internal modules
# -------------------------------
try:
    from beautify import beautify_message
    _BEAUTIFY_OK = True
    print(f"[{BOT_NAME}] ✅ beautify module ready")
except Exception as e:
    _BEAUTIFY_OK = False
    print(f"[{BOT_NAME}] ⚠️ beautify import failed: {e}")
    def beautify_message(title: str, body: str, **kw):
        # last-resort identity
        return (f"{title}\n\n{body}".strip(), None)

try:
    import llm_client
    _LLM_CLIENT_OK = True
    print(f"[{BOT_NAME}] ✅ llm_client module ready")
except Exception as e:
    _LLM_CLIENT_OK = False
    llm_client = None
    print(f"[{BOT_NAME}] ⚠️ llm_client import failed: {e}")

try:
    import llm_memory
    _LLM_MEMORY_OK = True
    print(f"[{BOT_NAME}] ✅ llm_memory module ready")
except Exception as e:
    _LLM_MEMORY_OK = False
    llm_memory = None
    print(f"[{BOT_NAME}] ⚠️ llm_memory import failed: {e}")

try:
    import personality_state
    _PSTATE_OK = True
    print(f"[{BOT_NAME}] ✅ personality_state module ready")
except Exception as e:
    _PSTATE_OK = False
    personality_state = None
    print(f"[{BOT_NAME}] ⚠️ personality_state import failed: {e}")

# -------------------------------
# Helpers
# -------------------------------
def _mkdirs():
    try:
        MEM_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ cannot create {MEM_DIR}: {e}")
    try:
        Path(LLM_MODEL_PATH).parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ cannot create model dir: {e}")

def _ws_url() -> str:
    if GOTIFY_URL.startswith("https://"):
        return "wss://" + GOTIFY_URL[len("https://"):] + "/stream?token=" + CLIENT_TOKEN
    return "ws://" + GOTIFY_URL[len("http://"):] + "/stream?token=" + CLIENT_TOKEN

def _pipeline_line() -> str:
    if LLM_ENABLED:
        present = Path(LLM_MODEL_PATH).exists()
        return f"UI: LLM ➜ polish  ·  Model: {'present' if present else 'missing'}"
    return "UI: Beautifier full pipeline"

def _memory_on() -> bool:
    return LLM_MEMORY_ENABLED and _LLM_MEMORY_OK

def _quip(mood: str) -> str:
    m = (mood or "").lower()
    if m == "angry":         return "— Done. No BS."
    if m == "playful":       return "— Sparkly clean."
    if m == "sarcastic":     return "— Revolutionary. Truly."
    if m == "hacker-noir":   return "— Packet traced. Signal clean."
    return "— All set."

def _footer(used_llm: bool) -> str:
    return "[Neural Core ✓]" if used_llm else "[Beautifier]"

def _resolve_app_id() -> Optional[int]:
    try:
        r = requests.get(f"{GOTIFY_URL}/application", headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=8)
        r.raise_for_status()
        for app in r.json():
            if (app.get("name") or "").lower() == JARVIS_APP_NAME.lower():
                return app.get("id")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ resolve app id error: {e}")
    return None

def _gotify_post(title: str, message: str, *, priority: int = 5, extras: Optional[Dict[str, Any]] = None) -> bool:
    try:
        payload: Dict[str, Any] = {
            "title": f"{BOT_ICON} {BOT_NAME}: {title}",
            "message": message,
            "priority": int(priority),
        }
        if extras:
            payload["extras"] = extras
        r = requests.post(f"{GOTIFY_URL}/message?token={APP_TOKEN}", json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ send error: {e}")
        return False

def _purge_original(msg_id: Optional[int]):
    if not (SILENT_REPOST and msg_id):
        return
    try:
        r = requests.delete(
            f"{GOTIFY_URL}/message/{msg_id}",
            headers={"X-Gotify-Key": CLIENT_TOKEN},
            timeout=8
        )
        if r.status_code in (200, 204):
            print(f"[{BOT_NAME}] 🧹 purged original id={msg_id}")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ purge error: {e}")

def _neural_state_section() -> str:
    present = Path(LLM_MODEL_PATH).exists()
    lines = [
        "### Neural Core",
        f"- State – **{'ACTIVE' if LLM_ENABLED else 'OFF'}{' (model missing)' if (LLM_ENABLED and not present) else ''}**",
        f"- Model: `{Path(LLM_MODEL_PATH).name}`",
        f"- Memory: **{'ACTIVE' if _memory_on() else 'OFF'}**",
    ]
    return "\n".join(lines)

def startup_poster() -> str:
    subs = [
        ("Radarr", RADARR_ENABLED),
        ("Sonarr", SONARR_ENABLED),
        ("Weather", WEATHER_ENABLED),
        ("Uptime Kuma", UPTIMEKUMA_ENABLED),
        ("SMTP Intake", SMTP_ENABLED),
        ("DNS (Technitium)", TECHNITIUM_ENABLED),
    ]
    bullets = "\n".join([f"- {'🟢' if enabled else '⚫'} {name}" for name, enabled in subs])
    lines = [
        f"__{BOT_NAME} {BOT_ICON}__",
        "",
        "⚡ Boot sequence initiated...",
        "→ Personalities loaded",
        "→ Memory core mounted",
        "→ Network bridges linked",
        f"→ {_pipeline_line()}",
        (f"→ Model path: {LLM_MODEL_PATH}" if LLM_ENABLED else "→ Neural Core: OFF"),
        "🚀 Systems online — Jarvis is awake!",
        "",
        "### Subsystems",
        bullets,
        "",
        _neural_state_section(),
    ]
    return "\n".join(lines)

# -------------------------------
# Personality persistence
# -------------------------------
def _save_mood(mood: str):
    if not (PERSONALITY_PERSISTENT and _PSTATE_OK):
        return
    try:
        personality_state.save_mood(STATE_PATH, mood)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ save mood: {e}")

def _load_mood():
    global CHAT_MOOD
    if not (PERSONALITY_PERSISTENT and _PSTATE_OK):
        return
    try:
        m = personality_state.load_mood(STATE_PATH)
        if m:
            CHAT_MOOD = m
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ load mood: {e}")

# -------------------------------
# LLM (Neural Core) step
# -------------------------------
def _maybe_prefetch_model():
    # Best-effort; non-fatal
    try:
        if LLM_ENABLED and _LLM_CLIENT_OK:
            if not Path(LLM_MODEL_PATH).exists() and LLM_MODEL_URL:
                print(f"[{BOT_NAME}] 🔮 Prefetching model (bot)…")
                llm_client.prefetch_model()
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ prefetch error: {e}")

def _llm_rewrite(text: str, mood: str) -> tuple[str, bool]:
    """Return (rewritten_text, used_llm)."""
    if not (LLM_ENABLED and _LLM_CLIENT_OK):
        return text, False
    try:
        if not Path(LLM_MODEL_PATH).exists():
            return text, False
        out = llm_client.rewrite_text(prompt=text, mood=mood, timeout_s=LLM_TIMEOUT_SEC)
        if isinstance(out, str) and out.strip():
            return out.strip(), True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM rewrite failed: {e}")
    return text, False

# -------------------------------
# Memory
# -------------------------------
def _mem_store(title: str, text: str):
    if not _memory_on():
        return
    try:
        llm_memory.store_event(MEM_EVENTS, title=title, text=text)
        llm_memory.flush_older_than(MEM_EVENTS, hours=RETENTION_HOURS)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ memory log error: {e}")

def _mem_answer_today() -> str:
    if not _memory_on():
        return "Memory disabled."
    try:
        return llm_memory.summarize_today(MEM_EVENTS)
    except Exception:
        return "No events logged yet."

def _mem_answer_failures() -> str:
    if not _memory_on():
        return "Memory disabled."
    try:
        return llm_memory.failures_today(MEM_EVENTS)
    except Exception:
        return "No failures detected today."

# -------------------------------
# Core formatting pipeline
# -------------------------------
def process_and_send(title: str, body: str, *, priority: int = 5, extras: Optional[Dict[str, Any]] = None, source_hint: Optional[str] = None, msg_id: Optional[int] = None):
    """
    Unified entrypoint used by WS, Proxy, and SMTP.
    """
    # 0) Memory (raw)
    _mem_store(title, body)

    # 1) LLM rewrite (optional)
    rewritten, used_llm = _llm_rewrite(body, CHAT_MOOD)

    # 2) Beautify (polish or full)
    final_text, b_extras = beautify_message(title, rewritten, mood=CHAT_MOOD, source_hint=source_hint)

    # 3) Footer + quip
    final_text = f"{final_text}\n\n{_footer(used_llm)}\n{_quip(CHAT_MOOD)}"

    # 4) Merge extras (prefer hero from beautify)
    merged_extras = None
    if b_extras and extras:
        merged_extras = dict(extras)
        cn = dict(merged_extras.get("client::notification", {}))
        cb = dict(b_extras.get("client::notification", {}))
        if "bigImageUrl" not in cn and cb.get("bigImageUrl"):
            cn["bigImageUrl"] = cb["bigImageUrl"]
        if cn:
            merged_extras["client::notification"] = cn
    else:
        merged_extras = (b_extras or extras)

    # 5) Send + purge original
    if _gotify_post(title, final_text, priority=int(priority), extras=merged_extras):
        _purge_original(msg_id)

# -------------------------------
# Commands (wake-words)
# -------------------------------
async def _handle_command(full_text_lower: str):
    global CHAT_MOOD
    if full_text_lower.startswith("jarvis mood "):
        new = full_text_lower.split("jarvis mood ", 1)[1].strip()
        if new:
            CHAT_MOOD = new
            _save_mood(CHAT_MOOD)
            _gotify_post("Mood", f"Personality switched to **{CHAT_MOOD}**.\n\n[System]", priority=5)
        return
    if "what happened today" in full_text_lower:
        _gotify_post("Today", _mem_answer_today() + "\n\n[Memory]", priority=5)
        return
    if "what broke today" in full_text_lower:
        _gotify_post("Incidents", _mem_answer_failures() + "\n\n[Memory]", priority=5)
        return

# -------------------------------
# WS listener (Gotify)
# -------------------------------
async def ws_listener():
    uri = _ws_url()
    print(f"[{BOT_NAME}] 🌐 WS connect -> {uri}")
    while True:
        try:
            async with websockets.connect(uri, ping_interval=30, ping_timeout=20) as ws:
                async for raw in ws:
                    try:
                        evt = json.loads(raw)
                    except Exception:
                        continue
                    if evt.get("event") != "message":
                        continue
                    m = evt.get("message", {})
                    mid = m.get("id")
                    title = m.get("title") or ""
                    body  = m.get("message") or ""
                    prio  = int(m.get("priority") or 5)
                    extras = m.get("extras")

                    # skip our own reposts (they already include BOT_NAME in the title)
                    if str(title).startswith(f"{BOT_ICON} {BOT_NAME}:"):
                        continue

                    # commands
                    joined = f"{title} {body}".strip().lower()
                    if joined.startswith("jarvis "):
                        await _handle_command(joined)
                        continue

                    # quick source hint (for beautifier)
                    hint = None
                    if "sonarr" in joined: hint = "sonarr"
                    elif "radarr" in joined: hint = "radarr"

                    process_and_send(title, body, priority=prio, extras=extras, source_hint=hint, msg_id=mid)

        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ WS error: {e}")
            await asyncio.sleep(5)

# -------------------------------
# SMTP / Proxy starters
# -------------------------------
def start_smtp():
    if not SMTP_ENABLED:
        return
    try:
        import smtp_server
        smtp_server.start_smtp(os.environ, lambda t, b, **kw: process_and_send(t, b, **kw))
        print(f"[{BOT_NAME}] ✅ SMTP intake started")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ SMTP start error: {e}")

def start_proxy():
    if not PROXY_ENABLED:
        return
    try:
        import proxy
        proxy.start_proxy(os.environ, lambda t, b, **kw: process_and_send(t, b, **kw))
        print(f"[{BOT_NAME}] ✅ Proxy started")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Proxy start error: {e}")

# -------------------------------
# Scheduler loop (lightweight)
# -------------------------------
def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# -------------------------------
# Main
# -------------------------------
if __name__ == "__main__":
    _mkdirs()
    _load_mood()
    _maybe_prefetch_model()

    print(f"[{BOT_NAME}] 🧠 Prime Neural Boot")
    print(f"[{BOT_NAME}] {_pipeline_line()}")

    # Always post a startup card (never silent)
    _gotify_post("Startup", startup_poster(), priority=5)

    # Start ingestion modules
    start_smtp()
    start_proxy()

    # Event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(ws_listener())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
