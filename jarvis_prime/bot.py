#!/usr/bin/env python3
# /app/bot.py
# Jarvis Prime – Bot Core (Neural Core edition)
#
# - Cool boot card with Neural Core section (model path + memory)
# - LLM first (rewrite with mood/personality) ➜ Beautifier polish
# - Fallbacks: if LLM disabled/unavailable/timeout ➜ Beautifier full pipeline
# - SMTP & Proxy feed into the same pipeline (no duplicate formatting)
# - Wake-words: 'jarvis mood <x>', 'jarvis what happened today', 'jarvis what broke today'
# - Footer: "[Neural Core ✓]" only if LLM actually rewrote; else "[Beautifier]"
#
from __future__ import annotations

import os, json, time, asyncio, re
from datetime import datetime
from pathlib import Path

import requests
import websockets
import schedule

# ---------- Config (from run.sh env) ----------
def _env_bool(key: str, default: bool=False) -> bool:
    v = os.getenv(key, "")
    if v == "" or v is None:
        return default
    return str(v).lower() in ("1","true","yes","on")

BOT_NAME   = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON   = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL", "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
JARVIS_APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS        = int(os.getenv("RETENTION_HOURS", "24"))
BEAUTIFY_ENABLED       = _env_bool("BEAUTIFY_ENABLED", True)
SILENT_REPOST          = _env_bool("SILENT_REPOST", True)

WEATHER_ENABLED        = _env_bool("WEATHER_ENABLED", False)  # not used here, just listed on boot
DIGEST_ENABLED         = _env_bool("DIGEST_ENABLED", False)
RADARR_ENABLED         = _env_bool("RADARR_ENABLED", False)
SONARR_ENABLED         = _env_bool("SONARR_ENABLED", False)
UPTIMEKUMA_ENABLED     = _env_bool("uptimekuma_enabled", False)
SMTP_ENABLED           = _env_bool("smtp_enabled", False)
PROXY_ENABLED          = _env_bool("proxy_enabled", False)
TECHNITIUM_ENABLED     = _env_bool("technitium_enabled", False)

HEARTBEAT_ENABLED      = _env_bool("heartbeat_enabled", False)
HEARTBEAT_INTERVAL_MIN = int(os.getenv("heartbeat_interval_minutes", "120"))
HEARTBEAT_START        = os.getenv("heartbeat_start", "06:00")
HEARTBEAT_END          = os.getenv("heartbeat_end", "20:00")

# Neural Core (LLM)
LLM_ENABLED            = _env_bool("LLM_ENABLED", False)
LLM_TIMEOUT_SEC        = int(os.getenv("LLM_TIMEOUT_SECONDS","5"))
LLM_MAX_CPU_PERCENT    = int(os.getenv("LLM_MAX_CPU_PERCENT","70"))  # reserved (not enforced w/o psutil)
LLM_MODEL_URL          = os.getenv("LLM_MODEL_URL", "")
LLM_MODEL_PATH         = os.getenv("LLM_MODEL_PATH","/share/jarvis_prime/models/tinyllama-1.1b-chat.Q4_K_M.gguf")
LLM_MODEL_SHA256       = (os.getenv("LLM_MODEL_SHA256","") or "")
PERSONALITY_PERSISTENT = _env_bool("PERSONALITY_PERSISTENT", True)
CHAT_MOOD              = os.getenv("personality_mood","serious").strip().lower() or "serious"

# Paths
BASE_DIR   = Path("/share/jarvis_prime")
MEM_DIR    = BASE_DIR / "memory"
STATE_PATH = BASE_DIR / "state.json"
MEM_EVENTS = MEM_DIR / "events.json"

# ---------- Imports of local modules ----------
try:
    from beautify import beautify_message
    print(f"[{BOT_NAME}] ✅ beautify loaded")
except Exception as e:
    def beautify_message(title, body, **kw):
        return f"{title}\n\n{body}", None
    print(f"[{BOT_NAME}] ⚠️ beautify not loaded: {e}")

try:
    import llm_client
    print(f"[{BOT_NAME}] ✅ llm_client loaded")
except Exception as e:
    llm_client = None
    print(f"[{BOT_NAME}] ⚠️ llm_client not loaded: {e}")

try:
    import llm_memory
    print(f"[{BOT_NAME}] ✅ llm_memory loaded")
except Exception as e:
    llm_memory = None
    print(f"[{BOT_NAME}] ⚠️ llm_memory not loaded: {e}")

try:
    import personality_state
    print(f"[{BOT_NAME}] ✅ personality_state loaded")
except Exception as e:
    personality_state = None
    print(f"[{BOT_NAME}] ⚠️ personality_state not loaded: {e}")

# Modules started later
modules = {}

# ---------- Utilities ----------
def _mkdirs():
    try:
        MEM_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ cannot create memory dir: {e}")

