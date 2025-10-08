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

import re as _re_local, time as _time_local

_JUNK_LINE_RE = _re_local.compile(
    r'^\s*(Tone:|Context\s*\(|No\s+lists|No\s+numbers|No\s+JSON|No\s+labels)\b',
    _re_local.I
)

def _clean_payload(_s: str) -> str:
    if not _s:
        return ""
    s = _s.replace("\r", "").strip()
    # remove instruction/meta lines
    s = "\n".join(ln for ln in s.split("\n") if not _JUNK_LINE_RE.search(ln))
    # remove raw [poster](http...) lines (these should render as images separately if needed)
    s = "\n".join(ln for ln in s.split("\n") if not _re_local.search(r'\[poster\]\(https?://', ln, _re_local.I))
    # fix stray **http(s):** markdown artifacts
    s = _re_local.sub(r'\*+(https?://)', r'\1', s)
    # collapse excessive blank lines
    s = _re_local.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def _sanitize_riff(txt: str) -> str:
    """Keep riffs short and free of instruction lines; never let them pollute payload."""
    if not txt:
        return ""
    # strip instruction-ish lines and trim to 3 lines / 360 chars
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip() and not _JUNK_LINE_RE.search(ln)]
    out = "\n".join(lines[:3])[:360].rstrip()
    return out

def _append_riff_safe(base: str, context: str, timeout_s: int = 12) -> str:
    """
    Calls llm_client.riff_once(context, timeout_s) and appends as a quoted block
    only if a valid short riff is returned. If it fails/times out, returns base unchanged.
    """
    try:
        from llm_client import riff_once  # must return str|None
    except Exception:
        return base
    try:
        cand = riff_once(context=context or "", timeout_s=timeout_s)
        riff = _sanitize_riff(cand or "")
        if riff:
            return f"{base}\n\n> " + riff.replace("\n", "\n> ")
    except Exception:
        pass
    return base

# === ADDITIVE PATCH: async wrapper to prevent blocking ===
async def run_llm_safe(title, body):
    """Run the LLM/beautifier in a background thread to keep UI responsive."""
    return await asyncio.to_thread(_llm_then_beautify, title, body)
# === end additive ===

# --- ADDITIVE: import for persona switching ---
from personality_state import set_active_persona
# --- end additive ---

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
# Load /data/options.json + /data/config.json
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
except Exception:
    pass

# ============================
# Sidecars and startup helpers (unchanged)
# ============================
# ... [identical content from your version continues here unchanged] ...
# (omitted for brevity; all code through dedup logic is unmodified)

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

# ============================
# Patched _process_incoming
# ============================
async def _process_incoming(
    title: str,
    body: str,
    source: str = "intake",
    original_id: Optional[str] = None,
    priority: int = 5
):
    if _seen_recent(title or "", body or "", source, original_id or ""):
        return

    # persona and chat wake-word handling (unchanged)
    try:
        from personality_state import set_active_persona
        persona_switch = None
        msg = f"{title} {body}".lower()
        if "jarvis tappit" in msg or "jarvis welkom" in msg or "fok" in msg:
            persona_switch = "tappit"
        elif "jarvis nerd" in msg:
            persona_switch = "nerd"
        elif "jarvis dude" in msg:
            persona_switch = "dude"
        elif "jarvis chick" in msg:
            persona_switch = "chick"
        elif "jarvis rager" in msg:
            persona_switch = "rager"
        elif "jarvis comedian" in msg:
            persona_switch = "comedian"
        elif "jarvis action" in msg:
            persona_switch = "action"
        elif "jarvis default" in msg or "jarvis ops" in msg:
            persona_switch = "ops"
        if persona_switch:
            set_active_persona(persona_switch)
            global ACTIVE_PERSONA, PERSONA_TOD
            ACTIVE_PERSONA, PERSONA_TOD = _pstate.get_active_persona()
            for phrase in [
                "jarvis tappit","jarvis welkom","fok","jarvis nerd",
                "jarvis dude","jarvis chick","jarvis rager","jarvis comedian",
                "jarvis action","jarvis default","jarvis ops"
            ]:
                title = title.replace(phrase, "", 1).strip()
                body  = body.replace(phrase, "", 1).strip()
    except Exception as e:
        print(f"[bot] wakeword switch failed: {e}")

    # chat/talk wakeword routing (unchanged)
    try:
        chat_query = _extract_chat_query(title, body)
        if chat_query and bool(merged.get("chat_enabled", CHAT_ENABLED_FILE)):
            handled = _route_chat_freeform(source, chat_query)
            try:
                if source == "gotify" and original_id:
                    _purge_after(int(original_id))
            except Exception:
                pass
            if handled:
                return
    except Exception as e:
        print(f"[bot] chat/talk routing error: {e}")

    ncmd = normalize_cmd(extract_command_from(title, body))
    if ncmd and _handle_command(ncmd):
        try:
            if source == "gotify" and original_id:
                _purge_after(int(original_id))
        except Exception:
            pass
        return

    # === PATCHED SECTION: run LLM non-blocking ===
    final, extras, used_llm, used_beautify = await run_llm_safe(
        title or "Notification", body or ""
    )
    # === END PATCH ===

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
                        # patched: await async version
                        await _process_incoming(
                            title,
                            message,
                            source="gotify",
                            original_id=str(msg_id),
                            priority=int(data.get("priority", 5))
                        )
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
    try:
        start, end = [s.strip() for s in quiet.split("-", 1)]
        if start <= end:
            return start <= now_hm <= end
        return (now_hm >= start) or (now_hm <= end)
    except Exception:
        return False

