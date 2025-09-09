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

    # Ingest toggles from config file if present
    INGEST_GOTIFY_ENABLED  = bool(merged.get("ingest_gotify_enabled", INGEST_GOTIFY_ENABLED))
    INGEST_APPRISE_ENABLED = bool(merged.get("intake_apprise_enabled", INTAKE_APPRISE_ENABLED)) and bool(merged.get("ingest_apprise_enabled", INGEST_APPRISE_ENABLED))
    INGEST_SMTP_ENABLED    = bool(merged.get("ingest_smtp_enabled", INGEST_SMTP_ENABLED))
    INGEST_NTFY_ENABLED    = bool(merged.get("ingest_ntfy_enabled", INGEST_NTFY_ENABLED))

    # Webhook
    WEBHOOK_ENABLED = bool(merged.get("webhook_enabled", WEBHOOK_ENABLED))
    WEBHOOK_BIND    = str(merged.get("webhook_bind", WEBHOOK_BIND))
    try:
        WEBHOOK_PORT = int(merged.get("webhook_port", WEBHOOK_PORT))
    except Exception:
        pass

    # Apprise sidecar
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

    # LLM + riffs linkup:
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
_heartbeat = _load_module("heartbeat", "/app/heartbeat.py")
_enviroguard = _load_module("enviroguard", "/app/enviroguard.py")

ACTIVE_PERSONA, PERSONA_TOD = "neutral", ""
if _pstate and hasattr(_pstate, "get_active_persona"):
    try:
        ACTIVE_PERSONA, PERSONA_TOD = _pstate.get_active_persona()
    except Exception:
        pass

# --- ADDITIVE: tappit wakeword detection ---
from personality_state import set_active_persona

def _detect_wakeword(msg: str) -> str | None:
    m = (msg or "").lower()
    if "jarvis tappit" in m or "jarvis welkom" in m or "fok" in m:
        return "tappit"
    if "jarvis nerd" in m:
        return "nerd"
    if "jarvis dude" in m:
        return "dude"
    if "jarvis chick" in m:
        return "chick"
    if "jarvis rager" in m:
        return "rager"
    if "jarvis comedian" in m:
        return "comedian"
    if "jarvis action" in m:
        return "action"
    if "jarvis default" in m or "jarvis ops" in m:
        return "ops"
    return None
# --- end additive ---
# ============================
# Gotify helpers (output)
# ============================
jarvis_app_id = None

# --- ADDITIVE: bypass list + helper for chat.py payloads ---
_CHAT_BYPASS_TITLES = {"Joke", "Quip", "Weird Fact"}
def _should_bypass_decor(title: str, extras=None) -> bool:
    try:
        if title in _CHAT_BYPASS_TITLES:
            return True
        if isinstance(extras, dict) and extras.get("bypass_beautify") is True:
            return True
    except Exception:
        pass
    return False
# --- end additive ---

def _persona_line(quip_text: str) -> str:
    who = ACTIVE_PERSONA or "neutral"
    quip_text = (quip_text or "").strip().replace("\n", " ")
    if len(quip_text) > 140:
        quip_text = quip_text[:137] + "..."
    return f"💬 {who} says: {quip_text}" if quip_text else f"💬 {who} says:"

def send_message(title, message, priority=5, extras=None, decorate=True):
    orig_title = title

    # --- ADDITIVE: auto-bypass for chat.py jokes/quip/weirdfacts ---
    _bypass = _should_bypass_decor(orig_title, extras)
    if _bypass:
        decorate = False
    # --- end additive ---

    try:
        if decorate and _personality and hasattr(_personality, "decorate_by_persona"):
            title, message = _personality.decorate_by_persona(title, message, ACTIVE_PERSONA, PERSONA_TOD, chance=1.0)
            title = orig_title
        elif decorate and _personality and hasattr(_personality, "decorate"):
            title, message = _personality.decorate(title, message, ACTIVE_PERSONA, chance=1.0)
            title = orig_title
    except Exception:
        title, message = orig_title, message

    try:
        quip_text = _personality.quip(ACTIVE_PERSONA) if _personality and hasattr(_personality, "quip") else ""
    except Exception:
        quip_text = ""

    # --- PATCH: build dynamic persona header using Lexi via personality.persona_header() ---
    try:
        if _personality and hasattr(_personality, "persona_header"):
            header = _personality.persona_header(ACTIVE_PERSONA)
        else:
            header = _persona_line(quip_text)
    except Exception:
        header = _persona_line(quip_text)
    # --- end patch ---

    # --- ADDITIVE: don't prepend persona header when bypassing ---
    if not _bypass:
        message = (header + ("\n" + (message or ""))) if header else (message or "")
    else:
        message = message or ""
    # --- end additive ---

    if _personality and hasattr(_personality, "apply_priority"):
        try:
            priority = _personality.apply_priority(priority, ACTIVE_PERSONA)
        except Exception:
            pass

    if GOTIFY_URL and APP_TOKEN:
        url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
        payload = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message or "", "priority": priority}
        if extras:
            payload["extras"] = extras
        try:
            r = requests.post(url, json=payload, timeout=8)
            r.raise_for_status()
            status = r.status_code
        except Exception as e:
            status = 0
            print(f"[bot] send_message error: {e}")
    else:
        status = -1

    if storage:
        try:
            storage.save_message(
                title=orig_title or "Notification",
                body=message or "",
                source="jarvis_out",
                priority=int(priority),
                extras={"extras": extras or {}, "status": status},
                created_at=int(time.time())
            )
        except Exception as e:
            print(f"[bot] storage save failed: {e}")

    return True

