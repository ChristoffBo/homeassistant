import os, json, time, asyncio, requests, websockets, schedule, random, re, yaml
from tabulate import tabulate
from datetime import datetime, timezone

# -----------------------------
# Module imports (safe)
# -----------------------------
try:
    from arr import handle_arr_command, RADARR_ENABLED as ARR_RADARR, SONARR_ENABLED as ARR_SONARR, cache_radarr, cache_sonarr
except Exception as e:
    print(f"[Jarvis Jnr] ⚠️ Failed to load arr module: {e}")
    handle_arr_command = lambda cmd: ("⚠️ ARR module not available", None)
    ARR_RADARR = False
    ARR_SONARR = False
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

# 🔧 Pull module toggles from options.json/env
RADARR_ENABLED_OPT = os.getenv("radarr_enabled", "false").lower() in ("1", "true", "yes", "on")
SONARR_ENABLED_OPT = os.getenv("sonarr_enabled", "false").lower() in ("1", "true", "yes", "on")

# Effective states = env toggle AND arr module capability
RADARR_ENABLED = ARR_RADARR and RADARR_ENABLED_OPT
SONARR_ENABLED = ARR_SONARR and SONARR_ENABLED_OPT

jarvis_app_id = None  # resolved on startup

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
# Helpers: Human-readable size, runtime, greeting
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

# -----------------------------
# Send message (with APP token, supports extras)
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
        print(f"[{BOT_NAME}] ✅ Sent beautified: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to send message: {e}")
        return False

# -----------------------------
# Force Gotify client refresh (API poll)
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
# Purge all messages for a specific app (non-Jarvis)
# -----------------------------
def purge_app_messages(appid, appname=""):
    if not appid:
        return False
    url = f"{GOTIFY_URL}/application/{appid}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] 🗑 Purged all messages from app '{appname}' (id={appid})")
            force_refresh()
            return True
        else:
            print(f"[{BOT_NAME}] ❌ Purge failed for app '{appname}' (id={appid}): {r.status_code} {r.text}")
            return False
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging app {appid}: {e}")
        return False

# -----------------------------
# Purge all non-Jarvis apps
# -----------------------------
def purge_non_jarvis_apps():
    global jarvis_app_id
    if not jarvis_app_id:
        print(f"[{BOT_NAME}] ⚠️ Jarvis app_id not resolved, cannot purge non-Jarvis apps")
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
        force_refresh()
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging non-Jarvis apps: {e}")

# -----------------------------
# Resolve numeric app_id for Jarvis app
# -----------------------------
def resolve_app_id():
    global jarvis_app_id
    print(f"[{BOT_NAME}] Resolving app ID for app name: '{APP_NAME}'")
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        apps = r.json()
        for app in apps:
            print(f"[{BOT_NAME}] Found app '{app.get('name')}' (id={app.get('id')})")
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] ✅ MATCHED: '{APP_NAME}' -> id={jarvis_app_id}")
                return
        print(f"[{BOT_NAME}] ❌ WARNING: Could not find app '{APP_NAME}'")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

# -----------------------------
# Beautifier modules
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

            table = tabulate(
                [[movie, year, runtime, quality, size]],
                headers=["Title", "Year", "Runtime", "Quality", "Size"],
                tablefmt="github"
            )

            if "importfailed" in raw.lower():
                msg = f"⛔ RADARR IMPORT FAILED\n╾━━━━━━━━━━━━━━━━╼\n{table}\n🔴 ERROR: Import failed"
                return msg, extras

            msg = f"🎬 NEW MOVIE DOWNLOADED\n╾━━━━━━━━━━━━━━━━╼\n{table}\n🟢 SUCCESS: Added to collection"
            return msg, extras
    except Exception:
        pass

    if "importfailed" in raw.lower() or "error" in raw.lower():
        msg = f"⛔ RADARR ERROR\n╾━━━━━━━━━━━━━━━━╼\n{raw}"
    elif any(x in raw.lower() for x in ["downloaded", "imported", "grabbed"]):
        msg = f"🎬 NEW MOVIE DOWNLOADED\n╾━━━━━━━━━━━━━━━━╼\n{raw}\n🟢 SUCCESS: Added to collection"
    else:
        msg = f"📡 RADARR EVENT\n╾━━━━━━━━━━━━━━━━╼\n{raw}"
    return msg, extras

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

            table = tabulate(
                [[series, f"S{season:02}E{ep_num:02}", ep_title, runtime, quality, size]],
                headers=["Series", "Episode", "Title", "Runtime", "Quality", "Size"],
                tablefmt="github"
            )

            if "importfailed" in raw.lower():
                msg = f"⛔ SONARR IMPORT FAILED\n╾━━━━━━━━━━━━━━━━╼\n{table}\n🔴 ERROR: Import failed"
                return msg, extras

            if "subtitle" in raw.lower():
                msg = f"💬 SUBTITLES IMPORTED\n╾━━━━━━━━━━━━━━━━╼\n{table}\n🟢 SUCCESS: Subtitles available"
                return msg, extras

            msg = f"📺 NEW EPISODE AVAILABLE\n╾━━━━━━━━━━━━━━━━╼\n{table}\n🟢 SUCCESS: Ready for streaming"
            return msg, extras
    except Exception:
        pass

    if "importfailed" in raw.lower() or "error" in raw.lower():
        msg = f"⛔ SONARR ERROR\n╾━━━━━━━━━━━━━━━━╼\n{raw}"
    elif "subtitle" in raw.lower():
        msg = f"💬 SUBTITLES IMPORTED\n╾━━━━━━━━━━━━━━━━╼\n{raw}"
    elif any(x in raw.lower() for x in ["downloaded", "imported", "grabbed"]):
        msg = f"📺 NEW EPISODE AVAILABLE\n╾━━━━━━━━━━━━━━━━╼\n{raw}\n🟢 SUCCESS: Ready for streaming"
    else:
        msg = f"📡 SONARR EVENT\n╾━━━━━━━━━━━━━━━━╼\n{raw}"
    return msg, extras

