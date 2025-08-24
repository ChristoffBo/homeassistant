import os, json, time, asyncio, requests, websockets, schedule, random, re, yaml
from tabulate import tabulate
from datetime import datetime, timezone

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
# Send message (with APP token)
# -----------------------------
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": message,
        "priority": priority,
    }
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent beautified: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to send message: {e}")
        return False

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
    return f"🎬 NEW MOVIE DOWNLOADED\n╾━━━━━━━━━━━━━━━━╼\n🎞 {raw}\n\n🟢 SUCCESS: Added to collection"

def beautify_sonarr(title, raw):
    return f"📺 NEW EPISODE AVAILABLE\n╾━━━━━━━━━━━━━━━━╼\n📌 {raw}\n\n🟢 SUCCESS: Ready for streaming"

def beautify_watchtower(title, raw):
    match = re.search(r"([\w./-]+):([\w.-]+)", raw)
    image = match.group(0) if match else "Unknown"
    if "error" in raw.lower() or "failed" in raw.lower():
        return f"⛔ CONTAINER UPDATE FAILED\n╾━━━━━━━━━━━━━━━━╼\n📦 Image: {image}\n🔴 ERROR: {raw}\n\n🛠 Action → Verify image or registry"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"🐳 CONTAINER UPDATE\n╾━━━━━━━━━━━━━━━━╼\n📦 Image: {image}\n🕒 Time: {now_str}\n\n🟢 SUCCESS: Container restarted successfully"

def beautify_semaphore(title, raw):
    playbook = re.search(r"Playbook:\s*(.+)", raw)
    host = re.search(r"Host:\s*(.+)", raw)
    status = re.search(r"Status:\s*(.+)", raw)
    pb_val = playbook.group(1) if playbook else "Unknown"
    host_val = host.group(1) if host else "Unknown"
    status_val = status.group(1).upper() if status else "UNKNOWN"
    if "FAIL" in status_val or "ERROR" in status_val:
        return f"📊 SEMAPHORE TASK REPORT\n╾━━━━━━━━━━━━━━━━╼\n📂 Playbook: `{pb_val}`\n🖥 Host: {host_val}\n🔴 Status: {status_val}\n\n🛠 Action → Investigate failure"
    return f"📊 SEMAPHORE TASK REPORT\n╾━━━━━━━━━━━━━━━━╼\n📂 Playbook: `{pb_val}`\n🖥 Host: {host_val}\n🟢 Status: {status_val}\n\n✨ All tasks completed successfully"

def beautify_json(title, raw):
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            table = tabulate([obj], headers="keys", tablefmt="github")
            return f"📡 JSON EVENT REPORT\n╾━━━━━━━━━━━━━━━━╼\n{table}"
    except Exception:
        return None
    return None

def beautify_yaml(title, raw):
    try:
        obj = yaml.safe_load(raw)
        if isinstance(obj, dict):
            table = tabulate([obj], headers="keys", tablefmt="github")
            return f"📡 YAML EVENT REPORT\n╾━━━━━━━━━━━━━━━━╼\n{table}"
    except Exception:
        return None
    return None

def beautify_generic(title, raw):
    if "error" in raw.lower():
        return f"⛔ ERROR DETECTED\n╾━━━━━━━━━━━━━━━━╼\n{colorize(raw, 'error')}"
    if "success" in raw.lower():
        return f"✅ SUCCESS\n╾━━━━━━━━━━━━━━━━╼\n{colorize(raw, 'success')}"
    if "warning" in raw.lower():
        return f"⚠ WARNING\n╾━━━━━━━━━━━━━━━━╼\n{colorize(raw, 'warn')}"
    return f"🛰 MESSAGE\n╾━━━━━━━━━━━━━━━━╼\n{raw}"

