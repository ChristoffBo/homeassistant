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

# Output
GOTIFY_URL   = os.getenv("GOTIFY_URL", "").rstrip("/")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN    = os.getenv("GOTIFY_APP_TOKEN", "")
APP_NAME     = os.getenv("JARVIS_APP_NAME", "Jarvis")

SILENT_REPOST    = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

RADARR_ENABLED     = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED     = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED    = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV   = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED       = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")
SMTP_ENABLED       = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")
PROXY_ENABLED_ENV  = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")

INGEST_GOTIFY_ENABLED  = os.getenv("ingest_gotify_enabled", "true").lower() in ("1","true","yes")
INGEST_APPRISE_ENABLED = os.getenv("ingest_apprise_enabled", "true").lower() in ("1","true","yes")
INGEST_SMTP_ENABLED    = os.getenv("ingest_smtp_enabled", "true").lower() in ("1","true","yes")
INGEST_NTFY_ENABLED    = os.getenv("ingest_ntfy_enabled", "false").lower() in ("1","true","yes")

WEBHOOK_ENABLED    = os.getenv("webhook_enabled", "false").lower() in ("1","true","yes")
WEBHOOK_BIND       = os.getenv("webhook_bind", "0.0.0.0")
WEBHOOK_PORT       = int(os.getenv("webhook_port", "2590"))

INTAKE_APPRISE_ENABLED = os.getenv("intake_apprise_enabled", "false").lower() in ("1","true","yes")
INTAKE_APPRISE_TOKEN = os.getenv("intake_apprise_token", "")
INTAKE_APPRISE_ACCEPT_ANY_KEY = os.getenv("intake_apprise_accept_any_key", "true").lower() in ("1","true","yes")
INTAKE_APPRISE_ALLOWED_KEYS = [k for k in os.getenv("intake_apprise_allowed_keys", "").split(",") if k.strip()]
INTAKE_APPRISE_PORT = int(os.getenv("intake_apprise_port", "2591"))
INTAKE_APPRISE_BIND = os.getenv("intake_apprise_bind", "0.0.0.0")

LLM_REWRITE_ENABLED = os.getenv("LLM_REWRITE_ENABLED", "false").lower() in ("1","true","yes")
BEAUTIFY_LLM_ENABLED_ENV = os.getenv("BEAUTIFY_LLM_ENABLED", "true").lower() in ("1","true","yes")

PROXY_ENABLED = PROXY_ENABLED_ENV
CHAT_ENABLED_FILE = CHAT_ENABLED_ENV
DIGEST_ENABLED_FILE = DIGEST_ENABLED_ENV
# ============================
# Load /data/options.json (overrides) + /data/config.json (fallback)
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

    INGEST_GOTIFY_ENABLED  = bool(merged.get("ingest_gotify_enabled", INGEST_GOTIFY_ENABLED))
    INGEST_APPRISE_ENABLED = bool(merged.get("intake_apprise_enabled", INTAKE_APPRISE_ENABLED)) and bool(merged.get("ingest_apprise_enabled", INGEST_APPRISE_ENABLED))
    INGEST_SMTP_ENABLED    = bool(merged.get("ingest_smtp_enabled", INGEST_SMTP_ENABLED))
    INGEST_NTFY_ENABLED    = bool(merged.get("ingest_ntfy_enabled", INGEST_NTFY_ENABLED))

    WEBHOOK_ENABLED = bool(merged.get("webhook_enabled", WEBHOOK_ENABLED))
    WEBHOOK_BIND    = str(merged.get("webhook_bind", WEBHOOK_BIND))
    try:
        WEBHOOK_PORT = int(merged.get("webhook_port", WEBHOOK_PORT))
    except Exception:
        pass

    INTAKE_APPRISE_ENABLED = bool(merged.get("intake_apprise_enabled", INTAKE_APPRISE_ENABLED))
    INTAKE_APPRISE_TOKEN = str(merged.get("intake_apprise_token", INTAKE_APPRISE_TOKEN or ""))
    INTAKE_APPRISE_ACCEPT_ANY_KEY = bool(merged.get("intake_apprise_accept_any_key", INTAKE_APPRISE_ACCEPT_ANY_KEY))
    INTAKE_APPRISE_PORT = int(merged.get("intake_apprise_port", INTAKE_APPRISE_PORT))
    INTAKE_APPRISE_BIND = str(merged.get("intake_apprise_bind", INTAKE_APPRISE_BIND or "0.0.0.0"))
    _allowed = merged.get("intake_apprise_allowed_keys", INTAKE_APPRISE_ALLOWED_KEYS)
    if isinstance(_allowed, list):
        INTAKE_APPRISE_ALLOWED_KEYS = [str(x) for x in _allowed]
    elif isinstance(_allowed, str) and _allowed.strip():
        INTAKE_APPRISE_ALLOWED_KEYS = [s.strip() for s in _allowed.split(",")]
    else:
        INTAKE_APPRISE_ALLOWED_KEYS = []

    LLM_REWRITE_ENABLED = bool(merged.get("llm_rewrite_enabled", LLM_REWRITE_ENABLED))
    _beautify_llm_enabled_opt = bool(merged.get("llm_persona_riffs_enabled", BEAUTIFY_LLM_ENABLED_ENV))
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
    except Exception as e:
        print(f"[bot] module load failed {name}: {e}")
    return None

