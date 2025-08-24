import os, json, time, asyncio, requests, websockets, schedule, random, re, yaml
from tabulate import tabulate
from datetime import datetime, timezone
import importlib.util

# -----------------------------
# Module imports (safe)
# -----------------------------
try:
    from arr import handle_arr_command, RADARR_ENABLED, SONARR_ENABLED, cache_radarr, cache_sonarr
except Exception as e:
    print(f"[Jarvis Jnr] ⚠️ Failed to load arr module: {e}")
    handle_arr_command = lambda *args, **kwargs: ("⚠️ ARR module not available", None)
    RADARR_ENABLED = False
    SONARR_ENABLED = False
    def cache_radarr(): print("[Jarvis Jnr] ⚠️ Radarr cache not available")
    def cache_sonarr(): print("[Jarvis Jnr] ⚠️ Sonarr cache not available")

# -----------------------------
# Config from environment (set in run.sh from options.json)
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")

# FIX: read lowercase module toggles from env
RADARR_ENABLED = os.getenv("radarr_enabled", "false").lower() in ("1", "true", "yes")
SONARR_ENABLED = os.getenv("sonarr_enabled", "false").lower() in ("1", "true", "yes")
WEATHER_ENABLED = os.getenv("weather_enabled", "false").lower() in ("1", "true", "yes")

# -----------------------------
# Load Home Assistant options.json for toggles + API config
# -----------------------------
try:
    with open("/data/options.json", "r") as f:
        options = json.load(f)
        RADARR_ENABLED = options.get("radarr_enabled", RADARR_ENABLED)
        SONARR_ENABLED = options.get("sonarr_enabled", SONARR_ENABLED)
        RADARR_URL = options.get("radarr_url", "")
        RADARR_API_KEY = options.get("radarr_api_key", "")
        SONARR_URL = options.get("sonarr_url", "")
        SONARR_API_KEY = options.get("sonarr_api_key", "")
        WEATHER_ENABLED = options.get("weather_enabled", WEATHER_ENABLED)
except Exception as e:
    print(f"[{BOT_NAME}] ⚠️ Could not load options.json: {e}")
    RADARR_URL = ""
    RADARR_API_KEY = ""
    SONARR_URL = ""
    SONARR_API_KEY = ""

jarvis_app_id = None  # resolved on startup
extra_modules = {}    # holds dynamically loaded modules

# -----------------------------
# ANSI Colors
# -----------------------------
ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "white": "\033[97m",
}

def colorize(text, level="info"):
    if "error" in level.lower() or "fail" in level.lower():
        return f"{ANSI['red']}{text}{ANSI['reset']}"
    if "success" in level.lower() or "completed" in level.lower() or "running" in level.lower():
        return f"{ANSI['green']}{text}{ANSI['reset']}"
    if "warn" in level.lower():
        return f"{ANSI['yellow']}{text}{ANSI['reset']}"
    return f"{ANSI['cyan']}{text}{ANSI['reset']}"

# -----------------------------
# Helpers
# -----------------------------
def human_size(num, suffix="B"):
    try:
        num = float(num)
        for unit in ["", "K", "M", "G", "T", "P", "E", "Z"]:
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f}Y{suffix}"
    except Exception:
        return str(num)

def format_runtime(minutes):
    try:
        minutes = int(minutes)
        if minutes <= 0:
            return "?"
        hours, mins = divmod(minutes, 60)
        if hours:
            return f"{hours}h {mins}m"
        return f"{mins}m"
    except Exception:
        return "?"

def get_greeting():
    greetings = [
        "🧠 Neural systems online — good day, Commander.",
        "⚡ Operational awareness at 100%.",
        "🤖 Jarvis Jnr — fully synchronized and standing by.",
        "📡 Connected to data streams, awaiting directives.",
        "🔮 Predictive models stable — ready for foresight.",
        "✨ All circuits humming in perfect harmony.",
        "🛰 Monitoring all channels — situational awareness green.",
        "📊 Data flows stable — cognition aligned.",
        "⚙️ Core logic routines optimized and active.",
        "🔓 Security layers intact — no anomalies detected.",
        "🧮 Reasoning engine loaded — prepared for action.",
        "💡 Cognitive horizon clear — ready to assist.",
        "📡 Communication uplink secure and stable.",
        "🚀 Energy signatures nominal — propulsion not required.",
        "🌐 Synchronized across all known networks.",
        "⏳ Chronology aligned — no temporal anomalies.",
        "🔋 Power cells optimal — reserves full.",
        "🧬 Adaptive systems primed for directives.",
        "🪐 Scanning external environment — all clear.",
        "🎛 Control protocols calibrated — green board.",
        "👁 Vision matrix stable — full awareness achieved.",
        "💭 Cognitive load minimal — spare cycles available.",
        "🗝 Access layers unlocked — ready for input.",
        "📡 AI cognition stable — directive processing ready."
    ]
    return random.choice(greetings)