def _human_bool(b: bool) -> str:
    return "enabled" if b else "disabled"

def _ws_url() -> str:
    if GOTIFY_URL.startswith("https://"):
        return "wss://" + GOTIFY_URL[len("https://"):] + "/stream?token=" + CLIENT_TOKEN
    return "ws://" + GOTIFY_URL[len("http://"):] + "/stream?token=" + CLIENT_TOKEN

def _quip(mood: str) -> str:
    mood = (mood or "").lower()
    if mood == "angry":
        return "— Done. No BS."
    if mood == "playful":
        return "— Easy peasy, lemon squeezy."
    if mood == "sarcastic":
        return "— Shocking. Truly groundbreaking."
    if mood == "hacker-noir":
        return "— Packet traced. Signal clean."
    return "— All set."

def _pipeline_label() -> str:
    if LLM_ENABLED:
        present = Path(LLM_MODEL_PATH).exists()
        return f"UI: LLM ➜ polish  ·  Model: {'present' if present else 'missing'}"
    else:
        return "UI: Beautifier full pipeline"

def _neural_state_lines() -> list[str]:
    present = Path(LLM_MODEL_PATH).exists()
    state = "ACTIVE" if LLM_ENABLED else "OFF"
    return [
        "### Neural Core",
        f"- State – **{state}{' (model missing)' if (LLM_ENABLED and not present) else ''}**",
        f"- Model: `{Path(LLM_MODEL_PATH).name}`",
        f"- Memory: **{'ACTIVE' if _memory_active() else 'OFF'}**",
    ]

def _memory_active() -> bool:
    return bool(llm_memory) and _env_bool("LLM_MEMORY_ENABLED", True)

def _footer(used_llm: bool) -> str:
    return "[Neural Core ✓]" if used_llm else "[Beautifier]"

def _resolve_app_id() -> int | None:
    try:
        r = requests.get(f"{GOTIFY_URL}/application", headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=8)
        r.raise_for_status()
        for app in r.json():
            if (app.get("name") or "").lower() == JARVIS_APP_NAME.lower():
                return app.get("id")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ resolve app id: {e}")
    return None

JARVIS_APP_ID = None

def startup_poster() -> str:
    subs = [
        ("Radarr", RADARR_ENABLED),
        ("Sonarr", SONARR_ENABLED),
        ("Weather", WEATHER_ENABLED),
        ("Uptime Kuma", UPTIMEKUMA_ENABLED),
        ("SMTP Intake", SMTP_ENABLED),
        ("DNS (Technitium)", TECHNITIUM_ENABLED),
    ]
    bullets = "\n".join([f"- {'🟢' if on else '⚫'} {name}" for name, on in subs])
    lines = [
        f"__{BOT_NAME} {BOT_ICON}__",
        "",
        "⚡ Boot sequence initiated...",
        "→ Personalities loaded",
        "→ Memory core mounted",
        "→ Network bridges linked",
        f"→ {_pipeline_label()}",
        f"→ Model path: {LLM_MODEL_PATH}" if LLM_ENABLED else "→ Neural Core: OFF",
        "🚀 Systems online — Jarvis is awake!",
        "",
        "### Subsystems",
        bullets,
        "",
    ] + _neural_state_lines()
    return "\n".join(lines)