# -----------------------------
# Main beautifier router
# -----------------------------
def beautify_message(title, raw):
    lower = raw.lower()
    result = None
    if "radarr" in lower:
        result = beautify_radarr(title, raw)
    elif "sonarr" in lower:
        result = beautify_sonarr(title, raw)
    elif "watchtower" in lower or "docker" in lower:
        result = beautify_watchtower(title, raw)
    elif "playbook" in lower or "semaphore" in lower:
        result = beautify_semaphore(title, raw)
    elif beautify_json(title, raw):
        result = beautify_json(title, raw)
    elif beautify_yaml(title, raw):
        result = beautify_yaml(title, raw)
    else:
        result = beautify_generic(title, raw)

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
        "🧬 Neural pathways stable",
        "🛰 Signal integrity verified",
        "⚡ Latency minimized",
        "🔭 Horizon scan clear",
        "📡 Event pipeline secure",
        "🛡 Notification shield active",
        "🎛 Systems calibrated",
        "🔓 Trust chain validated",
        "🧠 Pattern recognition complete",
        "📊 Metrics logged",
        "🔍 Deep scan finished",
        "⚙️ Self-adjustment executed",
        "🛰 Orbit stabilized",
        "🚨 Alert cycle completed",
        "📡 Transmission closed",
        "🔒 Encryption maintained",
        "🧩 Modular process complete",
        "📢 Event cycle terminated",
        "🎯 Precision maintained",
        "🔧 Maintenance complete",
        "🛠 Systems checked",
        "📂 Data safely stored",
        "👑 Signed by Jarvis Jnr AI",
    ]
    return f"{result}\n\n{random.choice(closings)}"

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

                    # Skip Jarvis's own messages
                    if jarvis_app_id and appid == jarvis_app_id:
                        print(f"[{BOT_NAME}] Skipping own message id={mid}")
                        continue

                    # Beautify if enabled
                    if BEAUTIFY_ENABLED:
                        final_msg = beautify_message(title, message)
                    else:
                        final_msg = message

                    repost_priority = 0 if SILENT_REPOST else 5
                    send_success = send_message(title, final_msg, priority=repost_priority)

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

    startup_msgs = [
        "🤖 JARVIS JNR ONLINE — Systems nominal",
        "🚀 Boot complete — AI core active",
        "🛰 Stream uplink established",
        "✅ Diagnostics clean, standing by",
        "📡 Event pipeline secure",
        "⚡ Neural systems engaged",
        "🔧 Initialization complete",
        "🌐 Network sync stable",
        "🛡 Defense subsystems ready",
        "✨ Adaptive AI cycle online",
        "📊 Metrics calibrated",
        "🧠 Intelligence kernel active",
        "🔋 Energy flow stable",
        "📂 Knowledge base loaded",
        "🎯 Objective lock established",
        "🔭 Horizon scan active",
        "📎 Notification hooks attached",
        "🗝 Secure channel ready",
        "🛰 Satellite link optimal",
        "🚨 Monitoring all systems",
        "🔍 Pattern recognition enabled",
        "🎛 Subroutines aligned",
        "🧬 Neural weave steady",
        "🔒 Trust chain validated",
        "📢 Broadcast channel live",
        "🛠 Maintenance check passed",
        "🧑‍💻 Operator link ready",
        "📡 Communication channel clear",
        "💡 Intelligence awakened",
        "👑 Jarvis Jnr reporting for duty",
        "🛰 AI uplink locked — streams secure",
        "⚡ Rapid response core online",
        "✨ Neural calibration complete",
        "📊 Event filters primed",
        "🛡 Intrusion detection ready",
        "🚀 Velocity mode engaged",
        "📡 Wideband listening enabled",
        "🔧 Auto-tuning modules online",
        "🔋 Battery reserves full",
        "🔭 Long-range scan clean",
        "🧠 Memory cache optimized",
        "🌐 Multi-network sync done",
        "📎 AI hooks aligned",
        "🔒 Encryption handshakes valid",
        "⚡ Power flows balanced",
        "🛠 Repair cycles green",
        "🎯 Targets monitored",
        "🧬 DNA patterns locked",
        "📢 Notification broadcast open",
        "👁 Surveillance optimal",
        "🚨 Emergency channel hot",
    ]
    send_message("Startup", random.choice(startup_msgs), priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
