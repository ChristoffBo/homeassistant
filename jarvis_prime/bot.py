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
import textwrap
from datetime import datetime, timezone
from typing import Optional, Tuple, List

# ---------------------------------
# Basic env
# ---------------------------------
BOT_NAME  = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON  = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL   = os.getenv("GOTIFY_URL", "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
APP_NAME     = os.getenv("JARVIS_APP_NAME", "Jarvis")

SILENT_REPOST    = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# Feature toggles (env defaults; overridable by /data/options.json)
RADARR_ENABLED     = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED     = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED    = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV   = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED       = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")
SMTP_ENABLED       = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")
PROXY_ENABLED_ENV  = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")

# Persona compatibility token for downstream modules
CHAT_MOOD = "neutral"

# ---------------------------------
# Load /data/options.json overrides
# ---------------------------------
def _load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

merged = {}
try:
    options = _load_json("/data/options.json")
    fallback = _load_json("/data/config.json")
    merged = {**fallback, **options}

    RADARR_ENABLED  = bool(merged.get("radarr_enabled", RADARR_ENABLED))
    SONARR_ENABLED  = bool(merged.get("sonarr_enabled", SONARR_ENABLED))
    WEATHER_ENABLED = bool(merged.get("weather_enabled", WEATHER_ENABLED))
    TECHNITIUM_ENABLED = bool(merged.get("technitium_enabled", TECHNITIUM_ENABLED))
    KUMA_ENABLED    = bool(merged.get("uptimekuma_enabled", KUMA_ENABLED))
    SMTP_ENABLED    = bool(merged.get("smtp_enabled", SMTP_ENABLED))
    PROXY_ENABLED   = bool(merged.get("proxy_enabled", PROXY_ENABLED_ENV))

    CHAT_ENABLED_FILE   = bool(merged.get("chat_enabled",   CHAT_ENABLED_ENV))
    DIGEST_ENABLED_FILE = bool(merged.get("digest_enabled", DIGEST_ENABLED_ENV))

    CHAT_MOOD = str(merged.get("personality_mood", merged.get("chat_mood", CHAT_MOOD)))
except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ options load failed: {e}")
    PROXY_ENABLED = PROXY_ENABLED_ENV
    CHAT_ENABLED_FILE = CHAT_ENABLED_ENV
    DIGEST_ENABLED_FILE = DIGEST_ENABLED_ENV

# ---------------------------------
# LLM settings
# ---------------------------------
def _bool_env(name, default=False):
    v = os.getenv(name)
    if v is None: return default
    return v.strip().lower() in ("1","true","yes","on")

LLM_ENABLED           = bool(merged.get("llm_enabled", _bool_env("LLM_ENABLED", False)))
LLM_TIMEOUT_SECONDS   = int(merged.get("llm_timeout_seconds", int(os.getenv("LLM_TIMEOUT_SECONDS", "12"))))
LLM_MAX_CPU_PERCENT   = int(merged.get("llm_max_cpu_percent", int(os.getenv("LLM_MAX_CPU_PERCENT", "70"))))
LLM_MODELS_PRIORITY   = merged.get("llm_models_priority", [])
OLLAMA_BASE_URL       = merged.get("ollama_base_url",  os.getenv("OLLAMA_BASE_URL", ""))
LLM_MODEL_URL         = merged.get("llm_model_url",    os.getenv("LLM_MODEL_URL", ""))
LLM_MODEL_PATH        = merged.get("llm_model_path",   os.getenv("LLM_MODEL_PATH", ""))
LLM_MODEL_SHA256      = merged.get("llm_model_sha256", os.getenv("LLM_MODEL_SHA256", ""))
PERSONALITY_ALLOW_PROFANITY = bool(merged.get("personality_allow_profanity", _bool_env("PERSONALITY_ALLOW_PROFANITY", False)))

# ---------------------------------
# Optional modules
# ---------------------------------
def _load_module(name, path):
    try:
        import importlib.util as _imp
        spec = _imp.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = _imp.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ load {name} failed: {e}")
    return None

_aliases = _load_module("aliases", "/app/aliases.py")
_personality = _load_module("personality", "/app/personality.py")
_pstate = _load_module("personality_state", "/app/personality_state.py")
_beautify = _load_module("beautify", "/app/beautify.py")
_llm = _load_module("llm_client", "/app/llm_client.py")

ACTIVE_PERSONA, PERSONA_TOD = "neutral", ""
if _pstate and hasattr(_pstate, "get_active_persona"):
    try:
        ACTIVE_PERSONA, PERSONA_TOD = _pstate.get_active_persona()
        CHAT_MOOD = ACTIVE_PERSONA
    except Exception:
        pass

# ---------------------------------
# Sidecars
# ---------------------------------
_sidecars: List[subprocess.Popen] = []

def _start_sidecar(cmd, label):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        _sidecars.append(p)
        print(f"[{BOT_NAME}] ▶️ {label} started (pid={p.pid})")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ {label} failed: {e}")

def start_sidecars():
    if bool(os.getenv("proxy_enabled", str(PROXY_ENABLED)).lower() in ("1","true","yes")) or PROXY_ENABLED:
        _start_sidecar(["python3","/app/proxy.py"], "proxy.py")
    if bool(SMTP_ENABLED):
        _start_sidecar(["python3","/app/smtp_server.py"], "smtp_server.py")

def stop_sidecars():
    for p in _sidecars:
        try: p.terminate()
        except Exception: pass
atexit.register(stop_sidecars)

# ---------------------------------
# Gotify helpers
# ---------------------------------
def _bubble_block(text: str, persona: str, position: str = "below", width: int = 64) -> str:
    """Render a small 'speech bubble' block with subtle box-drawing."""
    wrap = textwrap.fill(text.strip(), width=width)
    lines = wrap.splitlines() or [""]
    head = f"┌─ 🗣️ {persona} says ─"
    top = head + ("─" * max(0, width - len(head)))
    body = "\n".join([f"│ {ln}" for ln in lines])
    bot = "└" + "─" * width
    block = f"{top}\n{body}\n{bot}"
    if position == "above":
        return f"{block}\n\n"
    return f"\n\n{block}"

_BUBBLE_FLIP = False  # alternates above/below

def send_message(title, message, priority=5, extras=None, decorate=True):
    global _BUBBLE_FLIP
    orig_title = title

    # persona-aware decoration (keep original title to avoid big banner look)
    if decorate and _personality and hasattr(_personality, "decorate_by_persona"):
        title, message = _personality.decorate_by_persona(title, message, ACTIVE_PERSONA, PERSONA_TOD, chance=1.0)
        title = orig_title
    elif decorate and _personality and hasattr(_personality, "decorate"):
        title, message = _personality.decorate(title, message, CHAT_MOOD, chance=1.0)
        title = orig_title

    # turn persona voice into a neat bubble block in body
    bubble_pos = "above" if _BUBBLE_FLIP else "below"
    _BUBBLE_FLIP = not _BUBBLE_FLIP
    persona_tag = ACTIVE_PERSONA or CHAT_MOOD or "neutral"
    message = f"{message}{_bubble_block(' ' if message is None else '', persona_tag, bubble_pos, width=56)}" if message else _bubble_block("", persona_tag, bubble_pos, width=56)

    if _personality and hasattr(_personality, "apply_priority"):
        try: priority = _personality.apply_priority(priority, CHAT_MOOD)
        except Exception: pass

    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message or "", "priority": priority}
    if extras: payload["extras"] = extras
    try:
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ send_message failed: {e}")
        return False

