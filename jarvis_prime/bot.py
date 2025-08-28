#!/usr/bin/env python3
# Jarvis Prime – Bot Core (Neural Core edition)

from __future__ import annotations
import os, re, json, time, asyncio, schedule, requests, websockets
from pathlib import Path
from typing import Optional, Dict, Any

def _env_bool(k: str, d=False) -> bool:
    v = os.getenv(k, "")
    if v == "" or v is None: return d
    return str(v).lower() in ("1","true","yes","on")

# ------------ Config ------------
BOT_NAME = os.getenv("BOT_NAME","Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON","🧠")
GOTIFY_URL = (os.getenv("GOTIFY_URL","") or "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN","")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN","")
JARVIS_APP_NAME = os.getenv("JARVIS_APP_NAME","Jarvis")

RETENTION_HOURS  = int(os.getenv("RETENTION_HOURS","24"))
BEAUTIFY_ENABLED = _env_bool("BEAUTIFY_ENABLED", True)
SILENT_REPOST    = _env_bool("SILENT_REPOST", True)

RADARR_ENABLED     = _env_bool("RADARR_ENABLED", False)
SONARR_ENABLED     = _env_bool("SONARR_ENABLED", False)
WEATHER_ENABLED    = _env_bool("WEATHER_ENABLED", False)
UPTIMEKUMA_ENABLED = _env_bool("uptimekuma_enabled", False)
SMTP_ENABLED       = _env_bool("smtp_enabled", False)
PROXY_ENABLED      = _env_bool("proxy_enabled", False)
TECHNITIUM_ENABLED = _env_bool("technitium_enabled", False)

PERSONALITY_PERSISTENT = _env_bool("PERSONALITY_PERSISTENT", True)
CHAT_MOOD = (os.getenv("personality_mood","serious").strip().lower() or "serious")

LLM_ENABLED        = _env_bool("LLM_ENABLED", False)
LLM_MEMORY_ENABLED = _env_bool("LLM_MEMORY_ENABLED", True)
LLM_TIMEOUT_SEC    = int(os.getenv("LLM_TIMEOUT_SECONDS","5"))
LLM_MAX_CPU_PERCENT= int(os.getenv("LLM_MAX_CPU_PERCENT","70"))
LLM_MODEL_URL      = os.getenv("LLM_MODEL_URL","")
LLM_MODEL_PATH     = os.getenv("LLM_MODEL_PATH","/share/jarvis_prime/models/tinyllama-1.1b-chat.Q4_K_M.gguf")
LLM_MODEL_SHA256   = (os.getenv("LLM_MODEL_SHA256","") or "")

BASE_DIR   = Path("/share/jarvis_prime")
MEM_DIR    = BASE_DIR / "memory"
STATE_PATH = BASE_DIR / "state.json"
MEM_EVENTS = MEM_DIR / "events.json"

# ------------ Imports ------------
try:
    from beautify import beautify_message
    _BEAUTIFY_OK = True
except Exception as e:
    _BEAUTIFY_OK = False
    def beautify_message(title, body, **kw): return (f"{title}\n\n{body}".strip(), None)

try:
    import llm_client
    _LLM_CLIENT_OK = True
except Exception:
    _LLM_CLIENT_OK = False
    llm_client = None

try:
    import llm_memory
    _LLM_MEMORY_OK = True
except Exception:
    _LLM_MEMORY_OK = False
    llm_memory = None

try:
    import personality_state
    _PSTATE_OK = True
except Exception:
    _PSTATE_OK = False
    personality_state = None

# ------------ Helpers ------------
def _mkdirs():
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    Path(LLM_MODEL_PATH).parent.mkdir(parents=True, exist_ok=True)

def _ws_url() -> str:
    if GOTIFY_URL.startswith("https://"):
        return "wss://" + GOTIFY_URL[len("https://"):] + "/stream?token=" + CLIENT_TOKEN
    return "ws://" + GOTIFY_URL[len("http://"):] + "/stream?token=" + CLIENT_TOKEN

def _pipeline_line() -> str:
    if LLM_ENABLED:
        return f"UI: LLM ➜ polish  ·  Model: {'present' if Path(LLM_MODEL_PATH).exists() else 'missing'}"
    return "UI: Beautifier full pipeline"

