# /app/bot.py
import os, json, time, asyncio, re, requests, websockets, schedule
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

# -----------------------------
# Environment / options
# -----------------------------
CONFIG_PATH = "/data/options.json"
FALLBACK_CONFIG_PATH = "/data/config.json"

def _load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# env defaults (run.sh exports most of these)
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL", "")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN", "")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN", "")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")

# feature toggles (env)
RADARR_ENABLED = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")
SMTP_ENABLED = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")
PROXY_ENABLED = os.getenv("proxy_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")

# LLM
LLM_ENABLED = os.getenv("llm_enabled", "true").lower() in ("1","true","yes")
LLM_TIMEOUT_SECONDS = int(os.getenv("llm_timeout_seconds", "5"))
LLM_MAX_CPU_PERCENT = int(os.getenv("llm_max_cpu_percent", "70"))
LLM_MEMORY_ENABLED = os.getenv("llm_memory_enabled", "true").lower() in ("1","true","yes")
PERSONALITY_PERSISTENT = os.getenv("personality_persistent", "true").lower() in ("1","true","yes")
LLM_MODEL_PATH = os.getenv("llm_model_path", "/share/jarvis_prime/models/tinyllama-1.1b-chat.Q4_K_M.gguf")

# Mood
CHAT_MOOD = os.getenv("personality_mood", "serious")

# merge with options.json (takes precedence)
merged = {**_load_json(FALLBACK_CONFIG_PATH), **_load_json(CONFIG_PATH)}
def _m(key, default=None): return merged.get(key, default)

BOT_NAME = _m("bot_name", BOT_NAME)
BOT_ICON = _m("bot_icon", BOT_ICON)
GOTIFY_URL = _m("gotify_url", GOTIFY_URL)
CLIENT_TOKEN = _m("gotify_client_token", CLIENT_TOKEN)
APP_TOKEN = _m("gotify_app_token", APP_TOKEN)
APP_NAME = _m("jarvis_app_name", APP_NAME)

RETENTION_HOURS = int(_m("retention_hours", RETENTION_HOURS))
BEAUTIFY_ENABLED = bool(_m("beautify_enabled", BEAUTIFY_ENABLED))
SILENT_REPOST = bool(_m("silent_repost", SILENT_REPOST))

RADARR_ENABLED = bool(_m("radarr_enabled", RADARR_ENABLED))
SONARR_ENABLED = bool(_m("sonarr_enabled", SONARR_ENABLED))
WEATHER_ENABLED = bool(_m("weather_enabled", WEATHER_ENABLED))
TECHNITIUM_ENABLED = bool(_m("technitium_enabled", TECHNITIUM_ENABLED))
KUMA_ENABLED = bool(_m("uptimekuma_enabled", KUMA_ENABLED))
SMTP_ENABLED = bool(_m("smtp_enabled", SMTP_ENABLED))
PROXY_ENABLED = bool(_m("proxy_enabled", PROXY_ENABLED))
CHAT_ENABLED = bool(_m("chat_enabled", CHAT_ENABLED))
DIGEST_ENABLED = bool(_m("digest_enabled", DIGEST_ENABLED))

LLM_ENABLED = bool(_m("llm_enabled", LLM_ENABLED))
LLM_TIMEOUT_SECONDS = int(_m("llm_timeout_seconds", LLM_TIMEOUT_SECONDS))
LLM_MAX_CPU_PERCENT = int(_m("llm_max_cpu_percent", LLM_MAX_CPU_PERCENT))
LLM_MEMORY_ENABLED = bool(_m("llm_memory_enabled", LLM_MEMORY_ENABLED))
PERSONALITY_PERSISTENT = bool(_m("personality_persistent", PERSONALITY_PERSISTENT))
LLM_MODEL_PATH = _m("llm_model_path", LLM_MODEL_PATH)
CHAT_MOOD = _m("personality_mood", CHAT_MOOD)

# -----------------------------
# Dynamic module loading
# -----------------------------
def try_load(name: str, label: str):
    try:
        import importlib.util as imp
        spec = imp.spec_from_file_location(name, f"/app/{name}.py")
        if spec and spec.loader:
            mod = imp.module_from_spec(spec)
            spec.loader.exec_module(mod)
            print(f"[{BOT_NAME}] ✅ {label} loaded")
            return mod
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ {label} not loaded: {e}")
    return None

_personality = try_load("personality", "personality.py")
_beautify = try_load("beautify", "beautify.py")
_llm = try_load("llm_client", "llm_client.py")
_llm_mem = try_load("llm_memory", "llm_memory.py")
_aliases = try_load("aliases", "aliases.py")

