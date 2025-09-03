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
from typing import Optional, Tuple, List

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
GOTIFY_URL   = os.getenv("GOTIFY_URL", "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
APP_NAME     = os.getenv("JARVIS_APP_NAME", "Jarvis")

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

# --- Webhook feature toggles (safe defaults; overridden by /data/options.json)
WEBHOOK_ENABLED    = os.getenv("webhook_enabled", "false").lower() in ("1","true","yes")
WEBHOOK_BIND       = os.getenv("webhook_bind", "0.0.0.0")
WEBHOOK_PORT       = int(os.getenv("webhook_port", "2590"))

# --- Apprise intake toggles (safe defaults; overridden by /data/options.json)
INTAKE_APPRISE_ENABLED = os.getenv("intake_apprise_enabled", "false").lower() in ("1","true","yes")
INTAKE_APPRISE_TOKEN = os.getenv("intake_apprise_token", "")
INTAKE_APPRISE_ACCEPT_ANY_KEY = os.getenv("intake_apprise_accept_any_key", "true").lower() in ("1","true","yes")
INTAKE_APPRISE_ALLOWED_KEYS = [k for k in os.getenv("intake_apprise_allowed_keys", "").split(",") if k.strip()]
INTAKE_APPRISE_PORT = int(os.getenv("intake_apprise_port", "2591"))

# --- LLM behavior toggles ---
LLM_REWRITE_ENABLED = os.getenv("LLM_REWRITE_ENABLED", "false").lower() in ("1","true","yes")
BEAUTIFY_LLM_ENABLED_ENV = os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() in ("1","true","yes")

# ============================
# Load /data/options.json
# ============================
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
    CHAT_ENABLED_FILE   = bool(merged.get("chat_enabled", CHAT_ENABLED_ENV))
    DIGEST_ENABLED_FILE = bool(merged.get("digest_enabled", DIGEST_ENABLED_ENV))

    # webhook settings
    WEBHOOK_ENABLED = bool(merged.get("webhook_enabled", WEBHOOK_ENABLED))
    WEBHOOK_BIND    = str(merged.get("webhook_bind", WEBHOOK_BIND))
    try:
        WEBHOOK_PORT = int(merged.get("webhook_port", WEBHOOK_PORT))
    except Exception:
        pass

    # Apprise intake settings
    INTAKE_APPRISE_ENABLED = bool(merged.get("intake_apprise_enabled", INTAKE_APPRISE_ENABLED))
    INTAKE_APPRISE_TOKEN = str(merged.get("intake_apprise_token", INTAKE_APPRISE_TOKEN or ""))
    INTAKE_APPRISE_ACCEPT_ANY_KEY = bool(merged.get("intake_apprise_accept_any_key", INTAKE_APPRISE_ACCEPT_ANY_KEY))
    try:
        _allowed = merged.get("intake_apprise_allowed_keys", INTAKE_APPRISE_ALLOWED_KEYS)
        if isinstance(_allowed, list):
            INTAKE_APPRISE_ALLOWED_KEYS = [str(x) for x in _allowed]
        elif isinstance(_allowed, str) and _allowed.strip():
            INTAKE_APPRISE_ALLOWED_KEYS = [s.strip() for s in _allowed.split(",")]
        else:
            INTAKE_APPRISE_ALLOWED_KEYS = []
    except Exception:
        pass
    try:
        INTAKE_APPRISE_PORT = int(merged.get("intake_apprise_port", INTAKE_APPRISE_PORT))
    except Exception:
        pass

    # LLM behavior
    LLM_REWRITE_ENABLED = bool(merged.get("llm_rewrite_enabled", LLM_REWRITE_ENABLED))
    _beautify_llm_enabled_opt = merged.get("llm_persona_riffs_enabled", BEAUTIFY_LLM_ENABLED_ENV)
    os.environ["BEAUTIFY_LLM_ENABLED"] = "true" if _beautify_llm_enabled_opt else "false"
except Exception:
    PROXY_ENABLED = PROXY_ENABLED_ENV
    CHAT_ENABLED_FILE = CHAT_ENABLED_ENV
    DIGEST_ENABLED_FILE = DIGEST_ENABLED_ENV

# ============================
# Load optional modules
# ============================
def _load_module(name, path):
    try:
        import importlib.util as _imp
        spec = _imp.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = _imp.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    except Exception:
        pass
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
    except Exception:
        pass

# ============================
# Sidecars
# ============================
_sidecars: List[subprocess.Popen] = []

def _is_port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

def _start_sidecar(cmd, label, env=None):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        _sidecars.append(p)
        print(f"[bot] started {label}")
    except Exception as e:
        print(f"[bot] sidecar {label} start failed: {e}")

def start_sidecars():
    # proxy.py (2580) — skip if already bound (HA rebuilds can double-start)
    if PROXY_ENABLED:
        if not _is_port_in_use("0.0.0.0", 2580) and not _is_port_in_use("127.0.0.1", 2580):
            _start_sidecar(["python3","/app/proxy.py"], "proxy.py")
        else:
            print("[bot] proxy already listening; skip start")

    # smtp_server.py (2525)
    if SMTP_ENABLED:
        if not _is_port_in_use("0.0.0.0", 2525) and not _is_port_in_use("127.0.0.1", 2525):
            _start_sidecar(["python3","/app/smtp_server.py"], "smtp_server.py")
        else:
            print("[bot] smtp already listening; skip start")

    # webhook_server.py (WEBHOOK_PORT)
    if WEBHOOK_ENABLED:
        if not _is_port_in_use("0.0.0.0", WEBHOOK_PORT) and not _is_port_in_use("127.0.0.1", WEBHOOK_PORT):
            env = os.environ.copy()
            env["webhook_bind"] = WEBHOOK_BIND
            env["webhook_port"] = str(WEBHOOK_PORT)
            _start_sidecar(["python3","/app/webhook_server.py"], "webhook_server.py", env=env)
        else:
            print("[bot] webhook already listening; skip start")

    # Apprise intake (/app/intakes/apprise.py) on INTAKE_APPRISE_PORT
    if INTAKE_APPRISE_ENABLED:
        if not _is_port_in_use("0.0.0.0", INTAKE_APPRISE_PORT) and not _is_port_in_use("127.0.0.1", INTAKE_APPRISE_PORT):
            env = os.environ.copy()
            env["apprise_port"] = str(INTAKE_APPRISE_PORT)
            env["apprise_token"] = INTAKE_APPRISE_TOKEN
            env["apprise_accept_any_key"] = "true" if INTAKE_APPRISE_ACCEPT_ANY_KEY else "false"
            env["apprise_allowed_keys"] = ",".join(INTAKE_APPRISE_ALLOWED_KEYS or [])
            _start_sidecar(["python3","/app/intakes/apprise.py"], "apprise.py", env=env)
            print(f"[bot] apprise intake on :{INTAKE_APPRISE_PORT} (accept_any={INTAKE_APPRISE_ACCEPT_ANY_KEY})")
        else:
            print("[bot] apprise already listening; skip start")

def stop_sidecars():
    for p in _sidecars:
        try: p.terminate()
        except Exception: pass
atexit.register(stop_sidecars)

# ============================
# Gotify helpers
# ============================
def _persona_line(quip_text: str) -> str:
    who = ACTIVE_PERSONA or "neutral"
    quip_text = (quip_text or "").strip().replace("\n", " ")
    if len(quip_text) > 140:
        quip_text = quip_text[:137] + "..."
    return f"💬 {who} says: {quip_text}" if quip_text else f"💬 {who} says:"

def send_message(title, message, priority=5, extras=None, decorate=True):
    orig_title = title

    # Decorate body, but keep the original title
    if decorate and _personality and hasattr(_personality, "decorate_by_persona"):
        title, message = _personality.decorate_by_persona(title, message, ACTIVE_PERSONA, PERSONA_TOD, chance=1.0)
        title = orig_title
    elif decorate and _personality and hasattr(_personality, "decorate"):
        title, message = _personality.decorate(title, message, ACTIVE_PERSONA, chance=1.0)
        title = orig_title

    # Persona speaking line at the top
    try:
        quip_text = _personality.quip(ACTIVE_PERSONA) if _personality and hasattr(_personality, "quip") else ""
    except Exception:
        quip_text = ""
    header = _persona_line(quip_text)
    message = (header + ("\n" + (message or ""))) if header else (message or "")

    # Priority tweak via personality if present
    if _personality and hasattr(_personality, "apply_priority"):
        try: priority = _personality.apply_priority(priority, ACTIVE_PERSONA)
        except Exception: pass

    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message or "", "priority": priority}
    if extras: payload["extras"] = extras
    try:
        r = requests.post(url, json=payload, timeout=8)
        r.raise_for_status()
        status = r.status_code
    except Exception as e:
        status = 0
        print(f"[bot] send_message error: {e}")

    # Mirror to Inbox DB (UI-first)
    if storage:
        try:
            storage.save_message(
                title=orig_title or "Notification",
                body=message or "",
                source="gotify",
                priority=int(priority),
                extras={"extras": extras or {}, "status": status},
                created_at=int(time.time())
            )
        except Exception as e:
            print(f"[bot] storage save failed: {e}")

    return True

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
    except Exception:
        pass

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