_aliases = _load_module("aliases", "/app/aliases.py")
_personality = _load_module("personality", "/app/personality.py")
_pstate = _load_module("personality_state", "/app/personality_state.py")
_beautify = _load_module("beautify", "/app/beautify.py")
_llm = _load_module("llm_client", "/app/llm_client.py")
_digest = _load_module("digest", "/app/digest.py")
_chat = _load_module("chat", "/app/chat.py")
_heartbeat = _load_module("heartbeat", "/app/heartbeat.py")
# === EnviroGuard (INLINE — no extra file) ===
ENVGUARD = {
    "enabled": bool(merged.get("llm_enviroguard_enabled", False)),
    "poll_minutes": int(merged.get("llm_enviroguard_poll_minutes", 30)),
    "max_stale_minutes": int(merged.get("llm_enviroguard_max_stale_minutes", 120)),
    "hot_c": int(merged.get("llm_enviroguard_hot_c", 30)),
    "cold_c": int(merged.get("llm_enviroguard_cold_c", 10)),
    "hyst_c": int(merged.get("llm_enviroguard_hysteresis_c", 2)),
    "profiles": merged.get("llm_enviroguard_profiles", {
        "manual": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "hot":    { "cpu_percent": 50, "ctx_tokens": 2048, "timeout_seconds": 15 },
        "normal": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
        "boost":  { "cpu_percent": 95, "ctx_tokens": 8192, "timeout_seconds": 25 },
        "cold":   { "cpu_percent": 85, "ctx_tokens": 6144, "timeout_seconds": 25 }
    }),
    "profile": "normal",
    "temp_c": None,
    "last_ts": 0,
    "source": "open-meteo"
}

if isinstance(ENVGUARD["profiles"], str):
    try:
        ENVGUARD["profiles"] = json.loads(ENVGUARD["profiles"])
    except Exception:
        ENVGUARD["profiles"] = {
            "manual": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
            "hot":    { "cpu_percent": 50, "ctx_tokens": 2048, "timeout_seconds": 15 },
            "normal": { "cpu_percent": 80, "ctx_tokens": 4096, "timeout_seconds": 20 },
            "boost":  { "cpu_percent": 95, "ctx_tokens": 8192, "timeout_seconds": 25 },
            "cold":   { "cpu_percent": 85, "ctx_tokens": 6144, "timeout_seconds": 25 }
        }

