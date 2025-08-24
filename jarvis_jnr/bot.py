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
    handle_arr_command = lambda cmd: ("⚠️ ARR module not available", None)
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
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")

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
    hour = datetime.now().hour
    if hour < 12:
        return "☀️ Good morning"
    elif hour < 18:
        return "🌤 Good afternoon"
    else:
        return "🌙 Good evening"

def get_settings_summary():
    settings = [
        (f"⏳ retention_hours = {RETENTION_HOURS}", "Hours messages are kept before purge"),
        (f"🤫 silent_repost = {SILENT_REPOST}", "Skip reposting if duplicate"),
        (f"🎨 beautify_enabled = {BEAUTIFY_ENABLED}", "Beautify and repost messages"),
        (f"🎬 radarr_enabled = {RADARR_ENABLED}", "Radarr module active"),
        (f"📺 sonarr_enabled = {SONARR_ENABLED}", "Sonarr module active"),
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
    """Purge Jarvis' own messages based on retention hours silently."""
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
# Beautifiers (FULL)
# -----------------------------
def beautify_radarr(title, raw):
    img_match = re.search(r"(https?://\S+\.(?:jpg|png|jpeg))", raw)
    img_url = img_match.group(1) if img_match else None
    extras = {"client::notification": {"bigImageUrl": img_url}} if img_url else None
    try:
        obj = json.loads(raw)
        if "movie" in obj:
            movie = obj["movie"].get("title", "Unknown Movie")
            year = obj["movie"].get("year", "")
            runtime = format_runtime(obj["movie"].get("runtime", 0))
            quality = obj.get("release", {}).get("quality", "Unknown")
            size = human_size(obj.get("release", {}).get("size", 0))
            table = tabulate([[movie, year, runtime, quality, size]], headers=["Title","Year","Runtime","Quality","Size"], tablefmt="github")
            if "importfailed" in raw.lower():
                return f"⛔ RADARR IMPORT FAILED\n{table}", extras
            return f"🎬 NEW MOVIE\n{table}", extras
    except Exception:
        pass
    return f"📡 RADARR EVENT\n{raw}", extras

def beautify_sonarr(title, raw):
    img_match = re.search(r"(https?://\S+\.(?:jpg|png|jpeg))", raw)
    img_url = img_match.group(1) if img_match else None
    extras = {"client::notification": {"bigImageUrl": img_url}} if img_url else None
    try:
        obj = json.loads(raw)
        if "episode" in obj:
            series = obj.get("series", {}).get("title", "Unknown Series")
            ep_title = obj["episode"].get("title", "Unknown Episode")
            season = obj["episode"].get("seasonNumber", "?")
            ep_num = obj["episode"].get("episodeNumber", "?")
            runtime = format_runtime(obj["episode"].get("runtime", 0))
            quality = obj.get("release", {}).get("quality", "Unknown")
            size = human_size(obj.get("release", {}).get("size", 0))
            table = tabulate([[series, f"S{season:02}E{ep_num:02}", ep_title, runtime, quality, size]], headers=["Series","Episode","Title","Runtime","Quality","Size"], tablefmt="github")
            return f"📺 NEW EPISODE\n{table}", extras
    except Exception:
        pass
    return f"📡 SONARR EVENT\n{raw}", extras

def beautify_watchtower(title, raw):
    return f"🐳 WATCHTOWER\n{raw}", None

def beautify_semaphore(title, raw):
    return f"📊 SEMAPHORE\n{raw}", None

def beautify_json(title, raw):
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            table = tabulate([obj], headers="keys", tablefmt="github")
            return f"📡 JSON EVENT\n{table}", None
    except Exception:
        return None, None
    return None, None

def beautify_yaml(title, raw):
    try:
        obj = yaml.safe_load(raw)
        if isinstance(obj, dict):
            table = tabulate([obj], headers="keys", tablefmt="github")
            return f"📡 YAML EVENT\n{table}", None
    except Exception:
        return None, None
    return None, None

def beautify_generic(title, raw):
    return f"🛰 MESSAGE\n{raw}", None

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
    schedule.every(5).seconds.do(purge_non_jarvis_apps)   # fast purge others
    schedule.every(RETENTION_HOURS).hours.do(purge_all_messages)  # retention purge
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

                    # ADDITIVE FIX: ignore own messages
                    appid = data.get("appid")
                    if appid == jarvis_app_id:
                        continue

                    title = data.get("title","")
                    message = data.get("message","")
                    if message.lower().startswith("jarvis"):
                        response, extras = handle_arr_command(message.replace("jarvis","",1).strip())
                        if response: send_message("Jarvis", response, extras=extras); continue
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
    enabled = os.getenv(f"{modname.upper()}_ENABLED", "false").lower() in ("1", "true", "yes")
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
    startup_msgs = [
        f"{greeting}, Commander! 🤖 Jarvis Jnr is online",
        f"{greeting} — Systems check complete",
        f"{greeting} — Boot sequence done",
        f"{greeting} — Awaiting your first command",
        f"{greeting} — Online and operational",
        f"{greeting} — Ready to execute tasks",
        f"{greeting} — AI systems stable",
        f"{greeting} — All modules nominal",
        f"{greeting} — Standing by",
        f"{greeting} — Boot complete, monitoring systems",
        f"{greeting} — Your AI assistant is awake",
        f"{greeting} — Self-check passed, ready for input",
        f"{greeting} — Neural routines initialized",
        f"{greeting} — Connected and synchronized",
        f"{greeting} — Logging initialized",
        f"{greeting} — Status: Green across all systems",
        f"{greeting} — No anomalies detected",
        f"{greeting} — Communication link established",
        f"{greeting} — Directives loaded",
        f"{greeting} — Mission parameters clear",
        f"{greeting} — AI cognition stable",
        f"{greeting} — Situational awareness online",
        f"{greeting} — All channels monitored",
        f"{greeting} — Power levels optimal",
        f"{greeting} — Data streams stable",
        f"{greeting} — Integrity checks clean",
        f"{greeting} — Running smooth, no errors",
        f"{greeting} — Fully locked and synchronized",
        f"{greeting} — Central core running optimal",
        f"{greeting} — Handshake complete, commander",
        f"{greeting} — Prepared for system oversight",
    ]

    startup_message = random.choice(startup_msgs) + "\n\n" + get_settings_summary()

    active = []
    if RADARR_ENABLED:
        active.append("🎬 Radarr")
        try: cache_radarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Radarr cache failed {e}")
    if SONARR_ENABLED:
        active.append("📺 Sonarr")
        try: cache_sonarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Sonarr cache failed {e}")

    # Dynamically check optional modules
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