def _memory_on() -> bool:
    return LLM_MEMORY_ENABLED and _LLM_MEMORY_OK

def _quip(mood: str) -> str:
    m = (mood or "").lower()
    if m == "angry": return "— Done. No BS."
    if m == "playful": return "— Sparkly clean."
    if m == "sarcastic": return "— Revolutionary. Truly."
    if m == "hacker-noir": return "— Packet traced. Signal clean."
    return "— All set."

def _footer(used_llm: bool) -> str:
    return "[Neural Core ✓]" if used_llm else "[Beautifier]"

def _gotify_post(title: str, message: str, *, priority=5, extras: dict|None=None) -> bool:
    try:
        payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": int(priority)}
        if extras: payload["extras"] = extras
        r = requests.post(f"{GOTIFY_URL}/message?token={APP_TOKEN}", json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] send error: {e}")
        return False

def _purge_original(msg_id: int|None):
    if not (SILENT_REPOST and msg_id): return
    try:
        requests.delete(f"{GOTIFY_URL}/message/{msg_id}", headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=8)
    except Exception: pass

def _neural_state_section() -> str:
    present = Path(LLM_MODEL_PATH).exists()
    return "\n".join([
        "### Neural Core",
        f"- State – **{'ACTIVE' if LLM_ENABLED else 'OFF'}{' (model missing)' if (LLM_ENABLED and not present) else ''}**",
        f"- Model: `{Path(LLM_MODEL_PATH).name}`",
        f"- Memory: **{'ACTIVE' if _memory_on() else 'OFF'}**",
    ])

def startup_poster() -> str:
    subs = [
        ("Radarr", RADARR_ENABLED),
        ("Sonarr", SONARR_ENABLED),
        ("Weather", WEATHER_ENABLED),
        ("Uptime Kuma", UPTIMEKUMA_ENABLED),
        ("SMTP Intake", SMTP_ENABLED),
        ("DNS (Technitium)", TECHNITIUM_ENABLED),
    ]
    bullets = "\n".join([f"- {'🟢' if e else '⚫'} {n}" for n,e in subs])
    return "\n".join([
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
    ])

def _save_mood(mood: str):
    if PERSONALITY_PERSISTENT and _PSTATE_OK:
        try: personality_state.save_mood(STATE_PATH, mood)
        except Exception: pass

def _load_mood():
    global CHAT_MOOD
    if PERSONALITY_PERSISTENT and _PSTATE_OK:
        try:
            m = personality_state.load_mood(STATE_PATH)
            if m: CHAT_MOOD = m
        except Exception: pass

def _maybe_prefetch_model():
    try:
        if LLM_ENABLED and _LLM_CLIENT_OK and not Path(LLM_MODEL_PATH).exists() and LLM_MODEL_URL:
            print(f"[{BOT_NAME}] Prefetch (bot)…")
            llm_client.prefetch_model()
    except Exception as e:
        print(f"[{BOT_NAME}] prefetch error: {e}")

def _llm_rewrite(text: str, mood: str) -> tuple[str,bool]:
    if not (LLM_ENABLED and _LLM_CLIENT_OK): return text, False
    if not Path(LLM_MODEL_PATH).exists():    return text, False
    try:
        out = llm_client.rewrite_text(prompt=text, mood=mood, timeout_s=LLM_TIMEOUT_SEC)
        if isinstance(out, str) and out.strip():
            return out.strip(), True
    except Exception as e:
        print(f"[{BOT_NAME}] LLM rewrite failed: {e}")
    return text, False

def _mem_store(title: str, text: str):
    if _memory_on():
        try:
            llm_memory.store_event(MEM_EVENTS, title=title, text=text)
            llm_memory.flush_older_than(MEM_EVENTS, hours=RETENTION_HOURS)
        except Exception: pass

def _mem_answer_today() -> str:
    if not _memory_on(): return "Memory disabled."
    try: return llm_memory.summarize_today(MEM_EVENTS)
    except Exception: return "No events today."

def _mem_answer_failures() -> str:
    if not _memory_on(): return "Memory disabled."
    try: return llm_memory.failures_today(MEM_EVENTS)
    except Exception: return "No failures detected today."

