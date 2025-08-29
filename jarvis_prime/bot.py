#!/usr/bin/env python3
# /app/bot.py — with Startup card + self-loop guard + pipeline send

import os
import json
import time
import asyncio
import requests
import websockets
import schedule
from typing import Optional, Tuple

VERSION = "1.0.5"
CONFIG_PATH = "/data/options.json"

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")
JARVIS_APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

GOTIFY_URL = os.getenv("GOTIFY_URL", "").rstrip("/")
GOTIFY_CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
GOTIFY_APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN", "")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# LLM settings
LLM_ENABLED = os.getenv("LLM_ENABLED", "false").lower() in ("1","true","yes")
LLM_TIMEOUT = int(os.getenv("llm_timeout_seconds", "5"))
LLM_CPU_LIMIT = int(os.getenv("llm_max_cpu_percent", "70"))
PERSONALITY_MOOD = os.getenv("personality_mood", os.getenv("CHAT_MOOD", "serious"))

# Feature flags from run.sh (some are lowercased there)
technitium_enabled = os.getenv("technitium_enabled", "true").lower() in ("1","true","yes")
uptimekuma_enabled = os.getenv("uptimekuma_enabled", "true").lower() in ("1","true","yes")
smtp_enabled = os.getenv("smtp_enabled", "true").lower() in ("1","true","yes")
proxy_enabled = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")

# Self-loop guard key
JARVIS_ORIGIN_KEY = "jarvis_origin"

# Optional modules (lazy import)
def _safe_import(name: str):
    try:
        return __import__(name)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Optional module '{name}' failed to import: {e}", flush=True)
        return None

m_chat = _safe_import("chat")
m_arr = _safe_import("arr")
m_weather = _safe_import("weather")
m_tech = _safe_import("technitium")
m_digest = _safe_import("digest")
m_kuma = _safe_import("uptimekuma")
m_aliases = _safe_import("aliases")
m_llm_client = _safe_import("llm_client")
m_llm_memory = _safe_import("llm_memory")
m_personality = _safe_import("personality")
m_personality_state = _safe_import("personality_state")
m_smtp = _safe_import("smtp_server")
m_proxy = _safe_import("proxy")
m_beautify = _safe_import("beautify")

# Gotify client
class GotifyClient:
    def __init__(self, url: str, app_token: str, client_token: str):
        self.url = url.rstrip("/")
        self.app_token = app_token.strip()
        self.client_token = client_token.strip()

    def post(self, title: str, message: str, priority: int = 5, extras: Optional[dict] = None):
        payload = {"title": title, "message": message, "priority": int(priority)}
        if extras: payload["extras"] = extras
        try:
            r = requests.post(f"{self.url}/message",
                              headers={"X-Gotify-Key": self.app_token},
                              json=payload, timeout=10)
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

def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def normalize_command(text: str) -> str:
    raw = (text or "").strip().lower()
    # aliases.py mapping if present
    if m_aliases and hasattr(m_aliases, "map_alias"):
        try:
            mapped = m_aliases.map_alias(raw)
            if mapped: return mapped
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ alias mapping failed: {e}", flush=True)
    if raw in ("dns","dns","dns"): return "dns"
    if raw in ("kuma","uptime","monitor"): return "kuma"
    if raw in ("weather","now","today","temp","temps"): return "weather"
    if raw in ("forecast","weekly","7day","7-day","7 day"): return "forecast"
    if raw in ("digest","summary"): return "digest"
    return raw

def _parse_inbound(data: dict) -> Tuple[str, str, int]:
    return data.get("title") or "", data.get("message") or "", int(data.get("priority") or 5)

# Pipeline send
from pipeline import process as pipeline_process

def send_message(title: str, text: str, priority: int = 5, image: str | None = None):
    """Beautify -> LLM -> Polish -> post (with self-loop guard + single prefix)."""
    try:
        mood = os.getenv("personality_mood", "serious")
        final_text, extras = pipeline_process(title or "", text or "", mood)

        # avoid stacking prefix
        post_title = (title or "").strip()
        bn = os.getenv("BOT_NAME", "Jarvis Prime")
        if not post_title.lower().startswith(f"{bn.lower()}:"):
            post_title = f"{bn}: {post_title}"

        payload_extras = {JARVIS_ORIGIN_KEY: True}
        img = image
        if not img:
            imgs = (extras or {}).get("images") or []
            if imgs: img = imgs[0]
        if img:
            payload_extras.update({
                "client::display": {"contentType": "text/markdown"},
                "client::notification": {"image": img},
            })

        requests.post(f"{GOTIFY_URL}/message",
                      headers={"X-Gotify-Key": GOTIFY_APP_TOKEN},
                      json={"title": post_title, "message": final_text,
                            "priority": int(priority), "extras": payload_extras},
                      timeout=10)
    except Exception as e:
        try:
            requests.post(f"{GOTIFY_URL}/message",
                          headers={"X-Gotify-Key": GOTIFY_APP_TOKEN},
                          json={"title": f"{BOT_NAME}: send_message error",
                                "message": f"{title}\n\n{e}",
                                "priority": 5, "extras": {JARVIS_ORIGIN_KEY: True}},
                          timeout=10)
        except Exception:
            pass