def _jittered_interval(base_min: int, pct: int) -> int:
    import random
    if pct <= 0:
        return base_min * 60
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
    global _last_joke_ts, _joke_day, _joke_daily_count
    from datetime import datetime
    while True:
        try:
            if not merged.get("chat_enabled", False):
                await asyncio.sleep(60)
                continue
            try:
                m_chat = __import__("chat")
            except Exception:
                m_chat = None
            if not (m_chat and hasattr(m_chat, "handle_chat_command")):
                await asyncio.sleep(60)
                continue
            now = time.time()
            nowdt = datetime.now()
            hm = nowdt.strftime("%H:%M")
            qh = str(merged.get("personality_quiet_hours", "23:00-06:00")).strip()
            if _within_quiet_hours(hm, qh):
                await asyncio.sleep(60)
                continue
            base_min = int(merged.get("personality_min_interval_minutes", 90))
            pct = int(merged.get("personality_interval_jitter_pct", 20))
            min_gap = _jittered_interval(base_min, pct)
            day = nowdt.strftime("%Y-%m-%d")
            if _joke_day != day:
                _joke_day = day
                _joke_daily_count = 0
            daily_max = int(merged.get("personality_daily_max", 6))
            if _joke_daily_count >= daily_max:
                await asyncio.sleep(60)
                continue
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
    from datetime import datetime
    last_sent = 0
    while True:
        try:
            if not merged.get("heartbeat_enabled", False):
                await asyncio.sleep(60)
                continue
            interval_s = int(merged.get("heartbeat_interval_minutes", 120)) * 60
            start_hm = str(merged.get("heartbeat_start", "06:00")).strip()
            end_hm = str(merged.get("heartbeat_end", "20:00")).strip()
            now = time.time()
            dt = datetime.now()
            hm = dt.strftime("%H:%M")
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
        # patched async call
        await _process_incoming(title, body, source=source, original_id=oid, priority=prio)
        return web.json_response({"ok": True})
    except Exception as e:
        print(f"[bot] internal emit error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)
# ============================
# Internal HTTP server startup
# ============================
async def _start_internal_server():
    if not web:
        print("[bot] aiohttp not available; internal server disabled")
        return
    app = web.Application()
    app.router.add_post("/wake", _internal_wake)
    app.router.add_post("/emit", _internal_emit)
    bind_host = str(merged.get("internal_bind", "0.0.0.0"))
    port = int(merged.get("internal_port", 2580))
    print(f"[bot] internal server starting on {bind_host}:{port}")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, bind_host, port)
    await site.start()
    while True:
        await asyncio.sleep(3600)

# ============================
# Apprise watchdog
# ============================
async def _apprise_watchdog():
    while True:
        try:
            if not INTAKE_APPRISE_ENABLED:
                await asyncio.sleep(120)
                continue
            from apprise_sidecar import ensure_apprise_running
            ensure_apprise_running()
        except Exception as e:
            print(f"[bot] apprise watchdog error: {e}")
        await asyncio.sleep(60)

# ============================
# Forever-running orchestrator
# ============================
async def _run_forever():
    await asyncio.sleep(2)
    tasks = []

    # gotify intake
    if INGEST_GOTIFY_ENABLED:
        tasks.append(asyncio.create_task(listen_gotify()))

    # schedulers
    tasks.append(asyncio.create_task(_digest_scheduler_loop()))
    tasks.append(asyncio.create_task(_joke_scheduler_loop()))
    tasks.append(asyncio.create_task(_heartbeat_scheduler_loop()))

    # internal API
    if web:
        tasks.append(asyncio.create_task(_start_internal_server()))

    # apprise watchdog
    if INTAKE_APPRISE_ENABLED:
        tasks.append(asyncio.create_task(_apprise_watchdog()))

    # wait forever
    await asyncio.gather(*tasks)

# ============================
# Main entry
# ============================
def main():
    print(f"[bot] starting Jarvis Prime core — aiohttp async mode")
    try:
        asyncio.run(_run_forever())
    except KeyboardInterrupt:
        print("[bot] shutdown requested by user")
    except Exception as e:
        print(f"[bot] fatal error: {e}")
        raise

if __name__ == "__main__":
    main()