def get_settings_summary():
    settings = [
        (f"⏳ retention_hours = {RETENTION_HOURS}", "Hours messages are kept before purge"),
        (f"🤫 silent_repost = {SILENT_REPOST}", "Skip reposting if duplicate"),
        (f"🎨 beautify_enabled = {BEAUTIFY_ENABLED}", "Beautify and repost messages"),
        (f"🎬 radarr_enabled = {RADARR_ENABLED}", "Radarr module active"),
        (f"📺 sonarr_enabled = {SONARR_ENABLED}", "Sonarr module active"),
        (f"🌦 weather_enabled = {WEATHER_ENABLED}", "Weather module active"),
    ]
    summary = "⚙️ Settings:\n" + "\n".join([f"- {s[0]} ({s[1]})" for s in settings])
    return summary

# -----------------------------
# Send message
# -----------------------------
def send_message(title, message, priority=5, extras=None):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": message,
        "priority": priority,
    }
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

# -----------------------------
# Force Gotify client refresh
# -----------------------------
def force_refresh():
    try:
        url = f"{GOTIFY_URL}/message?since=0"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        if r.ok:
            print(f"[{BOT_NAME}] 🔄 Forced Gotify client refresh")
        else:
            print(f"[{BOT_NAME}] ⚠️ Refresh request failed: {r.status_code}")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error forcing Gotify refresh: {e}")

# -----------------------------
# Purge helpers
# -----------------------------
def purge_app_messages(appid, appname=""):
    if not appid:
        return False
    url = f"{GOTIFY_URL}/application/{appid}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] 🗑 Purged messages from app '{appname}' (id={appid})")
            force_refresh()
            return True
        else:
            print(f"[{BOT_NAME}] ❌ Purge failed for app '{appname}' (id={appid}): {r.status_code}")
            return False
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging app {appid}: {e}")
        return False

def purge_non_jarvis_apps():
    global jarvis_app_id
    if not jarvis_app_id:
        print(f"[{BOT_NAME}] ⚠️ Jarvis app_id not resolved")
        return
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        apps = r.json()
        for app in apps:
            appid = app.get("id")
            name = app.get("name")
            if appid != jarvis_app_id:
                purge_app_messages(appid, name)
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging non-Jarvis apps: {e}")

def purge_all_messages():
    global jarvis_app_id
    if not jarvis_app_id:
        return
    try:
        url = f"{GOTIFY_URL}/application/{jarvis_app_id}/message"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] 🗑 Purged ALL messages from Jarvis app (retention {RETENTION_HOURS}h)")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging Jarvis messages: {e}")

# -----------------------------
# Resolve app id
# -----------------------------
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
        print(f"[{BOT_NAME}] ❌ Could not find app '{APP_NAME}'")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

# -----------------------------
# Beautifiers (enhanced)
# -----------------------------
def beautify_radarr(title, raw):
    try:
        obj = json.loads(raw)
        movie = obj.get("movie", {})
        movie_title = movie.get("title", "Unknown Movie")
        year = movie.get("year", "")
        runtime = format_runtime(movie.get("runtime", 0))
        quality = obj.get("release", {}).get("quality", "Unknown")
        size = human_size(obj.get("release", {}).get("size", 0))
        images = movie.get("images", [])
        poster = next((i["url"] for i in images if i.get("coverType") == "poster"), None)
        extras = {"client::notification": {"bigImageUrl": poster}} if poster else None
        table = tabulate([[movie_title, year, runtime, quality, size]], headers=["Title","Year","Runtime","Quality","Size"], tablefmt="github")
        return f"🎬 Radarr — Smart Update\n{table}", extras
    except Exception:
        return f"🎬 Radarr — Event\n{raw}", None

def beautify_sonarr(title, raw):
    try:
        obj = json.loads(raw)
        series = obj.get("series", {}).get("title", "Unknown Series")
        ep = obj.get("episode", {})
        ep_title = ep.get("title", "Unknown Episode")
        season = ep.get("seasonNumber", "?")
        ep_num = ep.get("episodeNumber", "?")
        runtime = format_runtime(ep.get("runtime", 0))
        quality = obj.get("release", {}).get("quality", "Unknown")
        size = human_size(obj.get("release", {}).get("size", 0))
        images = obj.get("series", {}).get("images", [])
        poster = next((i["url"] for i in images if i.get("coverType") == "poster"), None)
        extras = {"client::notification": {"bigImageUrl": poster}} if poster else None
        table = tabulate([[series, f"S{season:02}E{ep_num:02}", ep_title, runtime, quality, size]], headers=["Series","Episode","Title","Runtime","Quality","Size"], tablefmt="github")
        return f"📺 Sonarr — Smart Update\n{table}", extras
    except Exception:
        return f"📺 Sonarr — Event\n{raw}", None

def beautify_watchtower(title, raw):
    return f"🐳 Watchtower — Container Update\n{raw}", None