def beautify_watchtower(title, raw):
    match = re.search(r"([\w./-]+):([\w.-]+)", raw)
    image = match.group(0) if match else "Unknown"
    if "error" in raw.lower() or "failed" in raw.lower():
        return f"⛔ CONTAINER UPDATE FAILED\n╾━━━━━━━━━━━━━━━━╼\n📦 Image: {image}\n🔴 ERROR: {raw}\n\n🛠 Action → Verify image or registry", None
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"🐳 CONTAINER UPDATE\n╾━━━━━━━━━━━━━━━━╼\n📦 Image: {image}\n🕒 Time: {now_str}\n\n🟢 SUCCESS: Container restarted successfully", None

def beautify_semaphore(title, raw):
    playbook = re.search(r"Playbook:\s*(.+)", raw)
    host = re.search(r"Host:\s*(.+)", raw)
    status = re.search(r"Status:\s*(.+)", raw)
    pb_val = playbook.group(1) if playbook else "Unknown"
    host_val = host.group(1) if host else "Unknown"
    status_val = status.group(1).upper() if status else "UNKNOWN"
    if "FAIL" in status_val or "ERROR" in status_val:
        return f"📊 SEMAPHORE TASK REPORT\n╾━━━━━━━━━━━━━━━━╼\n📂 Playbook: `{pb_val}`\n🖥 Host: {host_val}\n🔴 Status: {status_val}\n\n🛠 Action → Investigate failure", None
    return f"📊 SEMAPHORE TASK REPORT\n╾━━━━━━━━━━━━━━━━╼\n📂 Playbook: `{pb_val}`\n🖥 Host: {host_val}\n🟢 Status: {status_val}\n\n✨ All tasks completed successfully", None

def beautify_json(title, raw):
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            pretty_obj = {}
            for k, v in obj.items():
                if "size" in k.lower():
                    pretty_obj[k] = human_size(v)
                elif "time" in k.lower() or "runtime" in k.lower():
                    pretty_obj[k] = format_runtime(v)
                else:
                    pretty_obj[k] = v
            table = tabulate([pretty_obj], headers="keys", tablefmt="github")
            return f"📡 JSON EVENT REPORT\n╾━━━━━━━━━━━━━━━━╼\n{table}", None
    except Exception:
        return None, None
    return None, None

def beautify_yaml(title, raw):
    try:
        obj = yaml.safe_load(raw)
        if isinstance(obj, dict):
            pretty_obj = {}
            for k, v in obj.items():
                if "size" in k.lower():
                    pretty_obj[k] = human_size(v)
                elif "time" in k.lower() or "runtime" in k.lower():
                    pretty_obj[k] = format_runtime(v)
                else:
                    pretty_obj[k] = v
            table = tabulate([pretty_obj], headers="keys", tablefmt="github")
            return f"📡 YAML EVENT REPORT\n╾━━━━━━━━━━━━━━━━╼\n{table}", None
    except Exception:
        return None, None
    return None, None

def beautify_generic(title, raw):
    if "error" in raw.lower():
        return f"⛔ ERROR DETECTED\n╾━━━━━━━━━━━━━━━━╼\n{colorize(raw, 'error')}", None
    if "success" in raw.lower():
        return f"✅ SUCCESS\n╾━━━━━━━━━━━━━━━━╼\n{colorize(raw, 'success')}", None
    if "warning" in raw.lower():
        return f"⚠ WARNING\n╾━━━━━━━━━━━━━━━━╼\n{colorize(raw, 'warn')}", None
    return f"🛰 MESSAGE\n╾━━━━━━━━━━━━━━━━╼\n{raw}", None