# ============================
# LLM + Beautify
# ============================
def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _llm_then_beautify(title: str, message: str):
    used_llm = False
    used_beautify = False
    final = message or ""
    extras = None

    # Optional rewrite (OFF by default). Uses active persona context only.
    if LLM_REWRITE_ENABLED and merged.get("llm_enabled") and _llm and hasattr(_llm, "rewrite"):
        try:
            final2 = _llm.rewrite(
                text=final,
                mood=ACTIVE_PERSONA,
                timeout=int(merged.get("llm_timeout_seconds",12)),
                cpu_limit=int(merged.get("llm_max_cpu_percent",70)),
                models_priority=merged.get("llm_models_priority", []),
                base_url=merged.get("llm_ollama_base_url",""),
                model_url=merged.get("llm_model_url",""),
                model_path=merged.get("llm_model_path",""),
                model_sha256=merged.get("llm_model_sha256",""),
                allow_profanity=bool(merged.get("personality_allow_profanity", False))
            )
            if final2:
                final = final2
                used_llm = True
        except Exception as e:
            print(f"[bot] LLM rewrite failed (disabled by default): {e}")

    # Always beautify; pass persona so overlay + bottom riffs work
    if _beautify and hasattr(_beautify, "beautify_message"):
        try:
            final, extras = _beautify.beautify_message(
                title, final,
                mood=ACTIVE_PERSONA,
                persona=ACTIVE_PERSONA,
                persona_quip=True
            )
            used_beautify = True
        except Exception as e:
            print(f"[bot] Beautify failed: {e}")

    foot = _footer(used_llm, used_beautify)
    if final and not final.rstrip().endswith(foot):
        final = f"{final.rstrip()}\n\n{foot}"
    return final, extras, used_llm, used_beautify

