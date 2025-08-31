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


# ===== Standalone intake toggles =====
BOT_INPUT_SSE     = os.getenv("BOT_INPUT_SSE", "true").lower() in ("1","true","yes")
BOT_INPUT_GOTIFY  = os.getenv("BOT_INPUT_GOTIFY", "true").lower() in ("1","true","yes")
BOT_INPUT_NTFY    = os.getenv("BOT_INPUT_NTFY", "false").lower() in ("1","true","yes")
JARVIS_BASE       = os.getenv("JARVIS_BASE", "http://127.0.0.1:2581").rstrip("/")
DEDUPE_TTL_SECONDS= int(os.getenv("DEDUPE_TTL_SECONDS", "120"))
WORKERS           = int(os.getenv("WORKERS", "2"))
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
    # Single-line persona 'speaks' header placed at TOP of message body.
    who = ACTIVE_PERSONA or CHAT_MOOD or "neutral"
    quip_text = (quip_text or "").strip().replace("\n", " ")
    if len(quip_text) > 140:
        quip_text = quip_text[:137] + "..."
    # Keep it minimal so it aligns nicely with Gotify cards
    return f"💬 {who} says: {quip_text}" if quip_text else f"💬 {who} says:"

def send_message(title, message, priority=5, extras=None, decorate=True):
    orig_title = title

    # Decorate body, but keep the original title so it doesn't become a banner
    if decorate and _personality and hasattr(_personality, "decorate_by_persona"):
        title, message = _personality.decorate_by_persona(title, message, ACTIVE_PERSONA, PERSONA_TOD, chance=1.0)
        title = orig_title
    elif decorate and _personality and hasattr(_personality, "decorate"):
        title, message = _personality.decorate(title, message, CHAT_MOOD, chance=1.0)
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
    used_llm = False; used_beautify = False; final = message or ""; extras = None
    if merged.get("llm_enabled") and _llm and hasattr(_llm, "rewrite"):
        try:
            final2 = _llm.rewrite(text=final, mood=CHAT_MOOD, timeout=int(merged.get("llm_timeout_seconds",12)),
                                  cpu_limit=int(merged.get("llm_max_cpu_percent",70)),
                                  models_priority=merged.get("llm_models_priority", []),
                                  base_url=merged.get("ollama_base_url",""),
                                  model_url=merged.get("llm_model_url",""),
                                  model_path=merged.get("llm_model_path",""),
                                  model_sha256=merged.get("llm_model_sha256",""),
                                  allow_profanity=bool(merged.get("personality_allow_profanity", False)))
            if final2: final = final2; used_llm = True
        except Exception as e:
            print(f"[bot] LLM rewrite failed: {e}")

    if BEAUTIFY_ENABLED and _beautify and hasattr(_beautify, "beautify_message"):
        try:
            final, extras = _beautify.beautify_message(title, final, mood=CHAT_MOOD)
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
        f"🔀 Proxy (Gotify/ntfy) — {'ACTIVE' if PROXY_ENABLED else 'OFF'}",
        f"🧠 DNS (Technitium) — {'ACTIVE' if TECHNITIUM_ENABLED else 'OFF'}",
        "",
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
# Standalone SSE intake (Jarvis Prime) + Dedupe + Workers
# ============================
import hashlib, threading, queue, aiohttp

_recent = {}
_recent_lock = asyncio.Lock()
_workq: "queue.Queue[tuple]" = queue.Queue()

def _dedupe_key_from_msg(msg: dict) -> str:
    mid = msg.get("id")
    if mid is not None:
        return f"id:{mid}"
    h = hashlib.sha1()
    h.update((msg.get("title","") + "|" + msg.get("body","") + "|" + str(msg.get("created_at",""))).encode("utf-8", "ignore"))
    return "h:"+h.hexdigest()

async def _mark_seen(k: str) -> None:
    async with _recent_lock:
        _recent[k] = time.time() + DEDUPE_TTL_SECONDS
        # GC
        now = time.time()
        for kk, exp in list(_recent.items()):
            if exp < now:
                _recent.pop(kk, None)

async def _is_seen(k: str) -> bool:
    async with _recent_lock:
        now = time.time()
        for kk, exp in list(_recent.items()):
            if exp < now:
                _recent.pop(kk, None)
        return k in _recent

def _enqueue(kind: str, text: str, msg: dict) -> None:
    try:
        _workq.put_nowait((kind, text, msg))
    except Exception:
        pass

async def _sse_consumer():
    url = f"{JARVIS_BASE}/api/stream"
    headers = {}
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=None) as resp:
                    if resp.status != 200:
                        print(f"[bot] SSE connect failed: {resp.status}")
                        await asyncio.sleep(2); continue
                    async for raw in resp.content:
                        try:
                            line = raw.decode("utf-8", "ignore").strip()
                            if not line.startswith("data: "): continue
                            data = json.loads(line[6:].strip())
                            if data.get("event") != "created": continue
                            mid = data.get("id")
                            if mid is None: continue
                            r = requests.get(f"{JARVIS_BASE}/api/messages/{mid}", timeout=6)
                            r.raise_for_status()
                            msg = r.json()
                            k = _dedupe_key_from_msg(msg)
                            if await _is_seen(k): 
                                continue
                            await _mark_seen(k)
                            title = msg.get("title","")
                            body  = msg.get("body","") or msg.get("message","")
                            text = f"{title} {body}".strip()
                            ncmd = normalize_cmd(extract_command_from(title, body))
                            if ncmd:
                                _enqueue("wake", ncmd, msg)
                            else:
                                _enqueue("other", text, msg)
                        except Exception as e:
                            # swallow parse errors, continue stream
                            pass
        except Exception as e:
            print(f"[bot] SSE error: {e}")
            await asyncio.sleep(2)

def _worker_loop():
    while True:
        try:
            kind, text, msg = _workq.get()
        except Exception:
            time.sleep(0.1); continue
        try:
            if kind == "wake":
                _handle_command(text)
            else:
                # fallback: LLM then beautify like ws path
                title = (msg.get("title") or "Notification")
                message = (msg.get("body") or msg.get("message") or "")
                final, extras, used_llm, used_beautify = _llm_then_beautify(title, message)
                send_message(title, final, priority=5, extras=extras)
        except Exception as e:
            print(f"[bot] worker error: {e}")
        finally:
            try: _workq.task_done()
            except Exception: pass
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
                    except Exception as e:
                        print(f"[Scheduler] digest error: {e}")
        except Exception as e:
            print(f"[Scheduler] loop error: {e}")
        await asyncio.sleep(60)
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
    # Start periodic digest
    asyncio.create_task(_digest_scheduler_loop())
    # Start SSE intake if enabled
    if BOT_INPUT_SSE:
        asyncio.create_task(_sse_consumer())
        # start worker threads
        for _ in range(max(1, WORKERS)):
            threading.Thread(target=_worker_loop, daemon=True).start()
    # Gotify listener loop (keep reconnecting) if enabled
    while True:
        try:
            if BOT_INPUT_GOTIFY:
                await listen()
            else:
                await asyncio.sleep(5)
        except Exception:
            await asyncio.sleep(3)

if __name__ == "__main__":
    main()

    main()
