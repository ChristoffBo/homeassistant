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

CHAT_MOOD = "neutral"  # compatibility token; real persona comes from personality_state

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
        CHAT_MOOD = ACTIVE_PERSONA
    except Exception:
        pass

# ============================
# Sidecars
# ============================
_sidecars: List[subprocess.Popen] = []

def _start_sidecar(cmd, label):
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        _sidecars.append(p)
    except Exception as e:
        print(f"[bot] sidecar {label} start failed: {e}")

def start_sidecars():
    if PROXY_ENABLED:
        _start_sidecar(["python3","/app/proxy.py"], "proxy.py")
    if SMTP_ENABLED:
        _start_sidecar(["python3","/app/smtp_server.py"], "smtp_server.py")

def stop_sidecars():
    for p in _sidecars:
        try: p.terminate()
        except Exception: pass
atexit.register(stop_sidecars)

# ============================
# Gotify helpers
# ============================
def _persona_line(quip_text: str) -> str:
    who = ACTIVE_PERSONA or CHAT_MOOD or "neutral"
    quip_text = (quip_text or "").strip().replace("\n", " ")
    if len(quip_text) > 140:
        quip_text = quip_text[:137] + "..."
    return f"💬 {who} says: {quip_text}" if quip_text else f"💬 {who} says:"

