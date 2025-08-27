# /app/bot.py
import os, json, time, asyncio, requests, websockets, schedule, re
from datetime import datetime

# -----------------------------
# Dynamic modules dict
# -----------------------------
extra_modules = {}

# -----------------------------
# Config from env (set in run.sh)
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# Feature toggles
RADARR_ENABLED = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")

# SMTP toggle
SMTP_ENABLED = os.getenv("smtp_enabled", "false").lower() in ("1","true","yes")

AI_CHECKINS_ENABLED = os.getenv("ai_checkins_enabled", "false").lower() in ("1","true","yes")
CACHE_REFRESH_MINUTES = int(os.getenv("cache_refresh_minutes", "60"))

# Mood
CHAT_MOOD = "serious"

# Uptime tracking
BOOT_TIME = datetime.now()

# Heartbeat config
HEARTBEAT_ENABLED = False
HEARTBEAT_INTERVAL_MIN = 120
HEARTBEAT_START = "06:00"
HEARTBEAT_END = "20:00"

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

    RADARR_ENABLED = merged.get("radarr_enabled", RADARR_ENABLED)
    SONARR_ENABLED = merged.get("sonarr_enabled", SONARR_ENABLED)
    WEATHER_ENABLED = merged.get("weather_enabled", WEATHER_ENABLED)
    TECHNITIUM_ENABLED = merged.get("technitium_enabled", TECHNITIUM_ENABLED)
    KUMA_ENABLED = merged.get("uptimekuma_enabled", KUMA_ENABLED)
    SMTP_ENABLED = merged.get("smtp_enabled", SMTP_ENABLED)

    CHAT_ENABLED_FILE = merged.get("chat_enabled", CHAT_ENABLED_ENV)
    DIGEST_ENABLED_FILE = merged.get("digest_enabled", DIGEST_ENABLED_ENV)

    CHAT_MOOD = str(merged.get("personality_mood", merged.get("chat_mood", CHAT_MOOD)))

    HEARTBEAT_ENABLED = bool(merged.get("heartbeat_enabled", HEARTBEAT_ENABLED))
    HEARTBEAT_INTERVAL_MIN = int(merged.get("heartbeat_interval_minutes", HEARTBEAT_INTERVAL_MIN))
    HEARTBEAT_START = str(merged.get("heartbeat_start", HEARTBEAT_START))
    HEARTBEAT_END = str(merged.get("heartbeat_end", HEARTBEAT_END))

except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options/config json: {e}")

jarvis_app_id = None

# -----------------------------
# Optional alias + personality
# -----------------------------
_alias_mod = None
try:
    import importlib.util as _imp
    _alias_spec = _imp.spec_from_file_location("alias", "/app/alias.py")
    if _alias_spec and _alias_spec.loader:
        _alias_mod = _imp.module_from_spec(_alias_spec)
        _alias_spec.loader.exec_module(_alias_mod)
        print("[Jarvis Prime] ✅ alias.py loaded")
except Exception as _e:
    print(f"[Jarvis Prime] ⚠️ alias.py not loaded: {_e}")

_personality = None
try:
    import importlib.util as _imp
    _pspec = _imp.spec_from_file_location("personality", "/app/personality.py")
    if _pspec and _pspec.loader:
        _personality = _imp.module_from_spec(_pspec)
        _pspec.loader.exec_module(_personality)
        print("[Jarvis Prime] ✅ personality.py loaded")
except Exception as _e:
    print(f"[Jarvis Prime] ⚠️ personality.py not loaded: {_e}")

# -----------------------------
# Utils
# -----------------------------
def send_message(title, message, priority=5, extras=None):
    # Always decorate + bias priority
    if _personality:
        title, message = _personality.decorate(title, message, CHAT_MOOD, chance=1.0)
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
    """Delete a Gotify message by id (used for purge of non-Jarvis posts)."""
    try:
        if not msg_id:
            return
        url = f"{GOTIFY_URL}/message/{msg_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.delete(url, headers=headers, timeout=6)
        if r.status_code in (200, 204):
            print(f"[{BOT_NAME}] 🧹 Purged original message id={msg_id}")
        else:
            print(f"[{BOT_NAME}] ⚠️ Purge failed id={msg_id}: {r.status_code}")
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Purge error: {e}")

