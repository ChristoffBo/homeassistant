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
# Purge all non-Jarvis apps (only used if beautify is enabled)
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
# Purge old messages (retention-based, always runs)
# -----------------------------
def purge_old_messages():
    url = f"{GOTIFY_URL}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        messages = r.json().get("messages", [])
        now = datetime.datetime.utcnow().timestamp()
        cutoff = now - (RETENTION_HOURS * 3600)

        for msg in messages:
            ts = msg.get("date")
            if ts:
                msg_time = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                if msg_time < cutoff:
                    mid = msg.get("id")
                    del_url = f"{GOTIFY_URL}/message/{mid}"
                    dr = requests.delete(del_url, headers=headers, timeout=5)
                    if dr.status_code == 200:
                        print(f"[{BOT_NAME}] 🗑 Deleted old message id={mid}")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging old messages: {e}")

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
    status_line = None

    # Special handling for Radarr/Sonarr
    if "downloaded:" in lower and ("radarr" in lower or "movie" in lower):
        prefix = "🎬"
        status_line = f"{prefix} **New Movie Downloaded**"
        formatted = raw.replace("Downloaded:", "").strip()
        formatted = f"{status_line}\n{formatted}\n\n✅ Added to your collection!"
    elif "downloaded:" in lower and ("sonarr" in lower or "s0" in lower or "episode" in lower):
        prefix = "📺"
        status_line = f"{prefix} **New Episode Downloaded**"
        formatted = raw.replace("Downloaded:", "").strip()
        formatted = f"{status_line}\n{formatted}\n\n✅ Ready to watch!"
    else:
        # General rules
        if "error" in lower or "failed" in lower or "exception" in lower:
            prefix = "💀"
            status_line = f"{prefix} **ERROR**"
            text = text.replace("error", "**ERROR**").replace("Error", "**ERROR**")
        elif "success" in lower or "completed" in lower or "done" in lower:
            prefix = "✅"
            status_line = f"{prefix} **SUCCESS**"
            text = text.replace("success", "**SUCCESS**").replace("Success", "**SUCCESS**")
        elif "warning" in lower or "caution" in lower:
            prefix = "⚠️"
            status_line = f"{prefix} **WARNING**"
            text = text.replace("warning", "**WARNING**").replace("Warning", "**WARNING**")
        elif "start" in lower or "starting" in lower or "boot" in lower:
            prefix = "🚀"
            status_line = f"{prefix} **STARTUP**"

        formatted = text
        formatted = formatted.replace(":", ":\n")
        formatted = formatted.replace("  ", " ")

        if status_line:
            formatted = f"{status_line}\n{formatted}"
        else:
            formatted = f"{prefix} {formatted}"

    closings = [
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🧩 Ever at your service, {BOT_NAME}",
        f"🤖 Yours truly, {BOT_NAME}",
        f"📌 Tidied up by {BOT_NAME}",
        f"🔧 Optimized by {BOT_NAME}",
        f"📊 Sorted with care – {BOT_NAME}",
        f"✅ Verified and logged – {BOT_NAME}",
        f"⚡ Fast-forwarded through {BOT_NAME}",
        f"🛡️ Guarded by {BOT_NAME}",
        f"📡 Relayed by {BOT_NAME}",
        f"📝 Reformatted by {BOT_NAME}",
        f"📦 Packed neatly by {BOT_NAME}",
        f"🎯 Precision from {BOT_NAME}",
        f"🚀 Launched by {BOT_NAME}",
        f"🎶 Harmonized with {BOT_NAME}",
        f"💡 Refined by {BOT_NAME}",
        f"🔍 Checked thoroughly by {BOT_NAME}",
        f"🔑 Secured with {BOT_NAME}",
        f"🌙 Wrapped up by {BOT_NAME}",
        f"🔥 Clean and clear, {BOT_NAME}",
        f"🎉 Delivered courtesy of {BOT_NAME}",
        f"🛠️ Engineered by {BOT_NAME}",
        f"📢 Signed, {BOT_NAME}",
        f"🌐 Routed via {BOT_NAME}",
        f"⚙️ Mechanized by {BOT_NAME}",
        f"📎 Clipped and trimmed by {BOT_NAME}",
        f"🔋 Energized by {BOT_NAME}",
        f"👑 Finalized by {BOT_NAME}",
        f"🧠 Intelligently processed by {BOT_NAME}",
    ]
    closing = random.choice(closings)

    return f"{formatted}\n\n{closing}"