def delete_original_message(msg_id: int):
    try:
        if not (msg_id and GOTIFY_URL and CLIENT_TOKEN):
            return
        url = f"{GOTIFY_URL}/message/{msg_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        requests.delete(url, headers=headers, timeout=6)
    except Exception:
        pass

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

def _is_our_post(data: dict) -> bool:
    try:
        if jarvis_app_id and data.get("appid") == jarvis_app_id:
            return True
        t = data.get("title") or ""
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

def _footer(used_llm: bool, used_beautify: bool) -> str:
    tags = []
    if used_llm: tags.append("Neural Core ✓")
    if used_beautify: tags.append("Aesthetic Engine ✓")
    if not tags: tags.append("Relay Path")
    return "— " + " · ".join(tags)

def _llm_then_beautify(title: str, message: str):
    # Reflect LLM state in footer tag
    used_llm = bool(merged.get("llm_enabled")) or bool(merged.get("llm_rewrite_enabled")) or LLM_REWRITE_ENABLED
    used_beautify = True if _beautify else False

    # --- ADDITIVE: bypass beautifier entirely for chat.py payloads by title ---
    if title in _CHAT_BYPASS_TITLES:
        final = message or ""
        extras = None
        used_beautify = False
        # No footer either; return as-is
        return final, extras, used_llm, used_beautify
    # --- end additive ---

    final = message or ""
    extras = None

    try:
        if _beautify and hasattr(_beautify, "beautify_message"):
            final, extras = _beautify.beautify_message(
                title,
                final,
                mood=ACTIVE_PERSONA,
                persona=ACTIVE_PERSONA,
                persona_quip=True  # <— enable persona riffs for all intakes
            )
    except Exception as e:
        print(f"[bot] Beautify failed: {e}")

    foot = _footer(used_llm, used_beautify)
    if final and not final.rstrip().endswith(foot):
        final = f"{final.rstrip()}\n\n{foot}"
    return final, extras, used_llm, used_beautify
# ============================
# Dedup + intake fan-in
# ============================
_recent_hashes: dict = {}
_RECENT_TTL = 90

def _gc_recent():
    now = time.time()
    for k, exp in list(_recent_hashes.items()):
        if exp <= now:
            _recent_hashes.pop(k, None)

def _seen_recent(title: str, body: str, source: str, orig_id: Optional[str]) -> bool:
    _gc_recent()
    h = hashlib.sha256(f"{source}|{orig_id}|{title}|{body}".encode("utf-8")).hexdigest()
    if h in _recent_hashes:
        return True
    _recent_hashes[h] = time.time() + _RECENT_TTL
    return False

def _process_incoming(title: str, body: str, source: str = "intake", original_id: Optional[str] = None, priority: int = 5):
    if _seen_recent(title or "", body or "", source, original_id or ""):
        return

    # --- ADDITIVE: check wakeword + switch persona ---
    persona_switch = _detect_wakeword(f"{title} {body}")
    if persona_switch:
        try:
            set_active_persona(persona_switch)
            global ACTIVE_PERSONA, PERSONA_TOD
            ACTIVE_PERSONA, PERSONA_TOD = _pstate.get_active_persona()
            # strip wakeword phrases from message so they don't leak into output
            for phrase in [
                "jarvis tappit", "jarvis welkom", "fok",
                "jarvis nerd", "jarvis dude", "jarvis chick",
                "jarvis rager", "jarvis comedian", "jarvis action",
                "jarvis default", "jarvis ops"
            ]:
                title = title.replace(phrase, "", 1).strip()
                body  = body.replace(phrase, "", 1).strip()
        except Exception as e:
            print(f"[bot] wakeword switch failed: {e}")
    # --- end additive ---

    ncmd = normalize_cmd(extract_command_from(title, body))
    if ncmd and _handle_command(ncmd):
        try:
            if source == "gotify" and original_id:
                _purge_after(int(original_id))
        except Exception:
            pass
        return

    final, extras, used_llm, used_beautify = _llm_then_beautify(title or "Notification", body or "")
    send_message(title or "Notification", final, priority=priority, extras=extras)

    try:
        if source == "gotify" and original_id:
            _purge_after(int(original_id))
    except Exception:
        pass

