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
CHAT_MOOD = "Calm"

# -----------------------------
# Load /data/options.json overrides
# -----------------------------
def _load_json_file(path):
    try:
        with open(path, "r") as f: return json.load(f)
    except Exception: return {}

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
except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options/config json: {e}")

jarvis_app_id = None

# -----------------------------
# Utils
# -----------------------------
def send_message(title, message, priority=5, extras=None):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    if extras: data["extras"] = extras
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
        r = requests.get(url, headers=headers, timeout=5); r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id"); return
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

# -----------------------------
# Dynamic module loader
# -----------------------------
def try_load_module(modname, label):
    path = f"/app/{modname}.py"
    enabled = os.getenv(f"{modname}_enabled", "false").lower() in ("1","true","yes")
    if not enabled:
        try:
            with open("/data/options.json", "r") as f:
                enabled = json.load(f).get(f"{modname}_enabled", False)
        except Exception:
            enabled = False
    if not os.path.exists(path) or not enabled:
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
# Startup poster (lean)
# -----------------------------
def startup_poster():
    def mod_line(icon,name,enabled): return f"    {icon} {name} – {'ACTIVE' if enabled else 'INACTIVE'}"
    lines = []
    lines.append("🧠 Jarvis Prime – Prime Neural Boot\n")
    lines.append(f"Mood: {CHAT_MOOD}")
    lines.append("Modules:")
    lines.append(mod_line("🎬","Radarr", RADARR_ENABLED))
    lines.append(mod_line("📺","Sonarr", SONARR_ENABLED))
    lines.append(mod_line("🌤","Weather", WEATHER_ENABLED))
    lines.append(mod_line("📰","Digest", DIGEST_ENABLED_ENV or DIGEST_ENABLED_FILE))
    lines.append(mod_line("💬","Chat", CHAT_ENABLED_ENV or CHAT_ENABLED_FILE))
    lines.append(mod_line("📡","Uptime Kuma", KUMA_ENABLED))
    lines.append(mod_line("🧬","DNS (Technitium)", TECHNITIUM_ENABLED))
    lines.append("\nStatus: All systems nominal")
    return "\n".join(lines)

# -----------------------------
# Listeners / Scheduler
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting {ws_url}")
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        print(f"[{BOT_NAME}] ✅ Connected")
        async for msg in ws:
            try:
                data = json.loads(msg)
                appid = data.get("appid")
                if appid == jarvis_app_id:
                    continue  # ignore our own posts
                title = data.get("title","")
                message = data.get("message","")

                # Wake word
                if title.lower().startswith("jarvis") or message.lower().startswith("jarvis"):
                    # build command after wake word
                    if title.lower().startswith("jarvis"):
                        tmp = title.lower().replace("jarvis","",1).strip()
                        cmd = tmp if tmp else message.lower().replace("jarvis","",1).strip()
                    else:
                        cmd = message.lower().replace("jarvis","",1).strip()

                    # Help
                    if cmd in ("help","commands"):
                        help_text = (
                            "🤖 **Jarvis Prime Commands**\n\n"
                            "🌐 DNS: `dns` → Technitium summary\n"
                            "📡 Kuma: `kuma` → Uptime Kuma metrics\n"
                            "🌦 Weather: `weather`, `forecast`\n"
                            "🎬/📺: `movie count`, `series count`, `upcoming movies|series`\n"
                        )
                        send_message("Help", help_text)
                        continue

                    # DNS (Technitium)
                    if "technitium" in extra_modules and re.search(r"\bdns\b", cmd, re.IGNORECASE):
                        out = extra_modules["technitium"].handle_dns_command(cmd)
                        if isinstance(out, tuple) and out[0]:
                            send_message("DNS", out[0], extras=(out[1] if len(out)>1 else None)); continue
                        if isinstance(out, str) and out:
                            send_message("DNS", out); continue

                    # Kuma
                    if "uptimekuma" in extra_modules and ("kuma" in cmd or "uptime" in cmd):
                        out = extra_modules["uptimekuma"].handle_kuma_command(cmd)
                        if isinstance(out, tuple) and out[0]:
                            send_message("Kuma", out[0], extras=(out[1] if len(out)>1 else None)); continue
                        if isinstance(out, str) and out:
                            send_message("Kuma", out); continue

                    # Weather
                    if "weather" in extra_modules and any(w in cmd for w in ("weather","forecast","temperature","temp","now","today")):
                        w = extra_modules["weather"].handle_weather_command(cmd)
                        if isinstance(w, tuple) and w[0]:
                            send_message("Weather", w[0], extras=(w[1] if len(w)>1 else None)); continue
                        if isinstance(w, str) and w:
                            send_message("Weather", w); continue

                    # Chat jokes
                    if "chat" in extra_modules and ("joke" in cmd or "pun" in cmd):
                        c = extra_modules["chat"].handle_chat_command("joke") if hasattr(extra_modules["chat"],"handle_chat_command") else ("🃏 Here's a joke.", None)
                        if isinstance(c, tuple):
                            send_message("Joke", c[0], extras=(c[1] if len(c)>1 else None)); continue
                        else:
                            send_message("Joke", str(c)); continue

                    # ARR fallback if present
                    if "arr" in extra_modules and hasattr(extra_modules["arr"], "handle_arr_command"):
                        r = extra_modules["arr"].handle_arr_command(title, message)
                        if isinstance(r, tuple) and r[0]:
                            send_message("Jarvis", r[0], extras=(r[1] if len(r)>1 else None)); continue
                        if isinstance(r, str) and r:
                            send_message("Jarvis", r); continue

                    # Unknown
                    send_message("Jarvis", f"Unknown command: {cmd}")
                    continue

                # Non-wake messages: optional beautify (kept simple)
                send_message(title, message)

            except Exception as e:
                print(f"[{BOT_NAME}] Error processing: {e}")

def run_scheduler():
    # keep very light
    schedule.every(RETENTION_HOURS).hours.do(lambda: None)
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

    # Startup card
    send_message("Startup", startup_poster(), priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
