import os, json, time, asyncio, requests, websockets, schedule, random, re, yaml
from datetime import datetime, timezone
import importlib.util

# --- Reuse ARR (Radarr/Sonarr) from Prime's arr.py ---
try:
    from arr import handle_arr_command, RADARR_ENABLED, SONARR_ENABLED, cache_radarr, cache_sonarr
except Exception as e:
    print(f"[Jarvis Prime] ⚠️ ARR module not available: {e}")
    handle_arr_command = lambda *args, **kwargs: ("⚠️ ARR module not available", None)
    RADARR_ENABLED = False
    SONARR_ENABLED = False
    def cache_radarr(): pass
    def cache_sonarr(): pass

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Prime")
BOT_ICON = os.getenv("BOT_ICON", "🧠")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

# Feature toggles from env (run.sh sets from options)
RADARR_ENABLED = os.getenv("RADARR_ENABLED", "false").lower() in ("1","true","yes")
SONARR_ENABLED = os.getenv("SONARR_ENABLED", "false").lower() in ("1","true","yes")
WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "false").lower() in ("1","true","yes")
CHAT_ENABLED_ENV = os.getenv("chat_enabled", "false").lower() in ("1","true","yes")
DIGEST_ENABLED_ENV = os.getenv("digest_enabled", "false").lower() in ("1","true","yes")
AI_CHECKINS_ENABLED = os.getenv("ai_checkins_enabled", "true").lower() in ("1","true","yes")
CACHE_REFRESH_MINUTES = int(os.getenv("cache_refresh_minutes", "60"))
TECHNITIUM_ENABLED = os.getenv("technitium_enabled", "false").lower() in ("1","true","yes")
UPTIMEKUMA_ENABLED = os.getenv("uptimekuma_enabled", "true").lower() in ("1","true","yes")

CHAT_MOOD = "Calm"

def _load_json_file(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

# Merge options/config
try:
    options = _load_json_file("/data/options.json")
    fallback = _load_json_file("/data/config.json")
    merged = {**fallback, **options}
    RADARR_ENABLED = merged.get("radarr_enabled", RADARR_ENABLED)
    SONARR_ENABLED = merged.get("sonarr_enabled", SONARR_ENABLED)
    WEATHER_ENABLED = merged.get("weather_enabled", WEATHER_ENABLED)
    DIGEST_ENABLED_FILE = merged.get("digest_enabled", DIGEST_ENABLED_ENV)
    CHAT_ENABLED_FILE = merged.get("chat_enabled", CHAT_ENABLED_ENV)
    AI_CHECKINS_ENABLED = merged.get("ai_checkins_enabled", AI_CHECKINS_ENABLED)
    CACHE_REFRESH_MINUTES = int(merged.get("cache_refresh_minutes", CACHE_REFRESH_MINUTES))
    UPTIMEKUMA_ENABLED = merged.get("uptimekuma_enabled", UPTIMEKUMA_ENABLED)
    TECHNITIUM_ENABLED = merged.get("technitium_enabled", TECHNITIUM_ENABLED)
    CHAT_MOOD = str(merged.get("personality_mood", merged.get("chat_mood", CHAT_MOOD)))
except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options/config: {e}")

jarvis_app_id = None
extra_modules = {}

def send_message(title, message, priority=5, extras=None):
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
        print(f"[{BOT_NAME}] ❌ Send failed: {e}")
        return False

def resolve_app_id():
    global jarvis_app_id
    print(f"[{BOT_NAME}] Resolving app ID for '{APP_NAME}'")
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        apps = r.json()
        for app in apps:
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] ✅ Found '{APP_NAME}' id={jarvis_app_id}")
                return
        print(f"[{BOT_NAME}] ❌ App '{APP_NAME}' not found")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Resolve app id failed: {e}")

def purge_all_messages():
    if not jarvis_app_id:
        return
    try:
        url = f"{GOTIFY_URL}/application/{jarvis_app_id}/message"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] 🗑 Purged messages")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Purge failed: {e}")

def try_load_module(modname, label, icon="🧩"):
    path = f"/app/{modname}.py"
    enabled = os.getenv(f"{modname}_enabled", "false").lower() in ("1","true","yes")
    # allow options.json to override
    try:
        with open("/data/options.json","r") as f:
            opts = json.load(f)
            enabled = opts.get(f"{modname}_enabled", enabled)
    except Exception:
        pass
    if not os.path.exists(path) or not enabled:
        return None
    try:
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        extra_modules[modname] = module
        print(f"[{BOT_NAME}] ✅ Loaded module: {modname}")
        return f"{icon} {label}"
    except Exception as e:
        print(f"[{BOT_NAME}] ⚠️ Load failed {modname}: {e}")
        return None