def resolve_app_id():
    global jarvis_app_id
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=6)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                return
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

# -----------------------------
# Dynamic module loader
# -----------------------------
def try_load_module(modname, label):
    path = f"/app/{modname}.py"
    if modname == "arr":
        enabled = True
    else:
        enabled = os.getenv(f"{modname}_enabled", "false").lower() in ("1","true","yes")
        if not enabled:
            try:
                with open("/data/options.json", "r") as f:
                    enabled = json.load(f).get(f"{modname}_enabled", False)
            except Exception:
                enabled = False
    if not os.path.exists(path) or not enabled:
        print(f"[{BOT_NAME}] ↩️ Skipping module {modname}: file_exists={os.path.exists(path)} enabled={enabled}")
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        extra_modules[modname] = module
        print(f"[{BOT_NAME}] ✅ Loaded module: {modname}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Failed to load {modname}: {e}")
        return False

# -----------------------------
# Startup poster
# -----------------------------
def startup_poster():
    def mod_line(icon, name, enabled):
        return f"    {icon} {name} – {'ACTIVE' if enabled else 'INACTIVE'}"
    lines = []
    lines.append("🧠 Jarvis Prime – Prime Neural Boot\n")
    lines.append(f"Mood: {CHAT_MOOD}")
    lines.append("Modules:")
    lines.append(mod_line("🎬", "Radarr", RADARR_ENABLED))
    lines.append(mod_line("📺", "Sonarr", SONARR_ENABLED))
    lines.append(mod_line("🌤", "Weather", WEATHER_ENABLED))
    lines.append(mod_line("📰", "Digest", DIGEST_ENABLED_ENV or DIGEST_ENABLED_FILE))
    lines.append(mod_line("💬", "Chat", CHAT_ENABLED_ENV or CHAT_ENABLED_FILE))
    lines.append(mod_line("📡", "Uptime Kuma", KUMA_ENABLED))
    lines.append(mod_line("✉️", "SMTP Intake", SMTP_ENABLED))
    lines.append(mod_line("🧬", "DNS (Technitium)", TECHNITIUM_ENABLED))
    lines.append("\nStatus: All systems nominal")
    return "\n".join(lines)

# -----------------------------
# Heartbeat + helpers
# -----------------------------
def _parse_hhmm(s):
    try:
        hh, mm = s.split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return 0

def _in_window(now, start, end):
    mins = now.hour * 60 + now.minute
    a = _parse_hhmm(start); b = _parse_hhmm(end)
    if a == b:
        return True
    if a < b:
        return a <= mins <= b
    return mins >= a or mins <= b