# ============================
# Commands
# ============================
def _clean(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)  # strip punctuation
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
        rest = tlow.replace("jarvis","",1).strip()
        return rest or (mlow.replace("jarvis","",1).strip() if mlow.startswith("jarvis") else mlow.strip())
    if mlow.startswith("jarvis"): return mlow.replace("jarvis","",1).strip()
    return ""

def post_startup_card():
    lines = [
        "🧬 Prime Neural Boot",
        "🛰️ Engine: Neural Core — ONLINE" if merged.get("llm_enabled") else "🛰️ Engine: Neural Core — OFFLINE",
        f"🧠 LLM: {'Enabled' if merged.get('llm_enabled') else 'Disabled'}",
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
        f"🔀 Proxy Intake — {'ACTIVE' if PROXY_ENABLED else 'OFF'}",
        f"🧠 DNS (Technitium) — {'ACTIVE' if TECHNITIUM_ENABLED else 'OFF'}",
        f"🔗 Webhook Intake — {'ACTIVE' if WEBHOOK_ENABLED else 'OFF'}",
        f"📮 Apprise Intake — {'ACTIVE' if INTAKE_APPRISE_ENABLED else 'OFF'}",
        "",
        f"LLM rewrite: {'ON' if LLM_REWRITE_ENABLED else 'OFF'}",
        f"Persona riffs: {'ON' if os.getenv('BEAUTIFY_LLM_ENABLED','true').lower() in ('1','true','yes') else 'OFF'}",
        "Status: All systems nominal",
    ]
    send_message("Startup", "\n".join(lines), priority=4, decorate=False)