# -----------------------------
# Main beautifier router
# -----------------------------
def beautify_message(title, raw):
    lower = raw.lower()
    result, extras = None, None
    if "radarr" in lower:
        result, extras = beautify_radarr(title, raw)
    elif "sonarr" in lower:
        result, extras = beautify_sonarr(title, raw)
    elif "watchtower" in lower or "docker" in lower:
        result, extras = beautify_watchtower(title, raw)
    elif "playbook" in lower or "semaphore" in lower:
        result, extras = beautify_semaphore(title, raw)
    elif beautify_json(title, raw)[0]:
        result, extras = beautify_json(title, raw)
    elif beautify_yaml(title, raw)[0]:
        result, extras = beautify_yaml(title, raw)
    else:
        result, extras = beautify_generic(title, raw)

    closings = [
        "🧠 Analysis complete — Jarvis Jnr",
        "⚡ Task executed at optimal efficiency",
        "✅ Operation verified — Jarvis Jnr",
        "🛰 Transmission relayed successfully",
        "📊 Report compiled and archived",
        "🔍 Inspection concluded — no anomalies",
        "⚙️ Automated response — Jarvis Jnr",
        "📡 Standing by for further input",
        "🖥 Process logged in memory",
        "🔒 Secure execution confirmed",
        "🌐 Status synchronized across network",
        "🚀 Operation finished — systems nominal",
        "🧩 Adaptive workflow complete",
        "🔧 Diagnostics stable",
        "📢 Notification delivered — AI core",
        "🎯 Objective reached successfully",
        "🔋 Energy levels optimal",
        "🛡 Defensive protocols active",
        "📎 Documented for future reference",
        "🏷 Indexed by Jarvis Jnr",
        "⏱ Execution time recorded",
        "📂 Archived in knowledge base",
        "🧑‍💻 Operator assistance provided",
        "🗂 Data classified securely",
        "🗝 Access log updated",
        "👁 Visual scan completed",
        "🛠 AI maintenance cycle closed",
        "💡 No anomalies detected",
        "✨ End of report — Jarvis Jnr",
        "🤖 Yours truly — Jarvis Jnr",
        "👑 Signed by Jarvis Jnr AI",
    ]
    return f"{result}\n\n{random.choice(closings)}", extras

# -----------------------------
# Scheduled cleanup
# -----------------------------
def run_scheduler():
    schedule.every(5).minutes.do(purge_non_jarvis_apps)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Main async listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url += f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting to {ws_url}...")

    try:
        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
            print(f"[{BOT_NAME}] ✅ Connected! Listening for messages...")

            async for msg in ws:
                try:
                    data = json.loads(msg)
                    mid = data.get("id")
                    appid = data.get("appid")
                    title = data.get("title", "")
                    message = data.get("message", "")

                    print(f"[{BOT_NAME}] Incoming message id={mid}, appid={appid}, title='{title}'")

                    if jarvis_app_id and appid == jarvis_app_id:
                        continue

                    # Wake word handling
                    if message.lower().startswith("jarvis"):
                        response, extras = handle_arr_command(message.replace("jarvis","",1).strip())
                        if response:
                            send_message("Jarvis Module", response, extras=extras)
                            continue

                    if BEAUTIFY_ENABLED:
                        final_msg, extras = beautify_message(title, message)
                    else:
                        final_msg, extras = message, None

                    repost_priority = 0 if SILENT_REPOST else 5
                    send_success = send_message(title, final_msg, priority=repost_priority, extras=extras)

                    if send_success:
                        print(f"[{BOT_NAME}] ✅ Reposted beautified message")
                        purge_non_jarvis_apps()

                except Exception as e:
                    print(f"[{BOT_NAME}] ❌ Error processing message: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ WebSocket connection failed: {e}")
        await asyncio.sleep(10)
        await listen()

# -----------------------------
# Main entrypoint
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on...")

    resolve_app_id()

    greeting = get_greeting()
    send_message("Greeting", f"{greeting}, Commander! Jarvis Jnr reporting for duty.", priority=5)

    startup_msgs = [
        f"{greeting}, Commander!\n╾━━━━━━━━━━━━━━━━╼\n🤖 Jarvis Jnr is online\n🛡 Defense protocols armed\n🧠 Intelligence kernel active",
        f"{greeting} — Systems Check Complete\n╾━━━━━━━━━━━━━━━━╼\n✅ Diagnostics clean\n📂 Knowledge base loaded\n📡 Event pipeline secure",
        f"{greeting} — Link Established\n╾━━━━━━━━━━━━━━━━╼\n🌐 Network sync stable\n⚡ Rapid response ready\n🔒 Encryption validated",
        f"{greeting} — Core Engaged\n╾━━━━━━━━━━━━━━━━╼\n📊 Metrics calibrated\n🔭 Horizon scan clear\n🎯 Objective lock established",
        f"{greeting} — Boot Sequence Complete\n╾━━━━━━━━━━━━━━━━╼\n🔧 Subsystems aligned\n📡 Channels open\n👑 Jarvis Jnr reporting for duty",
    ]
    send_message("Startup", random.choice(startup_msgs), priority=5)

    # Report active modules + run cache
    active_modules = []
    if RADARR_ENABLED:
        active_modules.append("🎬 Radarr")
        try: cache_radarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Radarr cache failed: {e}")
    if SONARR_ENABLED:
        active_modules.append("📺 Sonarr")
        try: cache_sonarr()
        except Exception as e: print(f"[{BOT_NAME}] ⚠️ Sonarr cache failed: {e}")

    if active_modules:
        send_message("Modules", "✅ Active Modules: " + ", ".join(active_modules), priority=5)
    else:
        send_message("Modules", "⚠️ No external modules enabled", priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
