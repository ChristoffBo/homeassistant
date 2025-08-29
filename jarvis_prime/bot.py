#!/usr/bin/env python3
# /app/bot.py
import os
import json
import time
import asyncio
import requests
import websockets
import schedule
import re
import subprocess
import atexit
from datetime import datetime, timezone
from typing import Optional, Tuple, List

# -----------------------------
# Dynamic modules dict
# -----------------------------
extra_modules = {}

# -----------------------------
# Config from env (set in run.sh)
# -----------------------------
BOT_NAME  = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON  = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL   = os.getenv("GOTIFY_URL", "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
APP_NAME     = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS  = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST    = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# Feature toggles (env defaults; can be overridden by /data/options.json)
RADARR_ENABLED     = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED     = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED    = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV   = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED       = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")
SMTP_ENABLED       = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")
PROXY_ENABLED_ENV  = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")

# Mood
CHAT_MOOD = "serious"

# Uptime tracking
BOOT_TIME = datetime.now(timezone.utc)

# Heartbeat config (can be overridden)
HEARTBEAT_ENABLED = False
HEARTBEAT_INTERVAL_MIN = 120
HEARTBEAT_START = "06:00"
HEARTBEAT_END   = "20:00"

# Beautify inline images for Gotify Web (Android uses extras image natively)
BEAUTIFY_INLINE_IMAGES = False

# -----------------------------
# Load /data/options.json overrides
# -----------------------------
def _load_json_file(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

merged = {}
try:
    options = _load_json_file("/data/options.json")
    config_fallback = _load_json_file("/data/config.json")
    merged = {**config_fallback, **options}

    RADARR_ENABLED  = bool(merged.get("radarr_enabled", RADARR_ENABLED))
    SONARR_ENABLED  = bool(merged.get("sonarr_enabled", SONARR_ENABLED))
    WEATHER_ENABLED = bool(merged.get("weather_enabled", WEATHER_ENABLED))
    TECHNITIUM_ENABLED = bool(merged.get("technitium_enabled", TECHNITIUM_ENABLED))
    KUMA_ENABLED    = bool(merged.get("uptimekuma_enabled", KUMA_ENABLED))
    SMTP_ENABLED    = bool(merged.get("smtp_enabled", SMTP_ENABLED))
    PROXY_ENABLED   = bool(merged.get("proxy_enabled", PROXY_ENABLED_ENV))

    global CHAT_ENABLED_FILE, DIGEST_ENABLED_FILE
    CHAT_ENABLED_FILE   = merged.get("chat_enabled",   CHAT_ENABLED_ENV)
    DIGEST_ENABLED_FILE = merged.get("digest_enabled", DIGEST_ENABLED_ENV)

    CHAT_MOOD = str(merged.get("personality_mood", merged.get("chat_mood", CHAT_MOOD)))

    HEARTBEAT_ENABLED       = bool(merged.get("heartbeat_enabled", HEARTBEAT_ENABLED))
    HEARTBEAT_INTERVAL_MIN  = int(merged.get("heartbeat_interval_minutes", HEARTBEAT_INTERVAL_MIN))
    HEARTBEAT_START         = str(merged.get("heartbeat_start", HEARTBEAT_START))
    HEARTBEAT_END           = str(merged.get("heartbeat_end", HEARTBEAT_END))
    BEAUTIFY_INLINE_IMAGES  = bool(merged.get("beautify_inline_images", False))

except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options/config json: {e}")
    PROXY_ENABLED = PROXY_ENABLED_ENV
    CHAT_ENABLED_FILE = CHAT_ENABLED_ENV
    DIGEST_ENABLED_FILE = DIGEST_ENABLED_ENV

# -----------------------------
# LLM settings (from options.json with env fallbacks)
# -----------------------------
def _bool_env(name, default=False):
    if os.getenv(name) is None: return default
    return os.getenv(name, "").strip().lower() in ("1","true","yes","on")

LLM_ENABLED           = bool(merged.get("llm_enabled", _bool_env("LLM_ENABLED", False)))
LLM_TIMEOUT_SECONDS   = int(merged.get("llm_timeout_seconds", int(os.getenv("LLM_TIMEOUT_SECONDS", "12"))))
LLM_MAX_CPU_PERCENT   = int(merged.get("llm_max_cpu_percent", int(os.getenv("LLM_MAX_CPU_PERCENT", "70"))))
LLM_MODELS_PRIORITY   = merged.get("llm_models_priority", [])
# normalize: accept string "a,b,c" or list
if isinstance(LLM_MODELS_PRIORITY, str):
    import re as _re
    LLM_MODELS_PRIORITY = [x.strip() for x in _re.split(r'[\s,]+', LLM_MODELS_PRIORITY) if x.strip()]
OLLAMA_BASE_URL       = merged.get("ollama_base_url",  os.getenv("OLLAMA_BASE_URL", ""))
LLM_MODEL_URL         = merged.get("llm_model_url",    os.getenv("LLM_MODEL_URL", ""))
LLM_MODEL_PATH        = merged.get("llm_model_path",   os.getenv("LLM_MODEL_PATH", ""))
LLM_MODEL_SHA256      = merged.get("llm_model_sha256", os.getenv("LLM_MODEL_SHA256", ""))
# Export env so llm_client.engine_status can see our selection
try:
    import os as _os
    if isinstance(LLM_MODELS_PRIORITY, (list, tuple)):
        _os.environ["LLM_MODELS_PRIORITY"] = ",".join(LLM_MODELS_PRIORITY)
    elif isinstance(LLM_MODELS_PRIORITY, str) and LLM_MODELS_PRIORITY.strip():
        _os.environ["LLM_MODELS_PRIORITY"] = LLM_MODELS_PRIORITY.strip()
    if LLM_MODEL_PATH:
        _os.environ["LLM_MODEL_PATH"] = str(LLM_MODEL_PATH)
    if LLM_MODEL_URL:
        _os.environ["LLM_MODEL_URL"] = str(LLM_MODEL_URL)
except Exception:
    pass

# Prefetch LLM model at startup if enabled
if LLM_ENABLED and _llm and hasattr(_llm, "prefetch"):
    try:
        info = _llm.prefetch(LLM_MODELS_PRIORITY, LLM_MODEL_URL, LLM_MODEL_PATH)
        if info.get("path"):
            print(f"[{BOT_NAME}] 🚚 Model candidate: {info.get('key')} -> {info.get('path')} (downloaded={info.get('downloaded')})")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Prefetch failed: {e}")

PERSONALITY_ALLOW_PROFANITY = bool(merged.get("personality_allow_profanity", _bool_env("PERSONALITY_ALLOW_PROFANITY", False)))

print(f"[{BOT_NAME}] LLM_ENABLED={LLM_ENABLED} rewrite={'yes' if LLM_ENABLED else 'no'} "
      f"beautify={'yes' if BEAUTIFY_ENABLED else 'no'} mood={CHAT_MOOD}")

jarvis_app_id = None  # resolved at runtime

# -----------------------------
# Optional aliases + personality + helpers
# -----------------------------
_alias_mod = None
def _try_load_aliases():
    global _alias_mod
    try:
        import importlib.util as _imp
        for fname in ("aliases.py", "alias.py"):
            path = f"/app/{fname}"
            if not os.path.exists(path):
                continue
            spec = _imp.spec_from_file_location("aliases_module", path)
            if spec and spec.loader:
                _alias_mod = _imp.module_from_spec(spec)
                spec.loader.exec_module(_alias_mod)
                print(f"[{BOT_NAME}] ✅ {fname} loaded")
                return
        print(f"[{BOT_NAME}] ⚠️ aliases file not found")
    except Exception as _e:
        print(f"[{BOT_NAME}] ⚠️ aliases module not loaded: {_e}")

_try_load_aliases()

_personality = None
try:
    import importlib.util as _imp
    _pspec = _imp.spec_from_file_location("personality", "/app/personality.py")
    if _pspec and _pspec.loader:
        _personality = _imp.module_from_spec(_pspec)
        _pspec.loader.exec_module(_personality)
        print(f"[{BOT_NAME}] ✅ personality.py loaded")
except Exception as _e:
    print(f"[{BOT_NAME}] ⚠️ personality.py not loaded: {_e}")

_beautify = None
try:
    import importlib.util as _imp
    _bspec = _imp.spec_from_file_location("beautify", "/app/beautify.py")
    if _bspec and _bspec.loader:
        _beautify = _bspec.loader.load_module() if hasattr(_bspec.loader, "load_module") else None
        if _beautify is None:
            _beautify = _imp.module_from_spec(_bspec)
            _bspec.loader.exec_module(_beautify)
        print(f"[{BOT_NAME}] ✅ beautify.py loaded")
except Exception as _e:
    print(f"[{BOT_NAME}] ⚠️ beautify.py not loaded: {_e}")

_llm = None
try:
    import importlib.util as _imp
    _lspec = _imp.spec_from_file_location("llm_client", "/app/llm_client.py")
    if _lspec and _lspec.loader:
        _llm = _imp.module_from_spec(_lspec)
        _lspec.loader.exec_module(_llm)
        print(f"[{BOT_NAME}] ✅ llm_client loaded")
except Exception as _e:
    print(f"[{BOT_NAME}] ⚠️ llm_client not loaded: {_e}")

# -----------------------------
# Sidecar processes (proxy/smtp)
# -----------------------------
_sidecars: List[subprocess.Popen] = []

def start_sidecars():
    # proxy
    if PROXY_ENABLED:
        try:
            p = subprocess.Popen(["python3", "/app/proxy.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            _sidecars.append(p)
            print(f"[{BOT_NAME}] 🔀 proxy.py started (pid={p.pid})")
        except Exception as e:
            print(f"[{BOT_NAME}] ❌ failed to start proxy.py: {e}")
    # smtp
    if SMTP_ENABLED:
        try:
            p = subprocess.Popen(["python3", "/app/smtp_server.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            _sidecars.append(p)
            print(f"[{BOT_NAME}] ✉️ smtp_server.py started (pid={p.pid})")
        except Exception as e:
            print(f"[{BOT_NAME}] ❌ failed to start smtp_server.py: {e}")

def stop_sidecars():
    for p in _sidecars:
        try:
            p.terminate()
        except Exception:
            pass

atexit.register(stop_sidecars)

# -----------------------------
# Utils
# -----------------------------
def send_message(title, message, priority=5, extras=None):
    # Always decorate + bias priority
    if _personality and hasattr(_personality, "decorate"):
        title, message = _personality.decorate(title, message, CHAT_MOOD, chance=1.0)
    if _personality and hasattr(_personality, "apply_priority"):
        priority = _personality.apply_priority(priority, CHAT_MOOD)
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    if extras:
        payload["extras"] = extras
    try:
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to send message: {e}")
        return False

def delete_original_message(msg_id: int):
    try:
        if not msg_id:
            print(f"[{BOT_NAME}] ⚠️ No msg_id to purge")
            return
        url = f"{GOTIFY_URL}/message/{msg_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.delete(url, headers=headers, timeout=8)
        if r.status_code in (200, 204):
            print(f"[{BOT_NAME}] 🧹 Purged original message id={msg_id}")
        else:
            print(f"[{BOT_NAME}] ⚠️ Purge failed id={msg_id}: {r.status_code} {r.text[:120]}")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Purge error: {e}")

def resolve_app_id():
    global jarvis_app_id
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=8)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] 🆔 Resolved app id = {jarvis_app_id}")
                return
        print(f"[{BOT_NAME}] ⚠️ App '{APP_NAME}' not found when resolving app id")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

def _is_our_post(data: dict) -> bool:
    try:
        if data.get("appid") == jarvis_app_id:
            return True
        t = data.get("title", "") or ""
        return t.startswith(f"{BOT_ICON} {BOT_NAME}:")
    except Exception:
        return False

def _should_purge() -> bool:
    try:
        return bool(merged.get("silent_repost", SILENT_REPOST))
    except Exception:
        return SILENT_REPOST

def _purge_after(msg_id: int):
    if _should_purge():
        delete_original_message(msg_id)

# -----------------------------
# Footer + main pipeline
# -----------------------------
def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _llm_then_beautify(title: str, message: str) -> Tuple[str, Optional[dict], bool, bool]:
    """
    Always attempt LLM first when enabled. If it fails or times out, continue to Beautify.
    Returns (final_text, extras, used_llm, used_beautify)
    """
    used_llm = False
    used_beautify = False
    final = message
    extras = None

    # LLM FIRST — no wake-word skip
    if LLM_ENABLED and _llm and hasattr(_llm, "rewrite"):
        try:
            print(f"[{BOT_NAME}] → LLM.rewrite start (timeout={LLM_TIMEOUT_SECONDS}s, mood={CHAT_MOOD})")
            rewritten = _llm.rewrite(
                text=final,
                mood=CHAT_MOOD,
                timeout=LLM_TIMEOUT_SECONDS,
                cpu_limit=LLM_MAX_CPU_PERCENT,
                models_priority=LLM_MODELS_PRIORITY,
                base_url=OLLAMA_BASE_URL,
                model_url=LLM_MODEL_URL,
                model_path=LLM_MODEL_PATH,
                model_sha256=LLM_MODEL_SHA256,
                allow_profanity=PERSONALITY_ALLOW_PROFANITY,
            )
            if rewritten:
                final = rewritten
                used_llm = True
                print(f"[{BOT_NAME}] ✓ LLM.rewrite done")
        except Exception as _e:
            print(f"[{BOT_NAME}] ⚠️ LLM skipped: {_e}")

    # BEAUTIFY SECOND
    if BEAUTIFY_ENABLED and _beautify and hasattr(_beautify, "beautify_message"):
        try:
            final, extras = _beautify.beautify_message(title, final, mood=CHAT_MOOD)
            used_beautify = True
        except Exception as _e:
            print(f"[{BOT_NAME}] ⚠️ Beautify failed: {_e}")

    # Ensure footer visible
    foot = _footer(used_llm, used_beautify)
    if final and not final.rstrip().endswith(foot):
        final = f"{final.rstrip()}\n\n{foot}"

    return final, extras, used_llm, used_beautify

# -----------------------------
# Normalization + command extraction
# -----------------------------
def _clean(s):
    return re.sub(r"\s+", " ", s.lower().strip())

def normalize_cmd(cmd: str) -> str:
    if _alias_mod and hasattr(_alias_mod, "normalize_cmd"):
        try:
            return _alias_mod.normalize_cmd(cmd)
        except Exception:
            pass
    return _clean(cmd)

def extract_command_from(title: str, message: str) -> str:
    tlow, mlow = (title or "").lower(), (message or "").lower()
    if tlow.startswith("jarvis"):
        tcmd = tlow.replace("jarvis", "", 1).strip()
        if tcmd: return tcmd
        if mlow.startswith("jarvis"):
            return mlow.replace("jarvis", "", 1).strip()
        return mlow.strip()
    if mlow.startswith("jarvis"):
        return mlow.replace("jarvis", "", 1).strip()
    return ""

# -----------------------------
# Startup HUD (high-tech boot card)
# -----------------------------

def post_startup_card():
    # Warm-load the model in THIS process before status.
    try:
        if LLM_ENABLED and _llm and hasattr(_llm, "prefetch_model"):
            _llm.prefetch_model()
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Prefetch in bot failed: {e}")

    # LLM engine status/model
    st = {}
    if _llm and hasattr(_llm, "engine_status"):
        try:
            st = _llm.engine_status() or {}
        except Exception:
            st = {}

    online = bool(st.get("ready"))
    model_path = (st.get("model_path") or LLM_MODEL_PATH or "").strip()
    model_name = os.path.basename(model_path) if model_path else ""

    # Show clean engine status; report LLM family on its own line
    engine_line = f"Neural Core — {'ONLINE' if online else 'OFFLINE'}"

    def _family_from_name(n: str) -> str:
        n = (n or "").lower()
        if 'phi' in n:
            return 'Phi3'
        if 'tiny' in n or 'tinyl' in n:
            return 'TinyLlama'
        if 'qwen' in n:
            return 'Qwen'
        return '—'

    llm_line = f"🧠 LLM: {_family_from_name(model_name) if online else '—'}"

    lines = [
        "🧬 Prime Neural Boot",
        f"🛰️ Engine: {engine_line}",
        llm_line,
        f"🎛️ Mood: {CHAT_MOOD}",
        "",
        "Modules:",
        f"🎬 Radarr — {'ACTIVE' if RADARR_ENABLED else 'OFF'}",
        f"📺 Sonarr — {'ACTIVE' if SONARR_ENABLED else 'OFF'}",
        f"🌤️ Weather — {'ACTIVE' if WEATHER_ENABLED else 'OFF'}",
        f"🧾 Digest — {'ACTIVE' if DIGEST_ENABLED_FILE else 'OFF'}",
        f"💬 Chat — {'ACTIVE' if CHAT_ENABLED_FILE else 'OFF'}",
        f"📈 Uptime Kuma — {'ACTIVE' if KUMA_ENABLED else 'OFF'}",
        f"📨 SMTP Intake — {'ACTIVE' if SMTP_ENABLED else 'OFF'}",
        f"🔀 Proxy (Gotify/ntfy) — {'ACTIVE' if PROXY_ENABLED else 'OFF'}",
        f"🧠 DNS (Technitium) — {'ACTIVE' if TECHNITIUM_ENABLED else 'OFF'}",
        "",
        "Status: All systems nominal" if online else "Status: Neural Core warming up…",
    ]
    send_message("Startup", "\n".join(lines), priority=4)

# -----------------------------
# Command handling helpers (safe calls)
# -----------------------------
def _try_call(module, fn_name, *args, **kwargs):
    try:
        if module and hasattr(module, fn_name):
            fn = getattr(module, fn_name)
            return fn(*args, **kwargs)
    except Exception as e:
        return f"⚠️ {fn_name} failed: {e}", None
    return None, None

def _handle_command(ncmd: str):
    # Imports on demand so missing modules don't crash
    m_arr = None; m_weather = None; m_kuma = None; m_tech = None; m_digest = None
    try:
        m_arr = __import__("arr")
    except Exception: pass
    try:
        m_weather = __import__("weather")
    except Exception: pass
    try:
        m_kuma = __import__("uptimekuma")
    except Exception: pass
    try:
        m_tech = __import__("technitium")
    except Exception: pass
    try:
        m_digest = __import__("digest")
    except Exception: pass

    if ncmd in ("help", "commands"):
        help_text = (
            "🤖 Jarvis Prime — Commands\n"
            f"Mood: {CHAT_MOOD}\n\n"
            "Core:\n"
            "  • dns — Technitium DNS summary\n"
            "  • kuma — Uptime Kuma status (aliases: uptime, monitor)\n"
            "  • weather — Current weather (aliases: now, today, temp)\n"
            "  • forecast — Short forecast (aliases: weekly, 7day)\n"
            "  • digest — Daily digest now (aliases: daily digest, summary)\n"
            "  • joke — One short joke\n\n"
            "Media (ARR):\n"
            "  • upcoming movies | upcoming series | movie count | series count | longest movie | longest series\n"
        )
        send_message("Help", help_text)
        return True

    if ncmd in ("digest", "daily digest", "summary"):
        if m_digest and hasattr(m_digest, "build_digest"):
            title2, msg2, pr = m_digest.build_digest(merged)
            if _personality and hasattr(_personality, "quip"):
                msg2 += f"\n\n{_personality.quip(CHAT_MOOD)}"
            send_message(title2, msg2, priority=pr)
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
                if isinstance(text, tuple):
                    text = text[0]
            except Exception as e:
                text = f"⚠️ Weather failed: {e}"
        send_message("Weather", text or "No data.")
        return True

    if ncmd in ("forecast", "weekly", "7day", "7-day", "7 day"):
        text = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text = m_weather.handle_weather_command("forecast")
                if isinstance(text, tuple):
                    text = text[0]
            except Exception as e:
                text = f"⚠️ Forecast failed: {e}"
        send_message("Forecast", text or "No data.")
        return True

    # ARR commands
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

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting {ws_url}")
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        print(f"[{BOT_NAME}] ✅ Connected")
        async for msg in ws:
            try:
                data = json.loads(msg)
                msg_id = data.get("id")

                # always skip our own posts
                if _is_our_post(data):
                    continue

                title   = data.get("title", "")   or ""
                message = data.get("message", "") or ""

                # Commands (do NOT skip LLM anymore)
                ncmd = normalize_cmd(extract_command_from(title, message))
                if ncmd:
                    handled = _handle_command(ncmd)
                    if handled:
                        _purge_after(msg_id)
                        continue

                # Otherwise, relay message → LLM then Beautify
                final, extras, used_llm, used_beautify = _llm_then_beautify(title, message)
                send_message(title or "Notification", final, priority=5, extras=extras)
                _purge_after(msg_id)

            except Exception as e:
                print(f"[{BOT_NAME}] ⚠️ Stream handling error: {e}")

# -----------------------------
# Main
# -----------------------------
def main():
    resolve_app_id()
    try:
        start_sidecars()   # <- bring back proxy/smtp listeners
        post_startup_card()
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Startup error: {e}")

    loop = asyncio.get_event_loop()
    while True:
        try:
            loop.run_until_complete(listen())
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ WS error, reconnecting in 3s: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()
