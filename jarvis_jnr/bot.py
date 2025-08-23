import os, json, time, asyncio, requests, websockets, schedule, datetime, random

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
# AI-like beautifier
# -----------------------------
def beautify_message(title, raw):
    text = raw.strip()
    lower = text.lower()

    prefix = "💡"
    if "error" in lower or "failed" in lower:
        prefix = "💀"
    elif "success" in lower or "completed" in lower or "done" in lower:
        prefix = "✅"
    elif "warning" in lower:
        prefix = "⚠️"
    elif "start" in lower or "starting" in lower:
        prefix = "🚀"

    closings = [
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🧩 Ever at your service, {BOT_NAME}",
        f"🤖 Yours truly, {BOT_NAME}",
    ]
    closing = random.choice(closings)

    return f"{prefix} {text}\n\n{closing}"

# -----------------------------
# Scheduled cleanup
# -----------------------------
def run_scheduler():
    # Every 5 minutes, purge everything that is not Jarvis
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
                        # Purge everything that is not Jarvis
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

    startup_msg = random.choice([
        f"Good Day, I am {BOT_NAME}, ready to assist.",
        f"Greetings, {BOT_NAME} is now online and standing by.",
        f"🚀 {BOT_NAME} systems initialized and operational.",
        f"{BOT_NAME} reporting for duty.",
    ])
    send_message("Startup", startup_msg, priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
