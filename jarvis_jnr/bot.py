import os, json, time, asyncio, requests, websockets, schedule, datetime, collections

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
GOTIFY_APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
GOTIFY_CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

# App ID must be integer
try:
    JARVIS_APP_ID = int(os.getenv("JARVIS_APP_ID", "0"))
except ValueError:
    JARVIS_APP_ID = 0

# Track last sent IDs to avoid loops
last_sent_ids = collections.deque(maxlen=50)

def send_message(title, message, priority=5):
    """Send a message using APP token (posts under Jarvis app)."""
    url = f"{GOTIFY_URL}/message?token={GOTIFY_APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        mid = r.json().get("id")
        if mid:
            last_sent_ids.append(mid)
            print(f"[{BOT_NAME}] Sent message id={mid}")
        return mid
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")
        return None

async def listen():
    """Listen to Gotify WebSocket stream for new messages."""
    ws_url = f"{GOTIFY_URL.replace('http', 'ws')}/stream?token={GOTIFY_CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    mid = data.get("id")
                    appid = data.get("appid")

                    # Ignore own posts by appid
                    if JARVIS_APP_ID and appid == JARVIS_APP_ID:
                        print(f"[{BOT_NAME}] Ignored own message id={mid} (appid={appid})")
                        continue

                    # Ignore if in last sent IDs
                    if mid in last_sent_ids:
                        print(f"[{BOT_NAME}] Ignored own message id={mid} (last_sent_ids)")
                        continue

                    title = data.get("title", "")
                    message = data.get("message", "")

                    # Beautify + repost
                    if os.getenv("BEAUTIFY_ENABLED", "true") == "true":
                        new = f"✨ {message.lower().capitalize()}"
                        new_id = send_message(title, new)
                        if new_id:
                            try:
                                requests.delete(f"{GOTIFY_URL}/message/{mid}?token={GOTIFY_CLIENT_TOKEN}")
                                print(f"[{BOT_NAME}] Deleted original id={mid}")
                            except:
                                print(f"[{BOT_NAME}] Failed to delete id={mid}")
                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing message: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed: {e}")
        await asyncio.sleep(10)
        await listen()  # retry

def retention_cleanup():
    """Delete old messages past retention_hours."""
    try:
        url = f"{GOTIFY_URL}/message?token={GOTIFY_CLIENT_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z","+00:00")).timestamp()
            if ts < cutoff:
                requests.delete(f"{GOTIFY_URL}/message/{msg['id']}?token={GOTIFY_CLIENT_TOKEN}")
                print(f"[{BOT_NAME}] Deleted old message {msg['id']}")
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed: {e}")

def run_scheduler():
    """Run scheduled jobs like retention cleanup."""
    schedule.every(30).minutes.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    send_message("Startup", "Good Day, I am Jarvis ready to assist.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
