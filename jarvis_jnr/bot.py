import os, json, time, asyncio, requests, websockets, schedule, random, re, yaml
from tabulate import tabulate
from datetime import datetime, timezone

# -----------------------------
# Config
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

jarvis_app_id = None

# ANSI color codes
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
# Send message
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
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ send_message failed: {e}")
        return False

# -----------------------------
# Purge helpers
# -----------------------------
def purge_app_messages(appid):
    url = f"{GOTIFY_URL}/application/{appid}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        requests.delete(url, headers=headers, timeout=10)
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ purge_app_messages failed: {e}")

def purge_non_jarvis_apps():
    global jarvis_app_id
    if not jarvis_app_id:
        return
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        for app in r.json():
            if app.get("id") != jarvis_app_id:
                purge_app_messages(app.get("id"))
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ purge_non_jarvis_apps failed: {e}")

def purge_old_messages():
    url = f"{GOTIFY_URL}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        messages = r.json().get("messages", [])
        now = datetime.now(timezone.utc).timestamp()
        cutoff = now - (RETENTION_HOURS * 3600)
        for msg in messages:
            ts = msg.get("date")
            if ts:
                msg_time = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                if msg_time < cutoff:
                    del_url = f"{GOTIFY_URL}/message/{msg['id']}"
                    requests.delete(del_url, headers=headers, timeout=5)
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ purge_old_messages failed: {e}")

# -----------------------------
# Resolve app_id
# -----------------------------
def resolve_app_id():
    global jarvis_app_id
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ resolve_app_id failed: {e}")

