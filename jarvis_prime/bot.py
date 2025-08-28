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
# Constants and Utility Functions
# -----------------------------
VERSION = "1.0.4"
CONFIG_PATH = "/data/options.json"
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")
JARVIS_APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

GOTIFY_URL = os.getenv("GOTIFY_URL", "")
GOTIFY_CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
GOTIFY_APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN", "")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# LLM Settings
LLM_ENABLED = os.getenv("LLM_ENABLED", "false").lower() in ("1","true","yes")
LLM_TIMEOUT = int(os.getenv("llm_timeout_seconds", "5"))
LLM_CPU_LIMIT = int(os.getenv("llm_max_cpu_percent", "70"))
PERSONALITY_MOOD = os.getenv("personality_mood", os.getenv("CHAT_MOOD", "serious"))

# Weather settings (read from /data/options.json inside module where needed)
WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "true").lower() in ("1","true","yes")

# External services
technitium_enabled = os.getenv("technitium_enabled", "true").lower() in ("1","true","yes")
uptimekuma_enabled = os.getenv("uptimekuma_enabled", "true").lower() in ("1","true","yes")

# -----------------------------
# Optional modules, imported lazily
# -----------------------------
m_chat = None
m_arr = None
m_weather = None
m_tech = None
m_digest = None
m_kuma = None
m_aliases = None
m_llm_client = None
m_llm_memory = None
m_personality = None
m_personality_state = None
m_smtp = None
m_proxy = None
m_beautify = None

def _safe_import(mod_name):
    try:
        return __import__(mod_name)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Optional module '{mod_name}' failed to import: {e}", flush=True)
        return None

def load_modules_once():
    global m_chat, m_arr, m_weather, m_tech, m_digest, m_kuma, m_aliases
    global m_llm_client, m_llm_memory, m_personality, m_personality_state
    global m_smtp, m_proxy, m_beautify

    if m_chat is None:
        m_chat = _safe_import("chat")
    if m_arr is None:
        m_arr = _safe_import("arr")
    if m_weather is None:
        m_weather = _safe_import("weather")
    if m_tech is None:
        m_tech = _safe_import("technitium")
    if m_digest is None:
        m_digest = _safe_import("digest")
    if m_kuma is None:
        m_kuma = _safe_import("uptimekuma")
    if m_aliases is None:
        m_aliases = _safe_import("aliases")
    if m_llm_client is None:
        m_llm_client = _safe_import("llm_client")
    if m_llm_memory is None:
        m_llm_memory = _safe_import("llm_memory")
    if m_personality is None:
        m_personality = _safe_import("personality")
    if m_personality_state is None:
        m_personality_state = _safe_import("personality_state")
    if m_smtp is None:
        m_smtp = _safe_import("smtp_server")
    if m_proxy is None:
        m_proxy = _safe_import("proxy")
    if m_beautify is None:
        m_beautify = _safe_import("beautify")

# ensure modules loaded
load_modules_once()

# -----------------------------
# Gotify client
# -----------------------------
class GotifyClient:
    def __init__(self, url: str, app_token: str, client_token: str):
        self.url = url.rstrip("/")
        self.app_token = app_token.strip()
        self.client_token = client_token.strip()

    def post(self, title: str, message: str, priority: int = 5, extras: Optional[dict] = None):
        payload = {
            "title": title,
            "message": message,
            "priority": priority,
        }
        if extras:
            payload["extras"] = extras
        try:
            r = requests.post(
                f"{self.url}/message",
                headers={"X-Gotify-Key": self.app_token},
                json=payload,
                timeout=10,
            )
            if not r.ok:
                print(f"[{BOT_NAME}] ⚠️ Gotify post failed {r.status_code}: {r.text}", flush=True)
            return r
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Gotify post exception: {e}", flush=True)
            return None

    async def ws_listen(self, on_message):
        ws_url = self.url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/stream?token={self.client_token}"
        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=30) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    await on_message(data)
                except Exception as e:
                    print(f"[{BOT_NAME}] ⚠️ WS message parse error: {e}", flush=True)

gotify = GotifyClient(GOTIFY_URL, GOTIFY_APP_TOKEN, GOTIFY_CLIENT_TOKEN)