def process_and_send(title: str, body: str, *, priority=5, extras: dict|None=None, source_hint: str|None=None, msg_id: int|None=None):
    _mem_store(title, body)  # raw log

    rewritten, used_llm = _llm_rewrite(body, CHAT_MOOD)
    text, bx = beautify_message(title, rewritten, mood=CHAT_MOOD, source_hint=source_hint)

    text = f"{text}\n\n{_footer(used_llm)}\n{_quip(CHAT_MOOD)}"

    merged = None
    if bx and extras:
        merged = dict(extras)
        cn = dict(merged.get("client::notification", {}))
        cb = dict(bx.get("client::notification", {}))
        if "bigImageUrl" not in cn and cb.get("bigImageUrl"):
            cn["bigImageUrl"] = cb["bigImageUrl"]
        if cn: merged["client::notification"] = cn
    else:
        merged = (bx or extras)

    if _gotify_post(title, text, priority=int(priority), extras=merged):
        _purge_original(msg_id)

async def _handle_command(s: str):
    global CHAT_MOOD
    s = s.strip().lower()
    if s.startswith("jarvis mood "):
        CHAT_MOOD = s.split("jarvis mood ",1)[1].strip()
        _save_mood(CHAT_MOOD)
        _gotify_post("Mood", f"Personality switched to **{CHAT_MOOD}**.\n\n[System]")
        return
    if "what happened today" in s:
        _gotify_post("Today", _mem_answer_today() + "\n\n[Memory]")
        return
    if "what broke today" in s:
        _gotify_post("Incidents", _mem_answer_failures() + "\n\n[Memory]")
        return

async def ws_listener():
    uri = ("wss://" + GOTIFY_URL[len("https://"):] if GOTIFY_URL.startswith("https://")
           else "ws://" + GOTIFY_URL[len("http://"):]) + "/stream?token=" + CLIENT_TOKEN
    print(f"[{BOT_NAME}] WS -> {uri}")
    while True:
        try:
            async with websockets.connect(uri, ping_interval=30, ping_timeout=20) as ws:
                async for raw in ws:
                    try: evt = json.loads(raw)
                    except Exception: continue
                    if evt.get("event") != "message": continue
                    m = evt.get("message", {})
                    mid = m.get("id")
                    title = m.get("title") or ""
                    body  = m.get("message") or ""
                    prio  = int(m.get("priority") or 5)
                    extras= m.get("extras")

                    if str(title).startswith(f"{BOT_ICON} {BOT_NAME}:"):  # skip our reposts
                        continue

                    # commands
                    joined = f"{title} {body}".strip().lower()
                    if joined.startswith("jarvis "):
                        await _handle_command(joined)
                        continue

                    hint = None
                    low = joined
                    if "sonarr" in low: hint = "sonarr"
                    elif "radarr" in low: hint = "radarr"

                    process_and_send(title, body, priority=prio, extras=extras, source_hint=hint, msg_id=mid)
        except Exception as e:
            print(f"[{BOT_NAME}] WS error: {e}")
            await asyncio.sleep(5)

def start_smtp():
    if not SMTP_ENABLED: return
    try:
        import smtp_server
        smtp_server.start_smtp(os.environ, lambda t,b,**kw: process_and_send(t,b,**kw))
        print(f"[{BOT_NAME}] SMTP intake started")
    except Exception as e:
        print(f"[{BOT_NAME}] SMTP start error: {e}")

def start_proxy():
    if not PROXY_ENABLED: return
    try:
        import proxy
        proxy.start_proxy(os.environ, lambda t,b,**kw: process_and_send(t,b,**kw))
        print(f"[{BOT_NAME}] Proxy started")
    except Exception as e:
        print(f"[{BOT_NAME}] Proxy start error: {e}")

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    _mkdirs()
    _load_mood()
    _maybe_prefetch_model()

    print(f"[{BOT_NAME}] Prime Neural Boot")
    print(f"[{BOT_NAME}] {_pipeline_line()}")

    _gotify_post("Startup", startup_poster())
    start_smtp()
    start_proxy()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(ws_listener())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
