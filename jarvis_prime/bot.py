import os, json, time, asyncio, requests, websockets, schedule, random, re, yaml
from datetime import datetime, timezone

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

# Feature toggles (env defaults; config can override)
RADARR_ENABLED = os.getenv("radarr_enabled", "false").lower() in ("1","true","yes")
SONARR_ENABLED = os.getenv("sonarr_enabled", "false").lower() in ("1","true","yes")
WEATHER_ENABLED = os.getenv("weather_enabled", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
KUMA_ENABLED = os.getenv("uptimekuma_enabled", "false").lower() in ("1","true","yes")

AI_CHECKINS_ENABLED = os.getenv("ai_checkins_enabled", "false").lower() in ("1","true","yes")
CACHE_REFRESH_MINUTES = int(os.getenv("cache_refresh_minutes", "60"))

# Mood
CHAT_MOOD = "serious"

# Uptime tracking for heartbeat
BOOT_TIME = datetime.now()

# Heartbeat config defaults
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

    CHAT_ENABLED_FILE = merged.get("chat_enabled", CHAT_ENABLED_ENV)
    DIGEST_ENABLED_FILE = merged.get("digest_enabled", DIGEST_ENABLED_ENV)

    CHAT_MOOD = str(merged.get("personality_mood", merged.get("chat_mood", CHAT_MOOD)))

    # Heartbeat config
    HEARTBEAT_ENABLED = bool(merged.get("heartbeat_enabled", HEARTBEAT_ENABLED))
    HEARTBEAT_INTERVAL_MIN = int(merged.get("heartbeat_interval_minutes", HEARTBEAT_INTERVAL_MIN))
    HEARTBEAT_START = str(merged.get("heartbeat_start", HEARTBEAT_START))
    HEARTBEAT_END = str(merged.get("heartbeat_end", HEARTBEAT_END))

except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options/config json: {e}")

jarvis_app_id = None

# -----------------------------
# Optional alias module
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

# -----------------------------
# Personality module
# -----------------------------
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
    # Optionally decorate with mood
    if _personality:
        title, message = _personality.decorate(title, message, CHAT_MOOD)
        priority = _personality.apply_priority(priority, CHAT_MOOD)
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    if extras:
        data["extras"] = extras
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to send message: {e}")
        return False

def resolve_app_id():
    global jarvis_app_id
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
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
    lines.append(mod_line("🧬", "DNS (Technitium)", TECHNITIUM_ENABLED))
    lines.append("\nStatus: All systems nominal")
    return "\n".join(lines)

# -----------------------------
# Heartbeat
# -----------------------------
def _parse_hhmm(s: str):
    try: hh, mm = s.split(":"); return int(hh)*60 + int(mm)
    except Exception: return 0

def _in_window(now_dt: datetime, start_hhmm: str, end_hhmm: str):
    mins = now_dt.hour*60 + now_dt.minute
    a = _parse_hhmm(start_hhmm); b = _parse_hhmm(end_hhmm)
    if a == b: return True
    if a < b: return a <= mins <= b
    return mins >= a or mins <= b

def _fmt_uptime():
    delta = datetime.now() - BOOT_TIME
    total_min = int(delta.total_seconds() // 60)
    h, m = divmod(total_min, 60); d, h = divmod(h, 24)
    parts = []; 
    if d: parts.append(f"{d}d"); 
    if h: parts.append(f"{h}h"); 
    parts.append(f"{m}m")
    return " ".join(parts)

def send_heartbeat_if_window():
    try:
        if not HEARTBEAT_ENABLED: return
        now = datetime.now()
        if not _in_window(now, HEARTBEAT_START, HEARTBEAT_END): return
        lines = []
        lines.append("🫀 Heartbeat — Jarvis Prime alive")
        lines.append(f"Time: {now.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"Uptime: {_fmt_uptime()}")
        lines.append("")
        # ARR upcoming
        try:
            if "arr" in extra_modules:
                mv = extra_modules["arr"].list_upcoming_movies(days=1, limit=3) if hasattr(extra_modules["arr"], "list_upcoming_movies") else []
                if mv:
                    lines.append("🎬 Today’s Movies:"); lines += [f"- {x}" for x in mv]
                tv = extra_modules["arr"].list_upcoming_series(days=1, limit=5) if hasattr(extra_modules["arr"], "list_upcoming_series") else []
                if tv:
                    if mv: lines.append("")
                    lines.append("📺 Today’s Episodes:"); lines += [f"- {x}" for x in tv]
        except Exception as e: lines.append(f"ARR error: {e}")
        # One short quip
        if _personality: lines.append(""); lines.append(_personality.quip(CHAT_MOOD))
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
            print(f"[{BOT_NAME}] [Digest] build_digest not available"); return
        title, message, priority = dmod.build_digest(merged)
        send_message(title, message, priority=priority, extras=None)
        print(f"[{BOT_NAME}] [Digest] sent at {datetime.now().strftime('%H:%M')}")
    except Exception as e:
        print(f"[{BOT_NAME}] [Digest] ERROR: {e}")

# -----------------------------
# Normalization
# -----------------------------
def _clean(s: str) -> str: return re.sub(r"\s+", " ", s.lower().strip())
def normalize_cmd(cmd: str) -> str:
    if _alias_mod and hasattr(_alias_mod, "normalize_cmd"): return _alias_mod.normalize_cmd(cmd)
    return _clean(cmd)

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
                data = json.loads(msg); appid = data.get("appid")
                if appid == jarvis_app_id: continue
                title, message = data.get("title",""), data.get("message","")
                tlow, mlow = title.lower(), message.lower()
                if tlow.startswith("jarvis") or mlow.startswith("jarvis"):
                    cmd = tlow.replace("jarvis","",1).strip() if tlow.startswith("jarvis") else mlow.replace("jarvis","",1).strip()
                    ncmd = normalize_cmd(cmd)
                    # Help
                    if ncmd in ("help","commands"):
                        help_text = (
                            "🤖 **Jarvis Prime Commands**\n\n"
                            "🌐 DNS: `dns`\n"
                            "🌦 Weather: `weather`, `forecast`\n"
                            "🎬/📺 Movies/Series: `movie count`, `series count`, `upcoming movies`, `upcoming series`, `longest movie`, `longest series`\n"
                            "🃏 Fun: `joke`\n"
                            "📰 Digest: `digest`\n"
                        ); send_message("Help", help_text); continue
                    # Manual digest
                    if ncmd in ("digest","daily digest","summary"): job_daily_digest(); continue
                    # DNS
                    if "technitium" in extra_modules and re.search(r"\bdns\b|technitium", ncmd):
                        out = extra_modules["technitium"].handle_dns_command(ncmd)
                        if isinstance(out, tuple) and out and out[0]: send_message("DNS", out[0]); continue
                        if isinstance(out, str) and out: send_message("DNS", out); continue
                    # Weather
                    if "weather" in extra_modules and any(w in ncmd for w in ("weather","forecast","temperature","temp","now","today","current")):
                        w = extra_modules["weather"].handle_weather_command(ncmd)
                        if isinstance(w, tuple) and w and w[0]: send_message("Weather", w[0]); continue
                        if isinstance(w, str) and w: send_message("Weather", w); continue
                    # Chat jokes
                    if "chat" in extra_modules and ("joke" in ncmd or "pun" in ncmd):
                        c = extra_modules["chat"].handle_chat_command("joke") if hasattr(extra_modules["chat"],"handle_chat_command") else ("🃏 Here's a joke.",None)
                        if isinstance(c, tuple): send_message("Joke", c[0]); continue
                        else: send_message("Joke", str(c)); continue
                    # ARR
                    if "arr" in extra_modules and hasattr(extra_modules["arr"],"handle_arr_command"):
                        r = extra_modules["arr"].handle_arr_command(title,message)
                        if isinstance(r, tuple) and r and r[0]: send_message("Jarvis", r[0]); continue
                        if isinstance(r, str) and r: send_message("Jarvis", r); continue
                    # Unknown → use personality
                    if _personality:
                        resp = _personality.unknown_command_response(cmd, CHAT_MOOD)
                        send_message("Jarvis", resp); continue
                    else:
                        send_message("Jarvis", f"Unknown command: {cmd}"); continue
                # Non-wake messages
                send_message(title, message)
            except Exception as e: print(f"[{BOT_NAME}] Error processing: {e}")

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(RETENTION_HOURS).hours.do(lambda: None)
    if HEARTBEAT_ENABLED and HEARTBEAT_INTERVAL_MIN>0: schedule.every(HEARTBEAT_INTERVAL_MIN).minutes.do(send_heartbeat_if_window)
    try:
        if bool(merged.get("digest_enabled", False)):
            dtime = str(merged.get("digest_time","08:00")).strip()
            schedule.every().day.at(dtime).do(job_daily_digest)
            print(f"[{BOT_NAME}] [Digest] scheduled @ {dtime}")
    except Exception as e: print(f"[{BOT_NAME}] [Digest] schedule error: {e}")
    while True: schedule.run_pending(); time.sleep(1)

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on…")
    resolve_app_id()
    try_load_module("arr","ARR"); try_load_module("chat","Chat"); try_load_module("weather","Weather")
    try_load_module("technitium","DNS"); try_load_module("uptimekuma","Kuma"); try_load_module("digest","Digest")
    send_message("Startup", startup_poster(), priority=5)
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    loop.create_task(listen()); loop.run_in_executor(None, run_scheduler); loop.run_forever()