def _try_call(module, fn_name, *args, **kwargs):
    try:
        if module and hasattr(module, fn_name):
            return getattr(module, fn_name)(*args, **kwargs)
    except Exception as e:
        return f"⚠️ {fn_name} failed: {e}", None
    return None, None

def _handle_command(ncmd: str) -> bool:
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
        send_message("Help", "dns | kuma | weather | forecast | digest | joke\nARR: upcoming movies/series, counts, longest ...")
        return True

    if ncmd in ("digest", "daily digest", "summary"):
        if m_digest and hasattr(m_digest, "build_digest"):
            title2, msg2, pr = m_digest.build_digest(merged)
            try:
                if _personality and hasattr(_personality, "quip"):
                    msg2 += f"\n\n{_personality.quip(ACTIVE_PERSONA)}"
            except Exception:
                pass
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

    # Jokes / chat
    if ncmd in ("joke", "pun", "tell me a joke", "make me laugh", "chat"):
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

# ============================
# WebSocket listener
# ============================
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        async for raw in ws:
            try:
                data = json.loads(raw); msg_id = data.get("id")
                title = data.get("title") or ""
                message = data.get("message") or ""

                # wake-word first so commands work even if posted via same app
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
                print(f"[bot] listen loop err: {e}")

# ============================
# Daily scheduler (digest)
# ============================
_last_digest_date = None

async def _digest_scheduler_loop():
    # Check once a minute; when local time == digest_time and enabled, post digest once per day.
    global _last_digest_date
    from datetime import datetime
    while True:
        try:
            if merged.get("digest_enabled"):
                target = str(merged.get("digest_time", "08:00")).strip()
                now = datetime.now()
                if now.strftime("%H:%M") == target and _last_digest_date != now.date():
                    try:
                        import digest as _digest_mod
                        if hasattr(_digest_mod, "build_digest"):
                            title, msg, pr = _digest_mod.build_digest(merged)
                            send_message("Digest", msg, priority=pr)
                            _last_digest_date = now.date()
                        else:
                            _last_digest_date = now.date()
                    except Exception as e:
                        print(f"[Scheduler] digest error: {e}")
                        _last_digest_date = now.date()
        except Exception as e:
            print(f"[Scheduler] loop error: {e}")
        await asyncio.sleep(60)

# ============================
# Internal wake HTTP server
# ============================
try:
    from aiohttp import web
except Exception:
    web = None

async def _internal_wake(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    text = str(data.get("text") or "").strip()
    # Normalize typical prefixes like "jarvis ..."
    cmd = text
    for kw in ("jarvis", "hey jarvis", "ok jarvis"):
        if cmd.lower().startswith(kw):
            cmd = cmd[len(kw):].strip()
            break
    ok = False
    try:
        ok = bool(_handle_command(cmd))
    except Exception as e:
        try:
            send_message("Wake Error", f"{e}", priority=5)
        except Exception:
            pass
    return web.json_response({"ok": bool(ok)})

async def _start_internal_wake_server():
    if web is None:
        print("[bot] aiohttp not available; internal wake disabled")
        return
    try:
        app = web.Application()
        app.router.add_post("/internal/wake", _internal_wake)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 2599)
        await site.start()
        print("[bot] internal wake server listening on 127.0.0.1:2599")
    except Exception as e:
        print(f"[bot] failed to start internal wake server: {e}")

# ============================
# Main
# ============================
def main():
    resolve_app_id()
    try:
        start_sidecars()
        post_startup_card()
    except Exception:
        pass
    asyncio.run(_run_forever())

async def _run_forever():
    try:
        asyncio.create_task(_start_internal_wake_server())
    except Exception:
        pass
    asyncio.create_task(_digest_scheduler_loop())
    while True:
        try:
            await listen()
        except Exception:
            await asyncio.sleep(3)

if __name__ == "__main__":
    main()