def delete_original_message(msg_id: int):
    try:
        if not msg_id: return
        url = f"{GOTIFY_URL}/message/{msg_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        requests.delete(url, headers=headers, timeout=6)
    except Exception:
        pass

def resolve_app_id():
    global jarvis_app_id
    jarvis_app_id = None
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=8); r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id"); break
        print(f"[{BOT_NAME}] 🆔 app id = {jarvis_app_id}")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ app id resolve failed: {e}")

def _is_our_post(data: dict) -> bool:
    try:
        if data.get("appid") == jarvis_app_id: return True
        t = data.get("title") or ""
        return t.startswith(f"{BOT_ICON} {BOT_NAME}:")
    except Exception:
        return False

def _should_purge() -> bool:
    try: return bool(merged.get("silent_repost", SILENT_REPOST))
    except Exception: return SILENT_REPOST

def _purge_after(msg_id: int):
    if _should_purge(): delete_original_message(msg_id)

# ---------------------------------
# LLM + Beautify pipeline
# ---------------------------------
def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _llm_then_beautify(title: str, message: str) -> Tuple[str, Optional[dict], bool, bool]:
    used_llm = False; used_beautify = False; final = message or ""; extras = None
    if LLM_ENABLED and _llm and hasattr(_llm, "rewrite"):
        try:
            rewritten = _llm.rewrite(
                text=final, mood=CHAT_MOOD, timeout=LLM_TIMEOUT_SECONDS, cpu_limit=LLM_MAX_CPU_PERCENT,
                models_priority=LLM_MODELS_PRIORITY, base_url=OLLAMA_BASE_URL,
                model_url=LLM_MODEL_URL, model_path=LLM_MODEL_PATH, model_sha256=LLM_MODEL_SHA256,
                allow_profanity=PERSONALITY_ALLOW_PROFANITY,
            )
            if rewritten:
                final = rewritten; used_llm = True
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ LLM skipped: {e}")

    if BEAUTIFY_ENABLED and _beautify and hasattr(_beautify, "beautify_message"):
        try:
            final, extras = _beautify.beautify_message(title, final, mood=CHAT_MOOD)
            used_beautify = True
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ beautify error: {e}")

    foot = _footer(used_llm, used_beautify)
    if final and not final.rstrip().endswith(foot):
        final = f"{final.rstrip()}\n\n{foot}"
    return final, extras, used_llm, used_beautify