# -----------------------------
# Scheduled cleanup
# -----------------------------
def run_scheduler():
    schedule.every(10).minutes.do(purge_old_messages)
    if BEAUTIFY_ENABLED:
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

    while True:
        try:
            print(f"[{BOT_NAME}] Connecting to {ws_url}...")
            async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
                print(f"[{BOT_NAME}] ✅ Connected! Listening for messages...")

                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        mid = data.get("id")
                        appid = data.get("appid")
                        title = data.get("title", "")
                        message = data.get("message", "")
                        extras = data.get("extras", {})

                        print(f"[{BOT_NAME}] Incoming message id={mid}, appid={appid}, title='{title}'")

                        # Detect if message has an image (Radarr/Sonarr posters)
                        has_image = False
                        if extras:
                            client_disp = extras.get("client::display")
                            if client_disp and client_disp.get("image"):
                                has_image = True

                        # Skip Jarvis's own messages
                        if jarvis_app_id and appid == jarvis_app_id:
                            print(f"[{BOT_NAME}] Skipping own message id={mid}")
                            continue

                        if BEAUTIFY_ENABLED:
                            final_msg = beautify_message(title, message)
                            repost_priority = 0 if SILENT_REPOST else 5
                            send_success = send_message(title, final_msg, priority=repost_priority)
                            if send_success:
                                print(f"[{BOT_NAME}] ✅ Reposted beautified message")
                                if not has_image:
                                    purge_non_jarvis_apps()
                                else:
                                    print(f"[{BOT_NAME}] 🎬 Detected media message with image — keeping original")
                        else:
                            print(f"[{BOT_NAME}] (Beautify disabled) Keeping original message")

                    except Exception as e:
                        print(f"[{BOT_NAME}] ❌ Error processing message: {e}")

        except Exception as e:
            print(f"[{BOT_NAME}] ❌ WebSocket connection failed: {e}")
            await asyncio.sleep(10)

# -----------------------------
# Main entrypoint
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on...")

    resolve_app_id()

    startup_msgs = [
        f"Good Day, I am {BOT_NAME}, ready to assist.",
        f"Greetings, {BOT_NAME} is now online and standing by.",
        f"🚀 {BOT_NAME} systems initialized and operational.",
        f"{BOT_NAME} reporting for duty.",
        f"{BOT_NAME} says hello 👋, let’s get started.",
        f"✅ {BOT_NAME} boot complete. Standing ready.",
        f"🌐 {BOT_NAME} connected and awaiting instructions.",
        f"Jarvis online, how may I serve?",
        f"🤖 {BOT_NAME} has joined the network.",
        f"🟢 {BOT_NAME} is operational.",
        f"⚡ {BOT_NAME} spun up and ready.",
        f"📡 {BOT_NAME} listening for signals.",
        f"🛠️ {BOT_NAME} tools loaded, let’s go.",
        f"🎯 {BOT_NAME} targeting optimal performance.",
        f"💡 {BOT_NAME} systems nominal.",
        f"⏱️ {BOT_NAME} uptime counter started.",
        f"🧩 {BOT_NAME} fully initialized.",
        f"🔑 {BOT_NAME} authentication verified.",
        f"📊 {BOT_NAME} monitoring engaged.",
        f"📢 {BOT_NAME} loud and clear.",
        f"🔋 {BOT_NAME} power levels optimal.",
        f"🌙 {BOT_NAME} is awake from standby.",
        f"🔥 {BOT_NAME} is fired up.",
        f"🎉 {BOT_NAME} welcomes you.",
        f"Jarvis core sync complete.",
        f"System reboot finished, {BOT_NAME} online.",
        f"Hello World! {BOT_NAME} here.",
        f"Initialization finished. {BOT_NAME} operational.",
        f"Mission control: {BOT_NAME} connected.",
        f"👑 {BOT_NAME} ready to rule the notifications.",
    ]
    startup_msg = random.choice(startup_msgs)
    send_message("Startup", startup_msg, priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
