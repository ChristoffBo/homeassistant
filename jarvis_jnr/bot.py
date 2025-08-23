import os, json, time, asyncio, requests, websockets, schedule, datetime

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
APP_TOKEN = os.getenv("APP_TOKEN")       # FIXED naming
CLIENT_TOKEN = os.getenv("CLIENT_TOKEN") # FIXED naming
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

def send_message(title, message, priority=5):
    """Send a message back to Gotify (using APP token)."""
    if not APP_TOKEN:
        print(f"[{BOT_NAME}] No APP_TOKEN configured, cannot send messages")
        return
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] Sent message: {title}")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message:", e)

async def listen():
    """Listen to Gotify WebSocket stream for new messages."""
    if not CLIENT_TOKEN:
        print(f"[{BOT_NAME}] No CLIENT_TOKEN configured, cannot listen")
        return
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

                    # Ignore Jarvis’ own reposts (prevents infinite loop)
                    if title.startswith(f"{BOT_NAME}:") or title.startswith(f"{BOT_ICON} {BOT_NAME}:"):
                        continue

                    # Beautify + repost
                    if os.getenv("BEAUTIFY_ENABLED", "true") == "true":
                        new = f"✨ {message.capitalize()}"
                        send_message(title, new)

                        # delete original with CLIENT token
                        try:
                            requests.delete(f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}")
                            print(f"[{BOT_NAME}] Deleted original message {mid}")
                        except Exception as e:
                            print(f"[{BOT_NAME}] Failed to delete original message {mid}: {e}")

                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing message:", e)
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed:", e)
        await asyncio.sleep(10)
        await listen()  # retry

def retention_cleanup():
    """Delete old messages past retention_hours (uses CLIENT token)."""
    if not CLIENT_TOKEN:
        return
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z","+00:00")).timestamp()
            if ts < cutoff:
                requests.delete(f"{GOTIFY_URL}/message/{msg['id']}?token={CLIENT_TOKEN}")
                print(f"[{BOT_NAME}] Deleted old message {msg['id']}")
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed:", e)

def run_scheduler():
    """Run scheduled jobs like retention cleanup."""
    schedule.every(30).minutes.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    # Startup message
    send_message("Startup", "Good Day, I am Jarvis ready to assist.")

    # Explicitly create new asyncio loop (fixes DeprecationWarning)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start listener + scheduler
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