modules = {
    "arr": try_load("arr", "ARR"),
    "chat": try_load("chat", "Chat"),
    "weather": try_load("weather", "Weather"),
    "technitium": try_load("technitium", "DNS"),
    "uptimekuma": try_load("uptimekuma", "Kuma"),
    "digest": try_load("digest", "Digest"),
    "proxy": try_load("proxy", "Proxy"),
    "smtp_server": try_load("smtp_server", "SMTP intake"),
}

# -----------------------------
# Gotify helpers
# -----------------------------
jarvis_app_id: Optional[int] = None

def resolve_app_id():
    global jarvis_app_id
    try:
        r = requests.get(f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}", timeout=10)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] 🆔 Resolved app id {jarvis_app_id} ({APP_NAME})")
                return
        print(f"[{BOT_NAME}] ⚠️ App '{APP_NAME}' not found")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ resolve_app_id failed: {e}")

def _is_ours(data: dict) -> bool:
    try:
        if data.get("appid") == jarvis_app_id: return True
        t = (data.get("title") or "")
        return t.startswith(f"{BOT_ICON} {BOT_NAME}:")
    except Exception:
        return False

def send_message(title: str, message: str, priority: int = 5, extras: Optional[dict] = None):
    if _personality:
        try:
            title, message = _personality.decorate(title, message, CHAT_MOOD, chance=1.0)
            priority = _personality.apply_priority(priority, CHAT_MOOD)
        except Exception:
            pass
    try:
        payload = {
            "title": f"{BOT_ICON} {BOT_NAME}: {title}",
            "message": message,
            "priority": priority
        }
        if extras:
            payload["extras"] = extras
        url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ send_message failed: {e}")

def delete_original_message(msg_id: int):
    try:
        if not SILENT_REPOST: return
        url = f"{GOTIFY_URL}/message/{msg_id}?token={CLIENT_TOKEN}"
        requests.delete(url, timeout=10)
    except Exception:
        pass

# -----------------------------
# Pipeline (LLM -> polish OR beautify fallback)
# -----------------------------
def render_card(title: str, body: str, *, mood: str, source_hint: Optional[str] = None) -> Tuple[str, Optional[dict], bool]:
    used_llm = False
    llm_text = None

    if LLM_ENABLED and _llm and hasattr(_llm, "rewrite"):
        try:
            llm_text = _llm.rewrite(
                text=body,
                mood=mood,
                timeout=LLM_TIMEOUT_SECONDS,
                cpu_limit=LLM_MAX_CPU_PERCENT,
                model_path=LLM_MODEL_PATH,
            )
            if llm_text and llm_text.strip():
                used_llm = True
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ Neural Core skipped: {e}")

    if used_llm and _beautify and hasattr(_beautify, "polish"):
        text = _beautify.polish(llm_text, mood=mood)
        return text, None, True

    # Fallback: offline beautifier full pipeline
    if _beautify and hasattr(_beautify, "beautify_message"):
        text, extras = _beautify.beautify_message(title, body, mood=mood, source_hint=source_hint)
        return text, extras, False

    # Last resort
    return body, None, False

# -----------------------------
# Command helpers
# -----------------------------
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _extract_command(title: str, body: str) -> str:
    raw = f"{title or ''} {body or ''}"
    # Wake words: jarvis, bot
    m = re.search(r"\b(?:jarvis|bot)\s*[:,\-]?\s*(.*)$", raw, re.I)
    return _clean(m.group(1) if m else "")

def normalize_cmd(cmd: str) -> str:
    if _aliases and hasattr(_aliases, "normalize_cmd"):
        try:
            return _aliases.normalize_cmd(cmd)
        except Exception:
            pass
    return cmd

# -----------------------------
# Startup poster
# -----------------------------
def _brain_status() -> Tuple[str, str]:
    model = Path(LLM_MODEL_PATH)
    if LLM_ENABLED:
        if model.exists() and model.stat().st_size > 0:
            return ("ACTIVE", model.name)
        return ("ACTIVE (model missing)", model.name)
    return ("INACTIVE", model.name)