def format_startup_poster():
    def line(enabled, name, icon):
        return f"    {icon} {name} — {'ACTIVE' if enabled else 'INACTIVE'}"
    lines = []
    lines.append(f"🧠 {BOT_NAME} — Prime Neural Boot")
    lines.append(f"    Mood: {CHAT_MOOD}")
    lines.append("    Modules:")
    lines.append(line(RADARR_ENABLED, "Radarr", "🎬"))
    lines.append(line(SONARR_ENABLED, "Sonarr", "📺"))
    lines.append(line(WEATHER_ENABLED, "Weather", "🌤️"))
    lines.append(line(DIGEST_ENABLED_ENV or DIGEST_ENABLED_FILE, "Digest", "📰"))
    lines.append(line(CHAT_ENABLED_ENV or CHAT_ENABLED_FILE, "Chat", "💬"))
    lines.append(line(UPTIMEKUMA_ENABLED, "Uptime Kuma", "📡"))
    lines.append(line(TECHNITIUM_ENABLED, "DNS (Technitium)", "🧬"))
    lines.append("    Status: All systems nominal")
    return "\n".join(lines)

def beautify_message(title, raw):
    # simple pass-through in Prime foundation; can borrow Jnr beautifier later
    return raw, None

async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting {ws_url}")
    try:
        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
            print(f"[{BOT_NAME}] ✅ Connected")
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    appid = data.get("appid")
                    if appid == jarvis_app_id:
                        continue
                    title = data.get("title","")
                    message = data.get("message","")

                    text = (title + " " + message).lower()

                    # Help
                    if text.strip().startswith("jarvis") and any(w in text for w in ["help","commands"]):
                        help_text = (
                            "🧠 Jarvis Prime Commands\n\n"
                            "📡 Kuma: `jarvis kuma status`, `jarvis kuma incidents`\n"
                            "🧬 DNS:  `jarvis dns status`, `jarvis dns flush`\n"
                            "🎬 Radarr: `jarvis movie count`, `jarvis upcoming movies`\n"
                            "📺 Sonarr: `jarvis series count`, `jarvis upcoming series`\n"
                            "🌤️ Weather: `jarvis weather`, `jarvis forecast`\n"
                            "📰 Digest: auto daily at configured time\n"
                        )
                        send_message("Help", help_text); continue

                    # Uptime Kuma
                    if "uptimekuma" in extra_modules and ("kuma" in text):
                        resp = extra_modules["uptimekuma"].handle_kuma_command(text)
                        if isinstance(resp, tuple) and resp[0]:
                            send_message("Kuma", resp[0], extras=resp[1]); continue

                    # Weather
                    if "weather" in extra_modules and any(w in text for w in ["weather","forecast","temperature","temp"]):
                        r = extra_modules["weather"].handle_weather_command(text)
                        if isinstance(r, tuple) and r[0]:
                            send_message("Weather", r[0], extras=r[1]); continue

                    # ✅ Technitium DNS routing
                    if "technitium" in extra_modules and re.search(r"\bdns\b", text, re.IGNORECASE):
                        t_resp = extra_modules["technitium"].handle_dns_command(text)
                        if isinstance(t_resp, tuple) and t_resp[0]:
                            send_message("DNS", t_resp[0], extras=t_resp[1]); continue
                        if isinstance(t_resp, str) and t_resp:
                            send_message("DNS", t_resp); continue

                    # Chat jokes
                    if "chat" in extra_modules and ("joke" in text or "pun" in text):
                        try:
                            if hasattr(extra_modules["chat"], "handle_chat_command"):
                                c = extra_modules["chat"].handle_chat_command("joke")
                            else:
                                c = (extra_modules["chat"].get_joke(), None)
                            send_message("Joke", c[0], extras=c[1]); continue
                        except Exception as e:
                            send_message("Joke", f"⚠️ Joke error: {e}"); continue

                    # ARR
                    if text.strip().startswith("jarvis"):
                        r = handle_arr_command(title, message)
                        if isinstance(r, tuple) and r[0]:
                            send_message("Jarvis", r[0], extras=r[1]); continue

                    final, extras = beautify_message(title, message) if BEAUTIFY_ENABLED else (message, None)
                    send_message(title, final, extras=extras)

                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WS fail: {e}")
        await asyncio.sleep(10)
        await listen()

def run_scheduler():
    if RADARR_ENABLED and 'cache_radarr' in globals():
        try: schedule.every(CACHE_REFRESH_MINUTES).minutes.do(cache_radarr)
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ schedule radarr: {e}")
    if SONARR_ENABLED and 'cache_sonarr' in globals():
        try: schedule.every(CACHE_REFRESH_MINUTES).minutes.do(cache_sonarr)
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ schedule sonarr: {e}")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting…")
    resolve_app_id()

    # Load dynamic modules
    loaded = []
    for mod, label, icon in [
        ("chat", "Chat", "💬"),
        ("weather", "Weather", "🌤️"),
        ("digest", "Digest", "📰"),
        ("uptimekuma", "Uptime Kuma", "📡"),
        # Technitium kept in Prime:
        ("technitium", "DNS", "🧬"),
    ]:
        m = try_load_module(mod, label, icon)
        if m: loaded.append(m)

    poster = format_startup_poster()
    send_message("Startup", poster, priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