# ============================
# Gotify WebSocket intake
# ============================
async def listen_gotify():
    if not (INGEST_GOTIFY_ENABLED and GOTIFY_URL and CLIENT_TOKEN):
        print("[bot] Gotify intake disabled or not configured")
        return
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[bot] Gotify intake connecting to {ws_url}")
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                        if _is_our_post(data):
                            continue
                        msg_id = data.get("id")
                        title = data.get("title") or ""
                        message = data.get("message") or ""
                        _process_incoming(title, message, source="gotify", original_id=str(msg_id), priority=int(data.get("priority", 5)))
                    except Exception as ie:
                        print(f"[bot] gotify intake msg err: {ie}")
        except Exception as e:
            print(f"[bot] gotify listen loop err: {e}")
            await asyncio.sleep(3)

# ============================
# Schedulers
# ============================
_last_digest_date = None
_last_joke_ts = 0
_joke_day = None
_joke_daily_count = 0

def _within_quiet_hours(now_hm: str, quiet: str) -> bool:
    # quiet like "23:00-06:00" (overnight window supported)
    try:
        start, end = [s.strip() for s in quiet.split("-", 1)]
        if start <= end:
            return start <= now_hm <= end
        # overnight wrap
        return (now_hm >= start) or (now_hm <= end)
    except Exception:
        return False

def _jittered_interval(base_min: int, pct: int) -> int:
    import random
    if pct <= 0: return base_min * 60
    jitter = int(base_min * pct / 100)
    return (base_min + random.randint(-jitter, jitter)) * 60

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
                        import digest as _digest_mod
                        if hasattr(_digest_mod, "build_digest"):
                            title, msg, pr = _digest_mod.build_digest(merged)
                            send_message("Digest", msg, priority=pr)
                        _last_digest_date = now.date()
                    except Exception as e:
                        print(f"[Scheduler] digest error: {e}")
                        _last_digest_date = now.date()
        except Exception as e:
            print(f"[Scheduler] loop error: {e}")
        await asyncio.sleep(60)

async def _joke_scheduler_loop():
    # Random riffs with anti-spam + quiet hours + daily cap
    global _last_joke_ts, _joke_day, _joke_daily_count
    from datetime import datetime
    while True:
        try:
            if not merged.get("chat_enabled", False):
                await asyncio.sleep(60); continue

            try:
                m_chat = __import__("chat")
            except Exception:
                m_chat = None

            if not (m_chat and hasattr(m_chat, "handle_chat_command")):
                await asyncio.sleep(60); continue

            now = time.time()
            nowdt = datetime.now()
            hm = nowdt.strftime("%H:%M")

            qh = str(merged.get("personality_quiet_hours", "23:00-06:00")).strip()
            if _within_quiet_hours(hm, qh):
                await asyncio.sleep(60); continue

            base_min = int(merged.get("personality_min_interval_minutes", 90))
            pct = int(merged.get("personality_interval_jitter_pct", 20))
            min_gap = _jittered_interval(base_min, pct)

            # daily cap
            day = nowdt.strftime("%Y-%m-%d")
            if _joke_day != day:
                _joke_day = day
                _joke_daily_count = 0
            daily_max = int(merged.get("personality_daily_max", 6))
            if _joke_daily_count >= daily_max:
                await asyncio.sleep(60); continue

            if (now - _last_joke_ts) >= min_gap:
                try:
                    msg, _ = m_chat.handle_chat_command("joke")
                except Exception as e:
                    msg = f"⚠️ Chat error: {e}"
                send_message("Joke", msg or "No joke available right now.")
                _last_joke_ts = now
                _joke_daily_count += 1
        except Exception as e:
            print(f"[Scheduler] joke error: {e}")
        await asyncio.sleep(30)
async def _heartbeat_scheduler_loop():
    # Fires on interval and within allowed time window
    from datetime import datetime
    last_sent = 0
    while True:
        try:
            if not merged.get("heartbeat_enabled", False):
                await asyncio.sleep(60); continue

            interval_s = int(merged.get("heartbeat_interval_minutes", 120)) * 60
            start_hm = str(merged.get("heartbeat_start", "06:00")).strip()
            end_hm   = str(merged.get("heartbeat_end",   "20:00")).strip()

            now = time.time()
            dt = datetime.now()
            hm = dt.strftime("%H:%M")

            # Only send within the inclusive window [start, end]
            def _within_window(hm, start, end):
                if start <= end:
                    return start <= hm <= end
                return (hm >= start) or (hm <= end)

            if (now - last_sent) >= interval_s and _within_window(hm, start_hm, end_hm):
                title, msg = ("Heartbeat", "Still alive ✅")
                if _heartbeat and hasattr(_heartbeat, "build_heartbeat"):
                    try:
                        title, msg = _heartbeat.build_heartbeat(merged)
                    except Exception as e:
                        print(f"[Heartbeat] build error: {e}")
                send_message(title, msg, priority=3, decorate=False)
                last_sent = now
        except Exception as e:
            print(f"[Scheduler] heartbeat error: {e}")
        await asyncio.sleep(30)