def startup_poster() -> str:
    neural_state, model_name = _brain_status()
    lines = []
    lines.append("──────────────────────────────────────────────")
    lines.append(f"{BOT_ICON} {BOT_NAME} {BOT_ICON}")
    lines.append("⚡ Boot sequence initiated...")
    lines.append("   → Personalities loaded")
    lines.append("   → Memory core mounted")
    lines.append("   → Network bridges linked")
    if LLM_ENABLED:
        lines.append(f"   → Neural Core: {neural_state}")
        lines.append(f"   → Model path: {LLM_MODEL_PATH}")
    else:
        lines.append("   → Neural Core: DISABLED")
    lines.append("🚀 Systems online — Jarvis is awake!")
    lines.append("──────────────────────────────────────────────")
    lines.append("")
    lines.append("### Subsystems")
    def row(ok, name): return f"- {'🟢' if ok else '⚪'} {name}"
    lines.append(row(RADARR_ENABLED, "Radarr"))
    lines.append(row(SONARR_ENABLED, "Sonarr"))
    lines.append(row(WEATHER_ENABLED, "Weather"))
    lines.append(row(KUMA_ENABLED, "Uptime Kuma"))
    lines.append(row(SMTP_ENABLED, "SMTP Intake"))
    lines.append(row(TECHNITIUM_ENABLED, "DNS (Technitium)"))
    lines.append("")
    lines.append("### Neural Core")
    lines.append(f"- State — **{neural_state}**")
    if LLM_ENABLED:
        lines.append(f"- Model: `{model_name}`")
    lines.append(f"- Memory: **{'ACTIVE' if LLM_MEMORY_ENABLED else 'INACTIVE'}**")
    return "\n".join(lines)

# -----------------------------
# Message handling
# -----------------------------
def handle_incoming(msg: dict):
    try:
        if _is_ours(msg):
            return  # ignore our own reposts

        msg_id = msg.get("id")
        title = msg.get("title") or "Message"
        body = msg.get("message") or ""
        appname = (msg.get("app") or {}).get("name") or ""

        # command path
        ncmd = normalize_cmd(_extract_command(title, body))
        handled = False

        # Quick memory queries
        if LLM_MEMORY_ENABLED and _llm_mem and ncmd:
            if re.search(r"\bwhat\s+happened\s+today\b", ncmd):
                try:
                    out = _llm_mem.summarize_today()
                    if out:
                        send_message("Today", out)
                        handled = True
                except Exception as e:
                    send_message("Today", f"⚠️ Memory error: {e}")
                    handled = True
            elif re.search(r"\bwhat\s+broke\s+today\b", ncmd):
                try:
                    out = _llm_mem.what_broke_today()
                    if out:
                        send_message("Issues", out)
                        handled = True
                except Exception as e:
                    send_message("Issues", f"⚠️ Memory error: {e}")
                    handled = True

        # mood change
        m = re.search(r"\bmood\s+(serious|sarcastic|playful|hacker-noir)\b", ncmd)
        if m:
            global CHAT_MOOD
            CHAT_MOOD = m.group(1)
            send_message("Mood", f"Mood set to **{CHAT_MOOD}**")
            handled = True

        # Modules (only if wake-word used)
        if ncmd and not handled:
            if WEATHER_ENABLED and modules.get("weather") and re.search(r"\b(weather|forecast|temps|now|today|current|weekly|7day|7-day)\b", ncmd):
                try:
                    w = modules["weather"].handle_weather_command(ncmd)
                    if isinstance(w, tuple):
                        send_message("Weather", w[0], extras=(w[1] if len(w)>1 else None))
                    elif isinstance(w, str) and w:
                        send_message("Weather", w)
                    handled = True
                except Exception as e:
                    send_message("Weather", f"⚠️ {e}")
                    handled = True
            elif KUMA_ENABLED and modules.get("uptimekuma") and re.search(r"\b(kuma|uptime|monitor)\b", ncmd):
                try:
                    out = modules["uptimekuma"].handle_kuma_command(ncmd)
                    if isinstance(out, tuple):
                        send_message("Kuma", out[0], extras=(out[1] if len(out)>1 else None))
                    elif isinstance(out, str) and out:
                        send_message("Kuma", out)
                    handled = True
                except Exception as e:
                    send_message("Kuma", f"⚠️ {e}")
                    handled = True
            elif CHAT_ENABLED and modules.get("chat") and re.search(r"\b(joke|pun)\b", ncmd):
                try:
                    c = modules["chat"].handle_chat_command("joke")
                    if isinstance(c, tuple):
                        send_message("Joke", c[0], extras=(c[1] if len(c)>1 else None))
                    elif isinstance(c, str):
                        send_message("Joke", c)
                    handled = True
                except Exception as e:
                    send_message("Chat", f"⚠️ {e}")
                    handled = True

            if not handled and _personality and ncmd:
                send_message("Jarvis", _personality.unknown_command_response(ncmd, CHAT_MOOD))
                handled = True

            if handled:
                if SILENT_REPOST:
                    delete_original_message(msg_id)
                return

        # Normal notification path → pipeline
        text, extras, used_llm = render_card(title, body, mood=CHAT_MOOD, source_hint=None)
        footer = " `[Neural Core ✓]`" if used_llm else " `[Beautifier]`"
        if _personality:
            try:
                quip = _personality.quip(CHAT_MOOD)
                text = f"{text}\n\n{footer}\n\n— {quip}"
            except Exception:
                text = f"{text}\n\n{footer}"
        else:
            text = f"{text}\n\n{footer}"

        send_message(title, text, extras=extras)

        # Memory log
        if LLM_MEMORY_ENABLED and _llm_mem and hasattr(_llm_mem, "log_event"):
            try:
                src = appname or msg.get("appid") or "gotify"
                _llm_mem.log_event(kind=str(src).lower(), source=src, title=title or "Message", body=text, meta={"id": msg_id})
                if hasattr(_llm_mem, "prune"):
                    _llm_mem.prune(24)
            except Exception as e:
                print(f"[{BOT_NAME}] ⚠️ Memory log failed: {e}")

        if SILENT_REPOST:
            delete_original_message(msg_id)

    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ handle_incoming error: {e}")