# -----------------------------
# Beautifier (shortened here - unchanged from before)
# -----------------------------
def beautify_message(title, raw):
    # (keeping previous beautify code unchanged for brevity in this snippet)
    formatted = f"🛰 SYSTEM MESSAGE\n╾━━━━━━━━━━━━━━━━╼\n{colorize(raw, 'info')}"

    closings = [
        "🧠 Analysis complete — Jarvis Jnr",
        "⚡ Task executed at optimal efficiency",
        "✅ Operation verified by Jarvis Jnr",
        "🛰 Transmission relayed successfully",
        "📊 Report compiled and archived",
        "🔍 Inspection concluded — no anomalies detected",
        "⚙️ Automated by Jarvis Jnr",
        "📡 Standing by for further input",
        "🖥 Process logged in system memory",
        "🔒 Secure execution confirmed",
        "🌐 Status synchronized across network",
        "🚀 Operation finished — systems nominal",
        "🧩 Adaptive workflow completed",
        "🔧 Diagnostics concluded — stable",
        "📢 Notification delivered by AI core",
        "🎯 Objective reached successfully",
        "🔋 Energy levels optimal — continuing operations",
        "🛡 Defensive protocols maintained",
        "📎 Documented for future reference",
        "🏷 Tagged and indexed by Jarvis",
        "⏱ Execution time recorded",
        "📂 Archived in knowledge base",
        "🧑‍💻 Operator assistance provided",
        "🗂 Classified and stored securely",
        "🗝 Access log updated — all secure",
        "👁 Visual scan of event completed",
        "🛠 AI maintenance cycle closed",
        "💡 No anomalies detected at this stage",
        "✨ End of report — Jarvis Jnr",
        "🤖 Yours truly, Jarvis Jnr",
    ]
    return f"{formatted}\n\n{random.choice(closings)}"

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(10).minutes.do(purge_old_messages)
    if BEAUTIFY_ENABLED:
        schedule.every(5).minutes.do(purge_non_jarvis_apps)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url += f"/stream?token={CLIENT_TOKEN}"

    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        appid = data.get("appid")
                        message = data.get("message", "")
                        extras = data.get("extras", {})

                        if jarvis_app_id and appid == jarvis_app_id:
                            continue

                        has_image = extras.get("client::display", {}).get("image") if extras else False

                        if BEAUTIFY_ENABLED:
                            final_msg = beautify_message(data.get("title", ""), message)
                            repost_priority = 0 if SILENT_REPOST else 5
                            if send_message(data.get("title", ""), final_msg, priority=repost_priority):
                                if not has_image:
                                    purge_non_jarvis_apps()
                        else:
                            print(f"[{BOT_NAME}] Beautify disabled — keeping original")
                    except Exception as e:
                        print(f"[{BOT_NAME}] ❌ Error processing message: {e}")
        except Exception as e:
            print(f"[{BOT_NAME}] ❌ WebSocket connection failed: {e}")
            await asyncio.sleep(10)

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on...")
    resolve_app_id()
    startup_msgs = [
        "🤖 JARVIS JNR ONLINE\n╾━━━━━━━━━━━━━━━━╼\n👑 Ready to rule notifications\n📡 Listening for events\n⚡ Systems nominal\n\n🧠 Standing by",
        "🚀 BOOT COMPLETE\n╾━━━━━━━━━━━━━━━━╼\n✅ Initialization finished\n📡 Awaiting input\n⚡ Operational",
        "🛰 SYSTEM STARTUP\n╾━━━━━━━━━━━━━━━━╼\n🤖 Core AI online\n📊 Monitoring engaged\n🛡 Defensive protocols active",
        "✅ ALL SYSTEMS NOMINAL\n╾━━━━━━━━━━━━━━━━╼\n🖥 Core AI running\n📡 Event stream open\n🔋 Power levels stable",
        "📡 SYNC COMPLETE\n╾━━━━━━━━━━━━━━━━╼\n⚙️ Notification pipeline active\n🛡 Watching infrastructure\n🧠 Adaptive intelligence online",
        "🌐 NETWORK READY\n╾━━━━━━━━━━━━━━━━╼\n📡 Gotify stream connected\n🛰 Jarvis Jnr listening\n⚡ Awaiting instructions",
        "✨ BOOT SEQUENCE COMPLETE\n╾━━━━━━━━━━━━━━━━╼\n✅ Initialization finished\n🧠 Intelligence core ready\n📡 Events inbound",
        "🔧 INITIALIZATION DONE\n╾━━━━━━━━━━━━━━━━╼\n📊 Subsystems engaged\n🛰 AI standing by\n🚀 Systems at velocity",
        "📊 STATUS: ONLINE\n╾━━━━━━━━━━━━━━━━╼\n🖥 Console active\n📡 Events visible\n⚡ AI operator present",
        "🛡 SHIELDING ENABLED\n╾━━━━━━━━━━━━━━━━╼\n✅ Event protection\n📡 Core systems online\n🤖 Jarvis Jnr standing by",
        "⚡ POWER OPTIMAL\n╾━━━━━━━━━━━━━━━━╼\n🔋 Energy flow stable\n📡 Event link active\n🧠 Neural routines online",
        "🔍 SELF-CHECK PASSED\n╾━━━━━━━━━━━━━━━━╼\n✅ Diagnostics clean\n⚡ Performance optimal\n📡 Ready to process",
        "🌟 AI READY\n╾━━━━━━━━━━━━━━━━╼\n🤖 Jarvis Jnr awakened\n📡 Standing watch\n🛡 Securing notifications",
        "🚨 ALERT MODE READY\n╾━━━━━━━━━━━━━━━━╼\n📡 Streams locked\n🛡 Monitoring enabled\n⚡ Response instant",
        "📂 KNOWLEDGE BASE LOADED\n╾━━━━━━━━━━━━━━━━╼\n📡 Input channels ready\n🧠 AI processing active\n✨ Standing by",
        "🎯 TARGET LOCKED\n╾━━━━━━━━━━━━━━━━╼\n⚡ Awaiting next instruction\n🤖 Jarvis Jnr ready\n📡 Notifications inbound",
        "🛰 UPLINK STABLE\n╾━━━━━━━━━━━━━━━━╼\n📡 Gotify stream secure\n🛡 AI operational\n⚡ Fully online",
        "✨ OPERATIONAL CYCLE STARTED\n╾━━━━━━━━━━━━━━━━╼\n🧠 AI core ready\n📡 Monitoring flows\n🚀 Standing by",
        "📊 DATA STREAM OPEN\n╾━━━━━━━━━━━━━━━━╼\n📡 Listening to events\n🧠 AI parsing engaged\n⚡ Secure link stable",
        "🔒 SECURITY MODE ACTIVE\n╾━━━━━━━━━━━━━━━━╼\n🛡 Jarvis Jnr guarding events\n📡 Uplink confirmed\n⚡ All green",
        "📡 STREAM INIT\n╾━━━━━━━━━━━━━━━━╼\n🤖 Notifications will be managed\n🧠 AI safeguards online\n⚡ Stability ensured",
        "🛰 CONNECTION LIVE\n╾━━━━━━━━━━━━━━━━╼\n📡 Data link to Gotify secured\n🛡 Monitoring pipelines\n🤖 Jarvis Jnr vigilant",
        "🚀 AI ENGAGED\n╾━━━━━━━━━━━━━━━━╼\n📊 Neural cores aligned\n🛡 Systems protected\n📡 Jarvis Jnr standing by",
        "🔎 STATUS: READY\n╾━━━━━━━━━━━━━━━━╼\n📡 Stream validated\n🧠 AI analysis online\n⚡ Secure operations",
        "🌌 STARLINK READY\n╾━━━━━━━━━━━━━━━━╼\n📡 Notifications pipeline glowing\n🧠 AI aligned\n🚀 All modules active",
        "🛠 MODULES READY\n╾━━━━━━━━━━━━━━━━╼\n⚡ Neural subroutines linked\n📡 Input channels clean\n🤖 Core AI steady",
        "🎶 AI CHIME\n╾━━━━━━━━━━━━━━━━╼\n📡 Notifications orchestrated\n🛡 Protected by Jarvis Jnr\n✨ Standing by",
        "⚡ TURBO MODE\n╾━━━━━━━━━━━━━━━━╼\n📡 Streams wide open\n🤖 Processing with velocity\n🛡 Systems defended",
        "📡 AI GUARDIAN ONLINE\n╾━━━━━━━━━━━━━━━━╼\n🤖 Securing flows\n🛡 Monitoring 24/7\n✨ Jarvis Jnr operational",
        "✨ WELCOME BACK\n╾━━━━━━━━━━━━━━━━╼\n🤖 Jarvis Jnr here again\n📡 Notifications safe\n🛡 Standing guard",
    ]
    send_message("Startup", random.choice(startup_msgs), priority=5)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
