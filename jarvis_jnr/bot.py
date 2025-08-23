import os, json, time, asyncio, requests, websockets, schedule, datetime

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")   # admin client token
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")         # Jarvis app token
APP_NAME = os.getenv("JARVIS_APP_NAME", BOT_NAME)

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SELF_APP_ID = None  # resolved later

def resolve_self_appid():
    """Resolve Jarvis' own AppID from Gotify using APP_NAME (for loop protection)."""
    global SELF_APP_ID
    try:
        r = requests.get(f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}", timeout=5)
        r.raise_for_status()
        for app in r.json():
            if app["name"].lower() == APP_NAME.lower():
                SELF_APP_ID = app["id"]
                print(f"[{BOT_NAME}] Resolved self AppID = {SELF_APP_ID}")
                return
        print(f"[{BOT_NAME}] WARNING: Could not find app '{APP_NAME}', loop protection disabled.")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to resolve AppID: {e}")

def send_message(title, message, priority=5):
    """Send beautified message using Jarvis APP token."""
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message:", e)

def delete_message(mid):
    """Delete message using CLIENT token (admin rights)."""
    try:
        requests.delete(f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}", timeout=5)
        print(f"[{BOT_NAME}] Deleted original message {mid}")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to delete message {mid}: {e}")

async def listen():
    """Listen to Gotify WebSocket stream for new messages (via CLIENT token)."""
    ws_url = f"{GOTIFY_URL.replace('http', 'ws')}/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    title = data.get("title", "")
                    message = data.get("message", "")
                    mid = data.get("id")
                    appid = data.get("appid")

                    # 🔒 Skip Jarvis' own messages (loop protection)
                    if SELF_APP_ID and appid == SELF_APP_ID:
                        continue

                    # Beautify + repost + delete
                    if os.getenv("BEAUTIFY_ENABLED", "true") == "true":
                        new = f"✨ {message.capitalize()}"
                        send_message(title, new)
                        delete_message(mid)

                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing message:", e)
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed:", e)
        await asyncio.sleep(10)
        await listen()  # retry

def retention_cleanup():
    """Delete old messages past retention_hours."""
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z","+00:00")).timestamp()
            if ts < cutoff:
                delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed:", e)

def run_scheduler():
    """Run scheduled jobs like retention cleanup."""
    schedule.every(30).minutes.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    resolve_self_appid()
    send_message("Startup", f"Good Day, I am {BOT_NAME}, ready to assist.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