# -----------------------------
# WebSocket listener
# -----------------------------
async def listen():
    scheme = "wss" if GOTIFY_URL.startswith("https") else "ws"
    base = GOTIFY_URL.split("://",1)[1]
    ws_url = f"{scheme}://{base}/stream?token={CLIENT_TOKEN}"
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=30, ping_timeout=30, max_size=5*1024*1024) as ws:
                print(f"[{BOT_NAME}] 🔌 Connected to Gotify stream")
                async for raw in ws:
                    try:
                        data = json.loads(raw)
                        if isinstance(data, dict):
                            # message event payload can be nested under 'message'
                            msg = data.get("message") if "message" in data else data
                            if isinstance(msg, dict) and msg.get("message"):
                                handle_incoming(msg)
                    except Exception as e:
                        print(f"[{BOT_NAME}] ⚠️ stream decode: {e}")
        except Exception as e:
            print(f"[{BOT_NAME}] ⚠️ stream reconnect in 3s: {e}")
            await asyncio.sleep(3)

# -----------------------------
# Scheduler (heartbeat/digest hooks)
# -----------------------------
def _parse_hhmm(s: str) -> Tuple[int,int]:
    try:
        hh, mm = s.split(":")
        return int(hh), int(mm)
    except Exception:
        return (8,0)

def job_heartbeat():
    try:
        now = datetime.now().strftime("%H:%M")
        lines = [
            f"⏱ {now}",
            f"Mood: **{CHAT_MOOD}**",
        ]
        state, model = _brain_status()
        lines.append(f"Neural Core: {state}")
        if LLM_ENABLED: lines.append(f"Model: `{model}`")
        if _personality:
            lines.append("")
            lines.append(_personality.quip(CHAT_MOOD))
        send_message("Heartbeat", "\n".join(lines), priority=3)
    except Exception as e:
        print(f"[{BOT_NAME}] Heartbeat error: {e}")

def run_scheduler():
    try:
        # Heartbeat window
        hb_start = _m("heartbeat_start", "06:00")
        hb_end   = _m("heartbeat_end", "20:00")
        interval = int(_m("heartbeat_interval_minutes", 120))
        schedule.every(interval).minutes.do(job_heartbeat)

        if DIGEST_ENABLED and modules.get("digest") and hasattr(modules["digest"], "build_digest"):
            hh, mm = _parse_hhmm(_m("digest_time", "08:00"))
            schedule.every().day.at(f"{hh:02d}:{mm:02d}").do(lambda: _send_digest())

        while True:
            schedule.run_pending()
            time.sleep(1)
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ scheduler error: {e}")

def _send_digest():
    try:
        title, msg, prio = modules["digest"].build_digest(merged)
        if _personality:
            msg = f"{msg}\n\n{_personality.quip(CHAT_MOOD)}"
        send_message(title, msg, priority=prio)
    except Exception as e:
        print(f"[{BOT_NAME}] Digest error: {e}")

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] 🧠 Prime Neural Boot")
    resolve_app_id()

    # Fire startup card
    send_message("Startup", startup_poster(), priority=5)

    # Start SMTP (if available)
    try:
        if SMTP_ENABLED and modules.get("smtp_server") and hasattr(modules["smtp_server"], "start_smtp"):
            modules["smtp_server"].start_smtp(merged, send_message)
            print(f"[{BOT_NAME}] ✅ SMTP intake started")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ SMTP start error: {e}")

    # Start proxy if enabled
    try:
        if PROXY_ENABLED and modules.get("proxy") and hasattr(modules["proxy"], "start_proxy"):
            modules["proxy"].start_proxy(merged, send_message)
            print(f"[{BOT_NAME}] ✅ Proxy started")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Proxy start error: {e}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