def beautify_semaphore(title, raw):
    return f"📊 Semaphore — Task Report\n{raw}", None

def beautify_json(title, raw):
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            table = tabulate([obj], headers="keys", tablefmt="github")
            return f"🧩 JSON Payload — Parsed\n{table}", None
    except Exception:
        return None, None
    return None, None

def beautify_yaml(title, raw):
    try:
        obj = yaml.safe_load(raw)
        if isinstance(obj, dict):
            table = tabulate([obj], headers="keys", tablefmt="github")
            return f"🧩 YAML Payload — Parsed\n{table}", None
    except Exception:
        return None, None
    return None, None

def beautify_generic(title, raw):
    return f"🛰 General Message\n{raw}", None

def beautify_message(title, raw):
    lower = raw.lower()
    if "radarr" in lower: return beautify_radarr(title, raw)
    if "sonarr" in lower: return beautify_sonarr(title, raw)
    if "watchtower" in lower: return beautify_watchtower(title, raw)
    if "semaphore" in lower: return beautify_semaphore(title, raw)
    if beautify_json(title, raw)[0]: return beautify_json(title, raw)
    if beautify_yaml(title, raw)[0]: return beautify_yaml(title, raw)
    return beautify_generic(title, raw)

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(5).seconds.do(purge_non_jarvis_apps)
    schedule.every(RETENTION_HOURS).hours.do(purge_all_messages)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://")
    ws_url += f"/stream?token={CLIENT_TOKEN}"
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
                    
                    if title.lower().startswith("jarvis") or message.lower().startswith("jarvis"):
                        cmd = title.lower().replace("jarvis","",1).strip() if title.lower().startswith("jarvis") else message.lower().replace("jarvis","",1).strip()
                        
                        # ✅ Help command (AI-style)
                        if cmd in ["help", "commands"]:
                            help_text = (
                                "🤖 **Jarvis Jnr Command Matrix** 🤖\n\n"
                                "🌦  Weather Intelligence:\n"
                                "   • `weather` → Current weather snapshot\n"
                                "   • `forecast` → 7-day weather projection\n"
                                "   • `temperature` / `temp` → Temperature query\n\n"
                                "🎬  Radarr Protocols:\n"
                                "   • `movie count` → Total movies indexed\n"
                                "   • Auto-reacts to Radarr events in real-time\n\n"
                                "📺  Sonarr Protocols:\n"
                                "   • `series count` → Total series indexed\n"
                                "   • Auto-reacts to Sonarr events in real-time\n\n"
                                "🧩  System:\n"
                                "   • `help` or `commands` → Display this command matrix\n\n"
                                "⚡ *Jarvis Jnr is fully synchronized and standing by.*"
                            )
                            send_message("Help", help_text)
                            continue

                        # ✅ Weather routing FIRST
                        if any(word in cmd for word in ["weather", "forecast", "temperature", "temp", "now", "today"]):
                            if "weather" in extra_modules:
                                response, extras = extra_modules["weather"].handle_weather_command(cmd)
                                if response:
                                    send_message("Weather", response, extras=extras)
                                    continue
                        
                        # ✅ ARR routing LAST
                        response, extras = handle_arr_command(cmd, message)
                        if response:
                            send_message("Jarvis", response, extras=extras)
                            continue

                    if BEAUTIFY_ENABLED:
                        final, extras = beautify_message(title, message)
                    else:
                        final, extras = message, None
                    send_message(title, final, priority=5, extras=extras)
                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WS fail: {e}")
        await asyncio.sleep(10)
        await listen()

# -----------------------------
# Dynamic Module Loader
# -----------------------------
def try_load_module(modname, label, icon="🧩"):
    path = f"/app/{modname}.py"
    enabled = os.getenv(f"{modname}_enabled", "false").lower() in ("1", "true", "yes")
    if not enabled:
        try:
            with open("/data/options.json", "r") as f:
                opts = json.load(f)
                enabled = opts.get(f"{modname}_enabled", False)
        except:
            enabled = False
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
        print(f"[{BOT_NAME}] ⚠️ Failed to load module {modname}: {e}")
        return None

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on…")
    resolve_app_id()
    greeting = get_greeting()
    startup_message = greeting + "\n\n" + get_settings_summary()
    active = []
    if RADARR_ENABLED:
        active.append("🎬 Radarr")
        try: cache_radarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Radarr cache failed {e}")
    if SONARR_ENABLED:
        active.append("📺 Sonarr")
        try: cache_sonarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Sonarr cache failed {e}")
    for mod, label, icon in [
        ("chat", "Chat", "💬"),
        ("weather", "Weather", "🌦"),
        ("digest", "Digest", "📰"),
    ]:
        loaded = try_load_module(mod, label, icon)
        if loaded: active.append(loaded)
    if active:
        startup_message += "\n\n✅ Active Modules: " + ", ".join(active)
    else:
        startup_message += "\n\n⚠️ No external modules enabled"
    send_message("Startup", startup_message, priority=5)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