def _fmt_uptime():
    d = datetime.now() - BOOT_TIME
    total = int(d.total_seconds() // 60)
    h, m = divmod(total, 60)
    days, h = divmod(h, 24)
    parts = []
    if days: parts.append(f"{days}d")
    if h: parts.append(f"{h}h")
    parts.append(f"{m}m")
    return " ".join(parts)

def send_heartbeat_if_window():
    try:
        if not HEARTBEAT_ENABLED:
            return
        now = datetime.now()
        if not _in_window(now, HEARTBEAT_START, HEARTBEAT_END):
            return
        lines = [
            "🫀 Heartbeat — Jarvis Prime alive",
            f"Time: {now.strftime('%Y-%m-%d %H:%M')}",
            f"Uptime: {_fmt_uptime()}",
            ""
        ]
        # ARR (short upcoming)
        try:
            if "arr" in extra_modules:
                mv = extra_modules["arr"].list_upcoming_movies(days=1, limit=3) if hasattr(extra_modules["arr"], "list_upcoming_movies") else []
                if mv:
                    lines.append("🎬 Today’s Movies:")
                    lines += [f"- {x}" for x in mv]
                tv = extra_modules["arr"].list_upcoming_series(days=1, limit=5) if hasattr(extra_modules["arr"], "list_upcoming_series") else []
                if tv:
                    if mv: lines.append("")
                    lines.append("📺 Today’s Episodes:")
                    lines += [f"- {x}" for x in tv]
        except Exception as e:
            lines.append(f"ARR error: {e}")

        if _personality:
            lines.append("")
            lines.append(_personality.quip(CHAT_MOOD))

        send_message("Heartbeat", "\n".join(lines), priority=3)
    except Exception as e:
        print(f"[{BOT_NAME}] Heartbeat error: {e}")

# -----------------------------
# Digest helper
# -----------------------------
def job_daily_digest():
    try:
        dmod = extra_modules.get("digest")
        if not dmod or not hasattr(dmod, "build_digest"):
            return
        title, msg, prio = dmod.build_digest(merged)
        if _personality:
            msg += f"\n\n{_personality.quip(CHAT_MOOD)}"
        send_message(title, msg, priority=prio)
    except Exception as e:
        print(f"[{BOT_NAME}] Digest error: {e}")

# -----------------------------
# Normalization + command extraction
# -----------------------------
def _clean(s):
    return re.sub(r"\s+", " ", s.lower().strip())

def normalize_cmd(cmd: str) -> str:
    if _alias_mod and hasattr(_alias_mod, "normalize_cmd"):
        return _alias_mod.normalize_cmd(cmd)
    return _clean(cmd)

def extract_command_from(title: str, message: str) -> str:
    """Handle cases where title == 'jarvis' and the actual command is in message."""
    tlow, mlow = title.lower(), message.lower()
    if tlow.startswith("jarvis"):
        tcmd = tlow.replace("jarvis", "", 1).strip()
        if tcmd:
            return tcmd
        # fallback to message body if title had only 'jarvis'
        if mlow.startswith("jarvis"):
            return mlow.replace("jarvis", "", 1).strip()
        return mlow.strip()
    if mlow.startswith("jarvis"):
        return mlow.replace("jarvis", "", 1).strip()
    return ""

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
                appid = data.get("appid")
                if appid == jarvis_app_id:
                    continue  # ignore our own posts

                title = data.get("title", "") or ""
                message = data.get("message", "") or ""

                # Wake-word?
                ncmd = normalize_cmd(extract_command_from(title, message))
                if ncmd:
                    # Help
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
                            "  • upcoming movies\n"
                            "  • upcoming series\n"
                            "  • movie count\n"
                            "  • series count\n"
                            "  • longest movie\n"
                            "  • longest series\n"
                        )
                        send_message("Help", help_text)
                        continue

                    # Manual digest
                    if ncmd in ("digest", "daily digest", "summary"):
                        job_daily_digest()
                        continue

                    # DNS
                    if TECHNITIUM_ENABLED and "technitium" in extra_modules and re.search(r"\bdns\b|technitium", ncmd):
                        out = extra_modules["technitium"].handle_dns_command(ncmd)
                        if isinstance(out, tuple):
                            send_message("DNS", out[0], extras=(out[1] if len(out) > 1 else None)); continue
                        if isinstance(out, str) and out:
                            send_message("DNS", out); continue

                    # Uptime Kuma
                    if KUMA_ENABLED and "uptimekuma" in extra_modules and re.search(r"\bkuma\b|\buptime\b|\bmonitor", ncmd):
                        out = extra_modules["uptimekuma"].handle_kuma_command(ncmd)
                        if isinstance(out, tuple):
                            send_message("Kuma", out[0], extras=(out[1] if len(out) > 1 else None)); continue
                        if isinstance(out, str) and out:
                            send_message("Kuma", out); continue

                    # Weather
                    if WEATHER_ENABLED and "weather" in extra_modules and any(w in ncmd for w in ("weather","forecast","temperature","temp","now","today","current","weekly","7day","7-day","7 day")):
                        w = extra_modules["weather"].handle_weather_command(ncmd)
                        if isinstance(w, tuple) and w and w[0]:
                            msg_text = w[0]
                            extras = (w[1] if len(w) > 1 else None)
                            if _personality: msg_text = f"{msg_text}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Weather", msg_text, extras=extras); continue
                        if isinstance(w, str) and w:
                            msg_text = w
                            if _personality: msg_text = f"{msg_text}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Weather", msg_text); continue

                    # Chat jokes
                    if CHAT_ENABLED_FILE and "chat" in extra_modules and ("joke" in ncmd or "pun" in ncmd):
                        c = extra_modules["chat"].handle_chat_command("joke")
                        if isinstance(c, tuple):
                            send_message("Joke", c[0], extras=(c[1] if len(c) > 1 else None)); continue
                        else:
                            send_message("Joke", str(c)); continue

                    # ARR (unconditional handoff)
                    if "arr" in extra_modules and hasattr(extra_modules["arr"], "handle_arr_command"):
                        r = extra_modules["arr"].handle_arr_command(title, message)
                        if isinstance(r, tuple) and r and r[0]:
                            # pass extras through so Radarr/Sonarr posters render
                            extras = r[1] if len(r) > 1 else None
                            msg_text = r[0]
                            if _personality: msg_text = f"{msg_text}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Jarvis", msg_text, extras=extras); continue
                        if isinstance(r, str) and r:
                            msg_text = r
                            if _personality: msg_text = f"{msg_text}\n\n{_personality.quip(CHAT_MOOD)}"
                            send_message("Jarvis", msg_text); continue

                    # Unknown → personality
                    if _personality:
                        resp = _personality.unknown_command_response(ncmd, CHAT_MOOD)
                        send_message("Jarvis", resp); continue
                    else:
                        send_message("Jarvis", f"Unknown command: {ncmd}"); continue

                # Non-wwake messages: repost (beautified path) then purge original
                if SILENT_REPOST:
                    send_message(title, message)   # decorate + priority bias happen inside
                    delete_original_message(msg_id)
                else:
                    send_message(title, message)

            except Exception as e:
                print(f"[{BOT_NAME}] Listener error: {e}")

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    # keep very light (placeholder for future retention jobs)
    schedule.every(RETENTION_HOURS).hours.do(lambda: None)

    if HEARTBEAT_ENABLED and HEARTBEAT_INTERVAL_MIN > 0:
        schedule.every(HEARTBEAT_INTERVAL_MIN).minutes.do(send_heartbeat_if_window)

    # daily digest (validate time first)
    try:
        if bool(merged.get("digest_enabled", False)):
            dtime = str(merged.get("digest_time", "08:00")).strip()
            if re.match(r"^\d{2}:\d{2}(:\d{2})?$", dtime):
                schedule.every().day.at(dtime).do(job_daily_digest)
                print(f"[{BOT_NAME}] [Digest] scheduled @ {dtime}")
            else:
                print(f"[{BOT_NAME}] [Digest] ⚠️ Invalid time '{dtime}' (HH:MM[:SS]) → skipping")
    except Exception as e:
        print(f"[{BOT_NAME}] [Digest] schedule error: {e}")

    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on…")
    resolve_app_id()

    # Load modules
    try_load_module("arr", "ARR")
    try_load_module("chat", "Chat")
    try_load_module("weather", "Weather")
    try_load_module("technitium", "DNS")
    try_load_module("uptimekuma", "Kuma")
    try_load_module("digest", "Digest")

    # Start SMTP intake (if enabled)
    try:
        if SMTP_ENABLED and bool(merged.get("smtp_enabled", SMTP_ENABLED)):
            import importlib.util as _imp
            _sspec = _imp.spec_from_file_location("smtp_server", "/app/smtp_server.py")
            if _sspec and _sspec.loader:
                _smtp_mod = _imp.module_from_spec(_sspec)
                _sspec.loader.exec_module(_smtp_mod)
                _smtp_mod.start_smtp(merged, send_message)
                print("[Jarvis Prime] ✅ SMTP intake started")
            else:
                print("[Jarvis Prime] ⚠️ smtp_server.py not found")
    except Exception as e:
        print(f"[Jarvis Prime] ⚠️ SMTP start error: {e}")

    # Startup card
    send_message("Startup", startup_poster(), priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