# Commands
def _try_call(mod, func_name: str, *args):
    if not mod or not hasattr(mod, func_name):
        return (None, f"function {func_name} not available")
    try:
        return (getattr(mod, func_name)(*args), None)
    except Exception as e:
        return (None, e)

def _handle_command(cmd: str, text: str, priority: int) -> bool:
    ncmd = normalize_command(cmd)

    if ncmd in ("weather","now","today","temp","temps"):
        out = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                out = m_weather.handle_weather_command("weather")
                if isinstance(out, tuple): out = out[0]
            except Exception as e:
                out = f"⚠️ Weather failed: {e}"
        send_message("Weather", out or "No data.")
        return True

    if ncmd in ("forecast","weekly","7day","7-day","7 day"):
        out = ""
        if m_weather and hasattr(m_weather, "handle_weather_command"):
            try:
                out = m_weather.handle_weather_command("forecast")
                if isinstance(out, tuple): out = out[0]
            except Exception as e:
                out = f"⚠️ Forecast failed: {e}"
        send_message("Forecast", out or "No data.")
        return True

    if ncmd == "dns":
        out, err = _try_call(m_tech, "handle_dns_command", "dns")
        send_message("DNS", (out or f"⚠️ DNS failed: {err}") if err else (out or "No data."))
        return True

    if ncmd in ("kuma","uptime","monitor"):
        out, err = _try_call(m_kuma, "handle_kuma_command", "kuma")
        send_message("Uptime", (out or f"⚠️ Kuma failed: {err}") if err else (out or "No data."))
        return True

    if ncmd in ("digest","summary"):
        out, err = _try_call(m_digest, "run_digest")
        send_message("Digest", (out or f"⚠️ Digest failed: {err}") if err else (out or "No data."))
        return True

    return False

# Scheduler jobs
def _job_weather():
    if not m_weather: return
    try:
        out = m_weather.handle_weather_command("weather")
        if isinstance(out, tuple): out = out[0]
        send_message("Weather", out or "No data.")
    except Exception as e:
        send_message("Weather", f"⚠️ Weather job failed: {e}")

def _job_forecast():
    if not m_weather: return
    try:
        out = m_weather.handle_weather_command("forecast")
        if isinstance(out, tuple): out = out[0]
        send_message("Forecast", out or "No data.")
    except Exception as e:
        send_message("Forecast", f"⚠️ Forecast job failed: {e}")

def _job_digest():
    if not m_digest: return
    try:
        out = m_digest.run_digest()
        send_message("Digest", out or "No data.")
    except Exception as e:
        send_message("Digest", f"⚠️ Digest job failed: {e}")

def _job_radarr():
    if not m_arr or not hasattr(m_arr, "run_radarr"): return
    try:
        out = m_arr.run_radarr()
        send_message("Radarr", out or "No data.")
    except Exception as e:
        send_message("Radarr", f"⚠️ Radarr job failed: {e}")

def _job_sonarr():
    if not m_arr or not hasattr(m_arr, "run_sonarr"): return
    try:
        out = m_arr.run_sonarr()
        send_message("Sonarr", out or "No data.")
    except Exception as e:
        send_message("Sonarr", f"⚠️ Sonarr job failed: {e}")