ACTIVE_PERSONA, PERSONA_TOD = "neutral", ""
if _pstate and hasattr(_pstate, "get_active_persona"):
    try:
        ACTIVE_PERSONA, PERSONA_TOD = _pstate.get_active_persona()
    except Exception:
        pass

# ============================
# Sidecars (with port guards)
# ============================
_sidecars: List[subprocess.Popen] = []

def _port_in_use(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def _start_sidecar(cmd, label, env=None):
    try:
        p = subprocess.Popen(cmd, stdout=None, stderr=None, env=env or os.environ.copy())
        _sidecars.append(p)
        print(f"[bot] started sidecar: {label} -> {cmd}")
    except Exception as e:
        print(f"[bot] sidecar {label} start failed: {e}")

def _forward_env(extra: Optional[dict] = None) -> dict:
    env = os.environ.copy()
    env["JARVIS_INTERNAL_EMIT_URL"] = "http://127.0.0.1:2599/internal/emit"
    env["BEAUTIFY_LLM_ENABLED"] = os.getenv("BEAUTIFY_LLM_ENABLED", "true")
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env

def start_sidecars():
    if PROXY_ENABLED:
        if _port_in_use("127.0.0.1", 2580) or _port_in_use("0.0.0.0", 2580):
            print("[bot] proxy.py already running on :2580 — skipping sidecar")
        else:
            _start_sidecar(["python3", "/app/proxy.py"], "proxy.py", env=_forward_env())

    if SMTP_ENABLED and INGEST_SMTP_ENABLED:
        if _port_in_use("127.0.0.1", 2525) or _port_in_use("0.0.0.0", 2525):
            print("[bot] smtp_server.py already running on :2525 — skipping sidecar")
        else:
            _start_sidecar(["python3", "/app/smtp_server.py"], "smtp_server.py", env=_forward_env())

    if WEBHOOK_ENABLED:
        if _port_in_use("127.0.0.1", int(WEBHOOK_PORT)) or _port_in_use("0.0.0.0", int(WEBHOOK_PORT)):
            print(f"[bot] webhook_server.py already running on :{WEBHOOK_PORT} — skipping sidecar")
        else:
            env = _forward_env({"webhook_bind": WEBHOOK_BIND, "webhook_port": str(WEBHOOK_PORT)})
            _start_sidecar(["python3", "/app/webhook_server.py"], "webhook_server.py", env=env)

    if INTAKE_APPRISE_ENABLED and INGEST_APPRISE_ENABLED:
        if _port_in_use("127.0.0.1", int(INTAKE_APPRISE_PORT)) or _port_in_use("0.0.0.0", int(INTAKE_APPRISE_PORT)):
            print(f"[bot] apprise intake already running on :{INTAKE_APPRISE_PORT} — skipping sidecar")
        else:
            if not _port_in_use("127.0.0.1", 2599):
                print("[bot] deferring apprise sidecar until internal server is up on :2599")
            else:
                env = _forward_env()
                _start_sidecar(["python3", "/app/apprise.py"], "apprise.py", env=env)
                print(f"[bot] apprise intake configured on {INTAKE_APPRISE_BIND}:{INTAKE_APPRISE_PORT}")

def stop_sidecars():
    for p in _sidecars:
        try:
            p.terminate()
        except Exception:
            pass
atexit.register(stop_sidecars)
# ============================
# Gotify helpers (output)
# ============================
jarvis_app_id = None

def _persona_line(quip_text: str) -> str:
    who = ACTIVE_PERSONA or "neutral"
    quip_text = (quip_text or "").strip().replace("\n", " ")
    if len(quip_text) > 140:
        quip_text = quip_text[:137] + "..."
    return f"💬 {who} says: {quip_text}" if quip_text else f"💬 {who} says:"

def send_message(title, message, priority=5, extras=None, decorate=True):
    orig_title = title
    try:
        if decorate and _personality and hasattr(_personality, "decorate_by_persona"):
            title, message = _personality.decorate_by_persona(title, message, ACTIVE_PERSONA, PERSONA_TOD, chance=1.0)
            title = orig_title
        elif decorate and _personality and hasattr(_personality, "decorate"):
            title, message = _personality.decorate(title, message, ACTIVE_PERSONA, chance=1.0)
            title = orig_title
    except Exception:
        title, message = orig_title, message

    if GOTIFY_URL and APP_TOKEN:
        url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
        payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message or "", "priority": priority}
        if extras:
            payload["extras"] = extras
        try:
            r = requests.post(url, json=payload, timeout=8)
            r.raise_for_status()
        except Exception as e:
            print(f"[bot] send_message error: {e}")
    return True