# ---------- Posting ----------
def _gotify_post(title: str, message: str, priority: int = 5, extras: dict | None = None) -> bool:
    try:
        payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": int(priority)}
        if extras:
            payload["extras"] = extras
        r = requests.post(f"{GOTIFY_URL}/message?token={APP_TOKEN}", json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ send error: {e}")
        return False

def _purge_original(msg_id: int):
    try:
        if not SILENT_REPOST or not msg_id:
            return
        r = requests.delete(f"{GOTIFY_URL}/message/{msg_id}", headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=8)
        if r.status_code in (200,204):
            print(f"[{BOT_NAME}] 🧹 purged original id={msg_id}")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ purge error: {e}")

# ---------- Core pipeline ----------
def _maybe_llm(title: str, body: str, mood: str) -> tuple[str, bool]:
    """Return (text, used_llm)"""
    if not (LLM_ENABLED and llm_client):
        return body, False
    try:
        # ensure local model file exists; llm_client handles download if called from run.sh too
        if not Path(LLM_MODEL_PATH).exists():
            print(f"[{BOT_NAME}] ⚠️ model missing at {LLM_MODEL_PATH}")
            return body, False
        text = llm_client.rewrite_text(prompt=body, mood=mood, timeout_s=LLM_TIMEOUT_SEC)
        if text and isinstance(text, str):
            return text.strip(), True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ LLM rewrite failed: {e}")
    return body, False

def process_and_send(title: str, body: str, *, priority: int = 5, extras: dict | None = None, source_hint: str | None = None, msg_id: int | None = None):
    """Single entry used by WS/Proxy/SMTP."""
    # 1) Neural rewrite (optional)
    rewritten, used_llm = _maybe_llm(title, body, CHAT_MOOD)

    # 2) Beautify polish or full pipeline
    final_text, b_extras = beautify_message(title, rewritten, mood=CHAT_MOOD, source_hint=source_hint)
    # 3) Footer + quip
    final_text = final_text + "\n\n" + _footer(used_llm) + "\n" + _quip(CHAT_MOOD)

    # 4) Memory log
    try:
        if _memory_active():
            llm_memory.store_event(MEM_EVENTS, title=title, text=body)
            llm_memory.flush_older_than(MEM_EVENTS, hours=RETENTION_HOURS)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ memory log error: {e}")

    # 5) Send
    merged_extras = None
    if b_extras and extras:
        # merge: prefer image from beautify
        merged_extras = dict(extras)
        cn = dict(merged_extras.get("client::notification", {}))
        cb = dict(b_extras.get("client::notification", {}))
        if "bigImageUrl" not in cn and cb.get("bigImageUrl"):
            cn["bigImageUrl"] = cb["bigImageUrl"]
        if cn:
            merged_extras["client::notification"] = cn
    else:
        merged_extras = (b_extras or extras)

    ok = _gotify_post(title, final_text, priority=priority, extras=merged_extras)
    if ok:
        _purge_original(msg_id)

# ---------- Commands ----------
def _set_mood(new: str) -> str:
    global CHAT_MOOD
    CHAT_MOOD = (new or "").strip().lower() or "serious"
    try:
        if PERSONALITY_PERSISTENT and personality_state:
            personality_state.save_mood(STATE_PATH, CHAT_MOOD)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ persist mood: {e}")
    return CHAT_MOOD

def _load_mood():
    global CHAT_MOOD
    if PERSONALITY_PERSISTENT and personality_state:
        m = personality_state.load_mood(STATE_PATH)
        if m:
            CHAT_MOOD = m

async def _handle_command(text: str):
    low = (text or "").strip().lower()
    if low.startswith("jarvis mood "):
        mood = low.split("jarvis mood ",1)[1].strip()
        _set_mood(mood)
        _gotify_post("Mood", f"Personality switched to **{CHAT_MOOD}**.\n\n[System]", priority=5)
        return
    if "what happened today" in low and _memory_active():
        try:
            summary = llm_memory.summarize_today(MEM_EVENTS)
        except Exception:
            summary = "No events logged yet."
        _gotify_post("Today", summary + "\n\n[Memory]", priority=5)
        return
    if "what broke today" in low and _memory_active():
        try:
            report = llm_memory.failures_today(MEM_EVENTS)
        except Exception:
            report = "Nothing obvious broke. For once."
        _gotify_post("Incidents", report + "\n\n[Memory]", priority=5)
        return

# ---------- WebSocket listener ----------
async def _ws_listen():
    uri = _ws_url()
    print(f"[{BOT_NAME}] 🌐 connecting WS: {uri}")
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
                    title = m.get("title") or ""
                    body  = m.get("message") or ""
                    mid   = m.get("id")
                    # skip our own reposts
                    if str(title).startswith(f"{BOT_ICON} {BOT_NAME}:"):
                        continue
                    low_all = f"{title} {body}".lower()
                    if low_all.startswith("jarvis "):
                        await _handle_command(low_all)
                        continue
                    # heuristic source hint
                    hint = "sonarr" if "sonarr" in low_all else ("radarr" if "radarr" in low_all else None)
                    process_and_send(title, body, priority=int(m.get("priority") or 5), extras=m.get("extras"), source_hint=hint, msg_id=mid)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ ws error: {e}")
            await asyncio.sleep(5)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# ---------- Startup ----------
def _start_smtp():
    try:
        import smtp_server
        modules["smtp_server"] = smtp_server
        smtp_server.start_smtp(os.environ, lambda t, b, **kw: process_and_send(t, b, **kw))
        print(f"[{BOT_NAME}] ✅ SMTP intake started")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ SMTP start error: {e}")

def _start_proxy():
    try:
        import proxy
        modules["proxy"] = proxy
        proxy.start_proxy(os.environ, lambda t, b, **kw: process_and_send(t, b, **kw))
        print(f"[{BOT_NAME}] ✅ Proxy started")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Proxy start error: {e}")

# ---------- Main ----------
if __name__ == "__main__":
    _mkdirs()
    _load_mood()
    JARVIS_APP_ID = _resolve_app_id()

    # Console banner
    print(f"[{BOT_NAME}] 🧠 Prime Neural Boot")
    print(f"[{BOT_NAME}] {_pipeline_label()}")

    # Startup card
    _gotify_post("Startup", startup_poster(), priority=5)

    # modules
    if SMTP_ENABLED: _start_smtp()
    if PROXY_ENABLED: _start_proxy()

    # Loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(_ws_listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