# ============================
# Internal HTTP server (wake + emit)
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

async def _internal_emit(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    title = str(data.get("title") or "Notification")
    body  = str(data.get("body") or "")
    prio  = int(data.get("priority", 5))
    source = str(data.get("source") or "internal")
    oid = str(data.get("id") or "")
    try:
        _process_incoming(title, body, source=source, original_id=oid, priority=prio)
        return web.json_response({"ok": True})
    except Exception as e:
        print(f"[bot] internal emit error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def _start_internal_server():
    if web is None:
        print("[bot] aiohttp not available; internal server disabled")
        return
    try:
        app = web.Application()
        app.router.add_post("/internal/wake", _internal_wake)
        app.router.add_post("/internal/emit", _internal_emit)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 2599)
        await site.start()
        print("[bot] internal server listening on 127.0.0.1:2599 (/internal/wake, /internal/emit)")
    except Exception as e:
        print(f"[bot] failed to start internal server: {e}")

# ============================
# Apprise watchdog (sidecar must bind :2591)
# ============================
async def _apprise_watchdog():
    if not (INTAKE_APPRISE_ENABLED and INGEST_APPRISE_ENABLED):
        return
    # wait for internal server to be ready first
    for _ in range(100):
        if _port_in_use("127.0.0.1", 2599):
            break
        await asyncio.sleep(0.1)
    attempt = 0
    while True:
        try:
            if _port_in_use("127.0.0.1", int(INTAKE_APPRISE_PORT)) or _port_in_use("0.0.0.0", int(INTAKE_APPRISE_PORT)):
                # healthy
                await asyncio.sleep(5)
                continue
            attempt += 1
            env = _apprise_env()
            safe_env_print = {
                "INTAKE_APPRISE_BIND": env.get("INTAKE_APPRISE_BIND"),
                "INTAKE_APPRISE_PORT": env.get("INTAKE_APPRISE_PORT"),
                "INTAKE_APPRISE_ACCEPT_ANY_KEY": env.get("INTAKE_APPRISE_ACCEPT_ANY_KEY"),
                "INTAKE_APPRISE_ALLOWED_KEYS": env.get("INTAKE_APPRISE_ALLOWED_KEYS"),
                "JARVIS_INTERNAL_EMIT_URL": env.get("JARVIS_INTERNAL_EMIT_URL")
            }
            print(f"[bot] apprise watchdog: port {INTAKE_APPRISE_PORT} not listening, restart #{attempt} with env {safe_env_print}")
            _start_sidecar(["python3", "/app/apprise.py"], "apprise.py", env=env)
            # Give it a short grace to bind
            for _ in range(30):
                if _port_in_use("127.0.0.1", int(INTAKE_APPRISE_PORT)) or _port_in_use("0.0.0.0", int(INTAKE_APPRISE_PORT)):
                    print(f"[bot] apprise watchdog: sidecar is now listening on {INTAKE_APPRISE_BIND}:{INTAKE_APPRISE_PORT}")
                    break
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"[bot] apprise watchdog error: {e}")
        await asyncio.sleep(5)

# ============================
# Main / loop
# ============================
def main():
    resolve_app_id()
    try:
        start_sidecars()
        post_startup_card()
    except Exception as e:
        print(f"[bot] startup err: {e}")
    asyncio.run(_run_forever())

async def _run_forever():
    try:
        asyncio.create_task(_start_internal_server())
    except Exception:
        pass
    asyncio.create_task(_digest_scheduler_loop())
    asyncio.create_task(listen_gotify())
    asyncio.create_task(_apprise_watchdog())
    asyncio.create_task(_joke_scheduler_loop())       # <— NEW
    asyncio.create_task(_heartbeat_scheduler_loop())  # <— NEW

    # EnviroGuard background — externalized module
    if bool(merged.get("llm_enviroguard_enabled", False)) and _enviroguard:
        try:
            # Try richest signature first
            task_or_none = None
            if hasattr(_enviroguard, "start_background_poll"):
                try:
                    task_or_none = _enviroguard.start_background_poll(config=merged, notify=send_message)
                except TypeError:
                    try:
                        task_or_none = _enviroguard.start_background_poll(merged)
                    except Exception:
                        task_or_none = None
            if asyncio.iscoroutine(task_or_none):
                asyncio.create_task(task_or_none)
        except Exception as e:
            print(f"[bot] EnviroGuard start failed: {e}")

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    main()