def resolve_app_id():
    global jarvis_app_id
    jarvis_app_id = None
    if not (GOTIFY_URL and CLIENT_TOKEN):
        return
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=8)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                break
    except Exception:
        pass

# ============================
# Digest, Joke, Heartbeat schedulers
# ============================
_last_digest_date = None
_last_joke_ts = 0
_last_heartbeat_ts = 0

async def _digest_scheduler_loop():
    global _last_digest_date
    from datetime import datetime
    while True:
        try:
            if merged.get("digest_enabled"):
                target = str(merged.get("digest_time", "08:00")).strip()
                now = datetime.now()
                if now.strftime("%H:%M") == target and _last_digest_date != now.date():
                    try:
                        if _digest and hasattr(_digest, "build_digest"):
                            title, msg, pr = _digest.build_digest(merged)
                            send_message("Digest", msg, priority=pr)
                        _last_digest_date = now.date()
                    except Exception as e:
                        print(f"[Scheduler] digest error: {e}")
                        _last_digest_date = now.date()
        except Exception as e:
            print(f"[Scheduler] loop error: {e}")
        await asyncio.sleep(60)

async def _joke_scheduler_loop():
    global _last_joke_ts
    import random
    while True:
        try:
            if merged.get("chat_enabled") and _chat and hasattr(_chat, "handle_chat_command"):
                now = time.time()
                min_interval = int(merged.get("personality_min_interval_minutes", 90)) * 60
                daily_max = int(merged.get("personality_daily_max", 6))
                quiet_hours = str(merged.get("personality_quiet_hours", "23:00-06:00"))
                start, end = quiet_hours.split("-")
                from datetime import datetime
                nowdt = datetime.now()
                if not (start <= nowdt.strftime("%H:%M") <= end):
                    if (now - _last_joke_ts) > min_interval:
                        msg, _ = _chat.handle_chat_command("joke")
                        send_message("Joke", msg or "No joke available")
                        _last_joke_ts = now
        except Exception as e:
            print(f"[Scheduler] joke error: {e}")
        await asyncio.sleep(60)

async def _heartbeat_scheduler_loop():
    global _last_heartbeat_ts
    from datetime import datetime
    while True:
        try:
            if merged.get("heartbeat_enabled"):
                interval = int(merged.get("heartbeat_interval_minutes", 120)) * 60
                now = time.time()
                if (now - _last_heartbeat_ts) > interval:
                    title, msg = _heartbeat.build_heartbeat(merged) if _heartbeat else ("Heartbeat","Jarvis still alive")
                    send_message(title, msg)
                    _last_heartbeat_ts = now
        except Exception as e:
            print(f"[Scheduler] heartbeat error: {e}")
        await asyncio.sleep(60)

# ============================
# Main / loop
# ============================
def main():
    resolve_app_id()
    try:
        start_sidecars()
        send_message("Startup", "🚀 Systems online — Jarvis is awake!", priority=4, decorate=False)
    except Exception as e:
        print(f"[bot] startup err: {e}")
    asyncio.run(_run_forever())

async def _run_forever():
    asyncio.create_task(_digest_scheduler_loop())
    asyncio.create_task(_joke_scheduler_loop())
    asyncio.create_task(_heartbeat_scheduler_loop())
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    main()