# ---------------------------------
# Command parsing
# ---------------------------------
def _clean(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_cmd(cmd: str) -> str:
    try:
        if _aliases and hasattr(_aliases, "normalize_cmd"):
            return _aliases.normalize_cmd(cmd)
    except Exception:
        pass
    return _clean(cmd)

def extract_command_from(title: str, message: str) -> str:
    tlow, mlow = (title or "").lower(), (message or "").lower()
    if tlow.startswith("jarvis"):
        rest = tlow.replace("jarvis", "", 1).strip()
        return rest or (mlow.replace("jarvis","",1).strip() if mlow.startswith("jarvis") else mlow.strip())
    if mlow.startswith("jarvis"): return mlow.replace("jarvis","",1).strip()
    return ""

# ---------------------------------
# Startup HUD
# ---------------------------------
def post_startup_card():
    st = {}
    if LLM_ENABLED and _llm and hasattr(_llm, "engine_status"):
        try: st = _llm.engine_status() or {}
        except Exception: st = {}

    engine_online = bool(st.get("ready")) if LLM_ENABLED else False
    backend = (st.get("backend") or "").strip()
    model_path = (st.get("model_path") or LLM_MODEL_PATH or "").strip()
    model_token = os.path.basename(model_path) if model_path else backend
    llm_line = f"🧠 LLM: {('Disabled' if not engine_online else (model_token or 'Formatter'))}"

    lines = [
        "🧬 Prime Neural Boot",
        f"🛰️ Engine: {'Neural Core — ONLINE' if engine_online else 'Neural Core — OFFLINE'}",
        llm_line,
        f"🗣️ Persona speaking: {ACTIVE_PERSONA} ({PERSONA_TOD})",
        "",
        "Modules:",
        f"🎬 Radarr — {'ACTIVE' if RADARR_ENABLED else 'OFF'}",
        f"📺 Sonarr — {'ACTIVE' if SONARR_ENABLED else 'OFF'}",
        f"🌤️ Weather — {'ACTIVE' if WEATHER_ENABLED else 'OFF'}",
        f"🧾 Digest — {'ACTIVE' if DIGEST_ENABLED_FILE else 'OFF'}",
        f"💬 Chat — {'ACTIVE' if CHAT_ENABLED_FILE else 'OFF'}",
        f"📈 Uptime Kuma — {'ACTIVE' if KUMA_ENABLED else 'OFF'}",
        f"✉️ SMTP Intake — {'ACTIVE' if SMTP_ENABLED else 'OFF'}",
        f"🔀 Proxy (Gotify/ntfy) — {'ACTIVE' if PROXY_ENABLED else 'OFF'}",
        f"🧠 DNS (Technitium) — {'ACTIVE' if TECHNITIUM_ENABLED else 'OFF'}",
        "",
        "Status: All systems nominal",
    ]
    send_message("Startup", "\n".join(lines), priority=4, decorate=False)

# ---------------------------------
# Command handling
# ---------------------------------
def _try_call(module, fn_name, *args, **kwargs):
    try:
        if module and hasattr(module, fn_name):
            return getattr(module, fn_name)(*args, **kwargs)
    except Exception as e:
        return f"⚠️ {fn_name} failed: {e}", None
    return None, None

def _handle_command(ncmd: str) -> bool:
    # lazy imports
    m_arr = m_weather = m_kuma = m_tech = m_digest = m_chat = None
    try: m_arr = __import__("arr")
    except Exception: pass
    try: m_weather = __import__("weather")
    except Exception: pass
    try: m_kuma = __import__("uptimekuma")
    except Exception: pass
    try: m_tech = __import__("technitium")
    except Exception: pass
    try: m_digest = __import__("digest")
    except Exception: pass
    try: m_chat = __import__("chat")
    except Exception: pass

    if ncmd in ("help", "commands"):
        help_text = (
            "🤖 Jarvis Prime — Commands\n"
            f"Persona: {ACTIVE_PERSONA} ({PERSONA_TOD})\n\n"
            "Core: dns | kuma | weather | forecast | digest | joke\n"
            "ARR: upcoming movies | upcoming series | movie count | series count | longest movie | longest series"
        )
        send_message("Help", help_text)
        return True

    if ncmd in ("digest", "daily digest", "summary"):
        if m_digest and hasattr(m_digest, "build_digest"):
            title2, msg2, pr = m_digest.build_digest(merged)
            if _personality and hasattr(_personality, "quip"):
                try: msg2 += f"\n\n{_personality.quip(ACTIVE_PERSONA)}"
                except Exception: pass
            send_message("Digest", msg2, priority=pr)
        else:
            send_message("Digest", "Digest module unavailable.")
        return True

    if ncmd in ("dns",):
        text, _ = _try_call(m_tech, "handle_dns_command", "dns")
        send_message("DNS Status", text or "No data.")
        return True

    if ncmd in ("kuma", "uptime", "monitor"):
        text, _ = _try_call(m_kuma, "handle_kuma_command", "kuma")
        send_message("Uptime Kuma", text or "No data.")
        return True

    if ncmd in ("weather", "now", "today", "temp", "temps"):
        text = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text = m_weather.handle_weather_command("weather")
                if isinstance(text, tuple): text = text[0]
            except Exception as e:
                text = f"⚠️ Weather failed: {e}"
        send_message("Weather", text or "No data.")
        return True

    if ncmd in ("forecast", "weekly", "7day", "7-day", "7 day"):
        text = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text = m_weather.handle_weather_command("forecast")
                if isinstance(text, tuple): text = text[0]
            except Exception as e:
                text = f"⚠️ Forecast failed: {e}"
        send_message("Forecast", text or "No data.")
        return True

    if ncmd in ("joke", "pun", "tell me a joke", "make me laugh"):
        if m_chat and hasattr(m_chat, "handle_chat_command"):
            try:
                msg, _ = m_chat.handle_chat_command("joke")
            except Exception as e:
                msg = f"⚠️ Chat error: {e}"
            send_message("Joke", msg or "No joke available right now.")
        else:
            send_message("Joke", "Chat engine unavailable.")
        return True

    # ARR
    if ncmd in ("upcoming movies", "upcoming films", "movies upcoming", "films upcoming"):
        msg, _ = _try_call(m_arr, "upcoming_movies", 7)
        send_message("Upcoming Movies", msg or "No data.")
        return True
    if ncmd in ("upcoming series", "upcoming shows", "series upcoming", "shows upcoming"):
        msg, _ = _try_call(m_arr, "upcoming_series", 7)
        send_message("Upcoming Episodes", msg or "No data.")
        return True
    if ncmd in ("movie count", "film count"):
        msg, _ = _try_call(m_arr, "movie_count")
        send_message("Movie Count", msg or "No data.")
        return True
    if ncmd in ("series count", "show count"):
        msg, _ = _try_call(m_arr, "series_count")
        send_message("Series Count", msg or "No data.")
        return True
    if ncmd in ("longest movie", "longest film"):
        msg, _ = _try_call(m_arr, "longest_movie")
        send_message("Longest Movie", msg or "No data.")
        return True
    if ncmd in ("longest series", "longest show"):
        msg, _ = _try_call(m_arr, "longest_series")
        send_message("Longest Series", msg or "No data.")
        return True

    return False

# ---------------------------------
# WebSocket listener
# ---------------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] WS → {ws_url}")
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        async for raw in ws:
            try:
                data = json.loads(raw); msg_id = data.get("id")
                title = data.get("title") or ""
                message = data.get("message") or ""

                # wake-word first (works even if posted via same app)
                ncmd = normalize_cmd(extract_command_from(title, message))
                if ncmd and _handle_command(ncmd):
                    _purge_after(msg_id)
                    continue

                # skip our own non-command posts
                if _is_our_post(data):
                    continue

                final, extras, used_llm, used_beautify = _llm_then_beautify(title, message)
                send_message(title or "Notification", final, priority=5, extras=extras)
                _purge_after(msg_id)
            except Exception as e:
                print(f"[{BOT_NAME}] ⚠️ stream error: {e}")

# ---------------------------------
# Main
# ---------------------------------
def main():
    resolve_app_id()
    try:
        start_sidecars()
        post_startup_card()
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ startup error: {e}")
    asyncio.run(_run_forever())

async def _run_forever():
    while True:
        try:
            await listen()
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ reconnect in 3s: {e}")
            await asyncio.sleep(3)

if __name__ == "__main__":
    main()