def send_message(title, message, priority=5, extras=None, decorate=True):
    orig_title = title
    is_beautified = isinstance(extras, dict) and extras.get("jarvis::beautified") is True

    # Decorate body, but keep the original title so it doesn't become a banner
    if decorate and not is_beautified and _personality and hasattr(_personality, "decorate_by_persona"):
        title, message = _personality.decorate_by_persona(title, message, ACTIVE_PERSONA, PERSONA_TOD, chance=1.0)
        title = orig_title
    elif decorate and not is_beautified and _personality and hasattr(_personality, "decorate"):
        title, message = _personality.decorate(title, message, CHAT_MOOD, chance=1.0)
        title = orig_title

    # Persona speaking line at the top (skip if beautifier already placed overlay)
    if not is_beautified:
        try:
            quip_text = _personality.quip(ACTIVE_PERSONA) if _personality and hasattr(_personality, "quip") else ""
        except Exception:
            quip_text = ""
        header = _persona_line(quip_text)
        message = (header + ("\n" + (message or ""))) if header else (message or "")

    # Priority tweak via personality if present
    if _personality and hasattr(_personality, "apply_priority"):
        try: priority = _personality.apply_priority(priority, CHAT_MOOD)
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
        return t.startswith(f\"{BOT_ICON} {BOT_NAME}:\")
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
    used_llm = False; used_beautify = False; final = message or ""; extras = None
    # (LLM rewrite left exactly as before if you enable it)
    try:
        if BEAUTIFY_ENABLED and _beautify and hasattr(_beautify, "beautify_message"):
            final, extras = _beautify.beautify_message(
                title, final,
                mood=CHAT_MOOD,
                mode=str(merged.get('beautify_mode','standard')),
                persona=ACTIVE_PERSONA,
                persona_quip=bool(merged.get('personality_quips', True))
            )
            used_beautify = True
    except Exception as e:
        print(f"[bot] Beautify failed: {e}")

    foot = _footer(used_llm, used_beautify)
    if final and not final.rstrip().endswith(foot):
        final = f\"{final.rstrip()}\\n\\n{foot}\"
    return final, extras, used_llm, used_beautify

# ============================
# Commands (unchanged critical paths)
# ============================
def _clean(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r\"[^\\w\\s]\", \" \", s)
    s = re.sub(r\"\\s+\", \" \", s).strip()
    return s

def normalize_cmd(cmd: str) -> str:
    try:
        if _aliases and hasattr(_aliases, \"normalize_cmd\"):
            return _aliases.normalize_cmd(cmd)
    except Exception:
        pass
    return _clean(cmd)

def extract_command_from(title: str, message: str) -> str:
    tlow, mlow = (title or \"\").lower(), (message or \"\").lower()
    if tlow.startswith(\"jarvis\"):
        rest = tlow.replace(\"jarvis\",\"\",1).strip()
        return rest or (mlow.replace(\"jarvis\",\"\",1).strip() if mlow.startswith(\"jarvis\") else mlow.strip())
    if mlow.startswith(\"jarvis\"): return mlow.replace(\"jarvis\",\"\",1).strip()
    return \"\"

def post_startup_card():
    lines = [
        \"🧬 Prime Neural Boot\",
        f\"🗣️ Persona speaking: {ACTIVE_PERSONA} ({PERSONA_TOD})\",
        \"\",
        \"Modules:\",
        f\"🎬 Radarr — {'ACTIVE' if RADARR_ENABLED else 'OFF'}\",
        f\"📺 Sonarr — {'ACTIVE' if SONARR_ENABLED else 'OFF'}\",
        f\"🌤️ Weather — {'ACTIVE' if WEATHER_ENABLED else 'OFF'}\",
        f\"🧾 Digest — {'ACTIVE' if DIGEST_ENABLED_FILE else 'OFF'}\",
        f\"💬 Chat — {'ACTIVE' if CHAT_ENABLED_FILE else 'OFF'}\",
        f\"📈 Uptime Kuma — {'ACTIVE' if KUMA_ENABLED else 'OFF'}\",
        f\"✉️ SMTP Intake — {'ACTIVE' if SMTP_ENABLED else 'OFF'}\",
        f\"🔀 Proxy (Gotify/ntfy) — {'ACTIVE' if PROXY_ENABLED else 'OFF'}\",
        f\"🧠 DNS (Technitium) — {'ACTIVE' if TECHNITIUM_ENABLED else 'OFF'}\",
        \"\",
        \"Status: All systems nominal\",
    ]
    send_message(\"Startup\", \"\\n\".join(lines), priority=4, decorate=False)

def _try_call(module, fn_name, *args, **kwargs):
    try:
        if module and hasattr(module, fn_name):
            return getattr(module, fn_name)(*args, **kwargs)
    except Exception as e:
        return f\"⚠️ {fn_name} failed: {e}\", None
    return None, None

def _handle_command(ncmd: str) -> bool:
    return False

# ============================
# WebSocket listener
# ============================
async def listen():
    ws_url = GOTIFY_URL.replace(\"http://\",\"ws://\").replace(\"https://\",\"wss://\") + f\"/stream?token={CLIENT_TOKEN}\"
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        async for raw in ws:
            try:
                data = json.loads(raw); msg_id = data.get(\"id\")
                title = data.get(\"title\") or \"\"
                message = data.get(\"message\") or \"\"

                ncmd = normalize_cmd(extract_command_from(title, message))
                if ncmd and _handle_command(ncmd):
                    if bool(merged.get(\"silent_repost\", SILENT_REPOST)):
                        try:
                            url = f\"{GOTIFY_URL}/message/{msg_id}\"; headers = {\"X-Gotify-Key\": CLIENT_TOKEN}
                            requests.delete(url, headers=headers, timeout=6)
                        except Exception: pass
                    continue

                if data.get(\"appid\") == None:
                    pass

                final, extras, used_llm, used_beautify = _llm_then_beautify(title, message)
                send_message(title or \"Notification\", final, priority=5, extras=extras)
                if bool(merged.get(\"silent_repost\", SILENT_REPOST)):
                    try:
                        url = f\"{GOTIFY_URL}/message/{msg_id}\"; headers = {\"X-Gotify-Key\": CLIENT_TOKEN}
                        requests.delete(url, headers=headers, timeout=6)
                    except Exception: pass
            except Exception as e:
                print(f\"[bot] listen loop err: {e}\")

_last_digest_date = None

async def _digest_scheduler_loop():
    while True:
        await asyncio.sleep(60)

try:
    from aiohttp import web
except Exception:
    web = None

async def _start_internal_wake_server():
    return

async def _run_forever():
    try:
        asyncio.create_task(_start_internal_wake_server())
    except Exception: pass
    asyncio.create_task(_digest_scheduler_loop())
    while True:
        try:
            await listen()
        except Exception:
            await asyncio.sleep(3)

def main():
    try:
        post_startup_card()
    except Exception:
        pass
    asyncio.run(_run_forever())

if __name__ == \"__main__\":
    main()