# Scheduling + WS
def setup_schedules():
    cfg = _read_json(CONFIG_PATH)

    if cfg.get("weather_enabled", True):
        t = cfg.get("weather_time", "07:00")
        try:
            schedule.every().day.at(t).do(_job_weather)
            print(f"[{BOT_NAME}] 🕑 Weather scheduled daily at {t}", flush=True)
        except schedule.ScheduleValueError:
            print(f"[{BOT_NAME}] ⚠️ Bad weather_time '{t}', skipping.", flush=True)

    if cfg.get("digest_enabled", True):
        t = cfg.get("digest_time", "08:00")
        try:
            schedule.every().day.at(t).do(_job_digest)
            print(f"[{BOT_NAME}] 🕑 Digest scheduled daily at {t}", flush=True)
        except schedule.ScheduleValueError:
            print(f"[{BOT_NAME}] ⚠️ Bad digest_time '{t}', skipping.", flush=True)

    if cfg.get("radarr_enabled", False):
        t = cfg.get("radarr_time", "07:30")
        try:
            schedule.every().day.at(t).do(_job_radarr)
            print(f"[{BOT_NAME}] 🕑 Radarr scheduled daily at {t}", flush=True)
        except schedule.ScheduleValueError:
            print(f"[{BOT_NAME}] ⚠️ Bad radarr_time '{t}', skipping.", flush=True)

    if cfg.get("sonarr_enabled", False):
        t = cfg.get("sonarr_time", "07:30")
        try:
            schedule.every().day.at(t).do(_job_sonarr)
            print(f"[{BOT_NAME}] 🕑 Sonarr scheduled daily at {t}", flush=True)
        except schedule.ScheduleValueError:
            print(f"[{BOT_NAME}] ⚠️ Bad sonarr_time '{t}', skipping.", flush=True)

def run_schedulers_forever():
    while True:
        schedule.run_pending()
        time.sleep(1)

async def on_gotify_message(data: dict):
    # Ignore our own posts
    extras = data.get("extras") or {}
    if isinstance(extras, dict) and extras.get(JARVIS_ORIGIN_KEY): return

    title, message, priority = _parse_inbound(data)
    raw = (message or "").strip()

    # Try command
    toks = raw.split(None, 1)
    cmd = toks[0] if toks else ""
    rest = toks[1] if len(toks) > 1 else ""

    if cmd and _handle_command(cmd, rest, priority): return

    # Route through chat if present, else pipeline passthrough
    if m_chat and hasattr(m_chat, "handle_chat"):
        try:
            out = m_chat.handle_chat(title, raw)
            send_message(title, out or raw, priority=priority)
        except Exception as e:
            send_message(title, f"{raw}\n\n⚠️ Chat failed: {e}", priority=priority)
    else:
        send_message(title, raw, priority=priority)

async def ws_loop():
    while True:
        try:
            await gotify.ws_listen(on_gotify_message)
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ WS loop error: {e}; reconnecting in 3s", flush=True)
            await asyncio.sleep(3)

def start_background_schedulers():
    import threading
    th = threading.Thread(target=run_schedulers_forever, daemon=True)
    th.start()

def prefetch_llm():
    if not LLM_ENABLED or not m_llm_client or not hasattr(m_llm_client, "rewrite"): return
    cfg = _read_json(CONFIG_PATH)
    try:
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

def build_startup_text() -> str:
    cfg = _read_json(CONFIG_PATH)
    def onoff(val: bool) -> str: return "ACTIVE" if val else "OFF"
    lines = []
    lines.append("Prime Neural Boot")
    lines.append(f"Engine: Neural Core — {'ONLINE' if LLM_ENABLED else 'OFFLINE'}")
    lines.append(f"Mood: {PERSONALITY_MOOD}")
    lines.append("")
    lines.append("Modules:")
    lines.append(f"📚 Radarr — {onoff(cfg.get('radarr_enabled', False))}")
    lines.append(f"📺 Sonarr — {onoff(cfg.get('sonarr_enabled', False))}")
    lines.append(f"🌤️ Weather — {onoff(cfg.get('weather_enabled', True))}")
    lines.append(f"🧾 Digest — {onoff(cfg.get('digest_enabled', True))}")
    lines.append(f"💬 Chat — {onoff(bool(m_chat))}")
    lines.append(f"🧪 Uptime Kuma — {onoff(uptimekuma_enabled)}")
    lines.append(f"📮 SMTP Intake — {onoff(smtp_enabled)}")
    lines.append(f"🛰️ Proxy — {onoff(proxy_enabled)}")
    lines.append(f"🧠 DNS (Technitium) — {onoff(technitium_enabled)}")
    lines.append("")
    lines.append("Status: Neural Core warming up..." if LLM_ENABLED else "Status: Minimal mode.")
    return "\n".join(lines)

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

    # Prefetch and schedules
    prefetch_llm()
    setup_schedules()
    start_background_schedulers()

    # One-time Startup card
    try:
        send_message("Startup", build_startup_text(), priority=5)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Startup card failed: {e}", flush=True)

    # Modern asyncio runner
    asyncio.run(ws_loop())

if __name__ == "__main__":
    main()