# -----------------------------
# Helpers
# -----------------------------
def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _normalize_title(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return BOT_NAME
    return t

def normalize_command(text: str) -> str:
    """
    Normalize a command string, apply alias mapping if present.
    """
    raw = (text or "").strip()
    lower = raw.lower()

    # Use aliases.py if available
    mapped = None
    if m_aliases and hasattr(m_aliases, "map_alias"):
        try:
            mapped = m_aliases.map_alias(lower)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ alias mapping failed: {e}", flush=True)
    if mapped:
        return mapped

    # Default simplistic normalization
    if lower in ("dns", "DNS", "Dns"):
        return "dns"
    if lower in ("kuma","uptime","monitor"):
        return "kuma"
    if lower in ("weather","now","today","temp","temps"):
        return "weather"
    if lower in ("forecast","weekly","7day","7-day","7 day"):
        return "forecast"
    if lower in ("digest","summary"):
        return "digest"
    return lower

def _parse_inbound(data: dict) -> Tuple[str, str, int]:
    """
    Parse inbound Gotify message into (title, message, priority).
    """
    title = data.get("title") or ""
    message = data.get("message") or ""
    priority = int(data.get("priority") or 5)
    return title, message, priority

def _send_raw(title: str, text: str, priority: int = 5, extras: Optional[dict] = None):
    gotify.post(title, text, priority, extras)

# -----------------------------
# Pipeline-based send
# -----------------------------
from pipeline import process as pipeline_process

def send_message(title: str, text: str, priority: int = 5, image: str | None = None):
    """Single choke point: Beautify -> LLM -> Polish -> Gotify."""
    import os
    import requests
    try:
        mood = os.getenv("personality_mood", "serious")
        final_text, extras = pipeline_process(title or "", text or "", mood)

        img = image
        # If you don't want auto-attach, comment the next block
        if not img:
            imgs = (extras or {}).get("images") or []
            if imgs:
                img = imgs[0]

        payload = {
            "title": f"{os.getenv('BOT_NAME', 'Jarvis Prime')}: {title}",
            "message": final_text,
            "priority": int(priority),
        }
        if img:
            payload["extras"] = {
                "client::display": {"contentType": "text/markdown"},
                "client::notification": {"image": img},
            }

        requests.post(
            os.getenv("GOTIFY_URL", "").rstrip("/") + "/message",
            headers={"X-Gotify-Key": os.getenv("GOTIFY_APP_TOKEN", "")},
            json=payload,
            timeout=10,
        )
    except Exception as e:
        # last-resort post so you still see errors
        try:
            err_payload = {
                "title": f"{os.getenv('BOT_NAME', 'Jarvis Prime')}: send_message error",
                "message": f"{title}\n\n{e}",
                "priority": 5,
            }
            requests.post(
                os.getenv("GOTIFY_URL", "").rstrip("/") + "/message",
                headers={"X-Gotify-Key": os.getenv("GOTIFY_APP_TOKEN", "")},
                json=err_payload,
                timeout=10,
            )
        except Exception:
            pass

# -----------------------------
# Command Handlers
# -----------------------------
def _try_call(mod, func_name: str, *args):
    if not mod:
        return ("module not loaded", None)
    if not hasattr(mod, func_name):
        return (f"function {func_name} not found", None)
    try:
        res = getattr(mod, func_name)(*args)
        return (res, None)
    except Exception as e:
        return (None, e)

def _handle_command(cmd: str, text: str, priority: int):
    """
    Handle normalized command tokens, then return True if handled.
    """
    ncmd = normalize_command(cmd)

    # ----- WEATHER -----
    if ncmd in ("weather", "now", "today", "temp", "temps"):
        text_out = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text_out = m_weather.handle_weather_command("weather")
                if isinstance(text_out, tuple):
                    text_out = text_out[0]
            except Exception as e:
                text_out = f"⚠️ Weather failed: {e}"
        send_message("Weather", text_out or "No data.")
        return True

    if ncmd in ("forecast", "weekly", "7day", "7-day", "7 day"):
        text_out = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                text_out = m_weather.handle_weather_command("forecast")
                if isinstance(text_out, tuple):
                    text_out = text_out[0]
            except Exception as e:
                text_out = f"⚠️ Forecast failed: {e}"
        send_message("Forecast", text_out or "No data.")
        return True

    # ----- DNS -----
    if ncmd in ("dns",):
        text_out, err = _try_call(m_tech, "handle_dns_command", "dns")
        if err:
            send_message("DNS", f"⚠️ DNS failed: {err}")
        else:
            # handle_dns_command returns a string
            send_message("DNS", text_out or "No data.")
        return True

    # ----- KUMA (Uptime) -----
    if ncmd in ("kuma", "uptime", "monitor"):
        text_out, err = _try_call(m_kuma, "handle_kuma_command", "kuma")
        if err:
            send_message("Uptime", f"⚠️ Kuma failed: {err}")
        else:
            send_message("Uptime", text_out or "No data.")
        return True

    # ----- DIGEST -----
    if ncmd in ("digest", "summary"):
        text_out, err = _try_call(m_digest, "run_digest")
        if err:
            send_message("Digest", f"⚠️ Digest failed: {err}")
        else:
            send_message("Digest", text_out or "No data.")
        return True

    return False

# -----------------------------
# Scheduler jobs
# -----------------------------
def _job_weather():
    if not WEATHER_ENABLED or not m_weather:
        return
    try:
        out = m_weather.handle_weather_command("weather")
        if isinstance(out, tuple):
            out = out[0]
        send_message("Weather", out or "No data.")
    except Exception as e:
        send_message("Weather", f"⚠️ Weather job failed: {e}")

def _job_forecast():
    if not WEATHER_ENABLED or not m_weather:
        return
    try:
        out = m_weather.handle_weather_command("forecast")
        if isinstance(out, tuple):
            out = out[0]
        send_message("Forecast", out or "No data.")
    except Exception as e:
        send_message("Forecast", f"⚠️ Forecast job failed: {e}")

def _job_digest():
    if not m_digest:
        return
    try:
        out = m_digest.run_digest()
        send_message("Digest", out or "No data.")
    except Exception as e:
        send_message("Digest", f"⚠️ Digest job failed: {e}")

def _job_radarr():
    if not m_arr or not hasattr(m_arr, "run_radarr"):
        return
    try:
        out = m_arr.run_radarr()
        send_message("Radarr", out or "No data.")
    except Exception as e:
        send_message("Radarr", f"⚠️ Radarr job failed: {e}")

def _job_sonarr():
    if not m_arr or not hasattr(m_arr, "run_sonarr"):
        return
    try:
        out = m_arr.run_sonarr()
        send_message("Sonarr", out or "No data.")
    except Exception as e:
        send_message("Sonarr", f"⚠️ Sonarr job failed: {e}")

# -----------------------------
# Memory cleanup job
# -----------------------------
def _cleanup_old_messages():
    # Here you could optionally trim memory or logs if you store them locally.
    pass

# -----------------------------
# Message processing
# -----------------------------
async def on_gotify_message(data: dict):
    """
    Callback for Gotify websocket inbound messages.
    """
    # The message structure:
    # {'appid':..., 'date':..., 'id':..., 'message':..., 'priority':..., 'title':....}
    title, message, priority = _parse_inbound(data)

    # If message starts with jarvis prefix: e.g. "jarvis dns"
    # We'll parse out a potential command from the message's start.
    raw = (message or "").strip()
    tokens = raw.split(None, 1)
    cmd = tokens[0] if tokens else ""
    rest = tokens[1] if len(tokens) > 1 else ""

    # Attempt to handle command
    handled = False
    if cmd:
        handled = _handle_command(cmd, rest, priority)

    # If not handled as command, route as generic "chat" or pass through pipeline
    if not handled:
        # if chat module is enabled
        if m_chat and hasattr(m_chat, "handle_chat"):
            try:
                out = m_chat.handle_chat(title, raw)
                send_message(title, out or raw, priority=priority)
            except Exception as e:
                send_message(title, f"{raw}\n\n⚠️ Chat failed: {e}", priority=priority)
        else:
            # fallback: just send pipeline processed
            send_message(title, raw, priority=priority)

# -----------------------------
# Schedulers & main loop
# -----------------------------
def setup_schedules():
    cfg = _read_json(CONFIG_PATH)

    # Daily weather time
    if cfg.get("weather_enabled", True):
        t = cfg.get("weather_time", "07:00")
        try:
            schedule.every().day.at(t).do(_job_weather)
            print(f"[{BOT_NAME}] 🕑 Weather scheduled daily at {t}", flush=True)
        except schedule.ScheduleValueError:
            print(f"[{BOT_NAME}] ⚠️ Bad weather_time '{t}', skipping schedule.", flush=True)

    # Daily digest
    if cfg.get("digest_enabled", True):
        t = cfg.get("digest_time", "08:00")
        try:
            schedule.every().day.at(t).do(_job_digest)
            print(f"[{BOT_NAME}] 🕑 Digest scheduled daily at {t}", flush=True)
        except schedule.ScheduleValueError:
            print(f"[{BOT_NAME}] ⚠️ Bad digest_time '{t}', skipping schedule.", flush=True)

    # Radarr
    if cfg.get("radarr_enabled", False):
        t = cfg.get("radarr_time", "07:30")
        try:
            schedule.every().day.at(t).do(_job_radarr)
            print(f"[{BOT_NAME}] 🕑 Radarr scheduled daily at {t}", flush=True)
        except schedule.ScheduleValueError:
            print(f"[{BOT_NAME}] ⚠️ Bad radarr_time '{t}', skipping schedule.", flush=True)

    # Sonarr
    if cfg.get("sonarr_enabled", False):
        t = cfg.get("sonarr_time", "07:30")
        try:
            schedule.every().day.at(t).do(_job_sonarr)
            print(f"[{BOT_NAME}] 🕑 Sonarr scheduled daily at {t}", flush=True)
        except schedule.ScheduleValueError:
            print(f"[{BOT_NAME}] ⚠️ Bad sonarr_time '{t}', skipping schedule.", flush=True)

def run_schedulers_forever():
    while True:
        schedule.run_pending()
        time.sleep(1)

async def ws_loop():
    while True:
        try:
            await gotify.ws_listen(on_gotify_message)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ WS loop error: {e}; reconnecting in 3s", flush=True)
            await asyncio.sleep(3)

def start_background_schedulers():
    # Optionally start the scheduler in a subprocess/thread
    import threading
    th = threading.Thread(target=run_schedulers_forever, daemon=True)
    th.start()

def prefetch_llm():
    if not LLM_ENABLED:
        return
    cfg = _read_json(CONFIG_PATH)
    try:
        if m_llm_client and hasattr(m_llm_client, "rewrite"):
            print(f"[{BOT_NAME}] 🔮 Prefetching LLM model...", flush=True)
            _ = m_llm_client.rewrite(
                text="(prefetch)",
                mood=cfg.get("personality_mood","serious"),
                timeout=int(cfg.get("llm_timeout_seconds",5)),
                cpu_limit=int(cfg.get("llm_max_cpu_percent",70)),
                models_priority=[],
                base_url=cfg.get("llm_ollama_base_url",""),
                model_url=cfg.get("llm_model_url",""),
                model_path=cfg.get("llm_model_path",""),
                model_sha256=cfg.get("llm_model_sha256",""),
            )
            print(f"[{BOT_NAME}] 🧠 Prefetch complete", flush=True)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Prefetch failed: {e}", flush=True)

def main():
    print("──────────────────────────────────────────────", flush=True)
    print(f"🧠 {BOT_NAME} {BOT_ICON}", flush=True)
    print("⚡ Boot sequence initiated...", flush=True)
    print("   → Personalities loaded", flush=True)
    print("   → Memory core mounted", flush=True)
    print("   → Network bridges linked", flush=True)
    print(f"   → LLM: {'enabled' if LLM_ENABLED else 'disabled'}", flush=True)
    print("🚀 Systems online — Jarvis is awake!", flush=True)
    print("──────────────────────────────────────────────", flush=True)

    prefetch_llm()
    setup_schedules()
    start_background_schedulers()

    # Run websocket listener
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(ws_loop())
    finally:
        loop.close()

if __name__ == "__main__":
    main()
