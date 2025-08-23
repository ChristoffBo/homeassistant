import os, json, time, asyncio, requests, websockets, schedule, datetime

# -----------------------------
# Config from environment (set in run.sh from options.json)
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")   # admin / client token
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")         # app token for posting
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis") # optional app name lookup
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

jarvis_app_id = None  # will be resolved on startup

# -----------------------------
# Send message (with APP token)
# -----------------------------
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": f"✨ {message.strip()}\n\n{BOT_ICON} With regards, {BOT_NAME}",
        "priority": priority,
    }
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] Sent beautified: {title}")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")

# -----------------------------
# Delete message (with CLIENT token)
# -----------------------------
def delete_message(mid):
    if not mid:
        return
    try:
        url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
        r = requests.delete(url, timeout=5)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] Deleted original message {mid}")
        else:
            print(f"[{BOT_NAME}] Failed to delete {mid}: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[{BOT_NAME}] Delete error: {e}")

# -----------------------------
# Resolve numeric app_id for our Jarvis app
# -----------------------------
def resolve_app_id():
    global jarvis_app_id
    try:
        r = requests.get(f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}", timeout=5)
        r.raise_for_status()
        apps = r.json()
        for app in apps:
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] Resolved app '{APP_NAME}' to id={jarvis_app_id}")
                return
        print(f"[{BOT_NAME}] WARNING: Could not find app {APP_NAME}")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to resolve app id: {e}")

# -----------------------------
# Retention cleanup
# -----------------------------
def retention_cleanup():
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                requests.delete(f"{GOTIFY_URL}/message/{msg['id']}?token={CLIENT_TOKEN}")
                print(f"[{BOT_NAME}] Deleted old message {msg['id']}")
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed: {e}")

def run_scheduler():
    schedule.every(30).minutes.do(retention_cleanup)
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
        async with websockets.connect(ws_url) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    mid = data.get("id")
                    appid = data.get("appid")
                    title = data.get("title", "")
                    message = data.get("message", "")

                    # Skip own messages
                    if jarvis_app_id and appid == jarvis_app_id:
                        continue

                    print(f"[{BOT_NAME}] Processing message id={mid} title='{title}'")

                    # Beautify + repost
                    beautified = f"✨ {message.strip().capitalize()}"
                    send_message(title, beautified)
                    delete_message(mid)

                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed: {e}")
        await asyncio.sleep(10)
        await listen()  # retry

# -----------------------------
# Main entrypoint
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on...")

    resolve_app_id()

    send_message("Startup", f"Good Day, I am {BOT_NAME}, ready to assist.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
