import os, json, time, asyncio, requests, websockets, schedule, datetime

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
GOTIFY_TOKEN = os.getenv("GOTIFY_TOKEN")
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

def send_message(title, message, priority=5):
    """Send a message back to Gotify."""
    url = f"{GOTIFY_URL}/message?token={GOTIFY_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print("[Jarvis Jnr] Failed to send message:", e)

async def listen():
    """Listen to Gotify WebSocket stream for new messages."""
    ws_url = f"{GOTIFY_URL.replace('http', 'ws')}/stream?token={GOTIFY_TOKEN}"
    print(f"[Jarvis Jnr] Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    title = data.get("title", "")
                    message = data.get("message", "")
                    mid = data.get("id")
                    # Beautify + repost
                    if os.getenv("BEAUTIFY_ENABLED", "true") == "true":
                        new = f"✨ {message.capitalize()}"
                        send_message(title, new)
                        # delete original
                        try:
                            requests.delete(f"{GOTIFY_URL}/message/{mid}?token={GOTIFY_TOKEN}")
                        except:
                            pass
                except Exception as e:
                    print("[Jarvis Jnr] Error processing message:", e)
    except Exception as e:
        print("[Jarvis Jnr] WebSocket connection failed:", e)
        await asyncio.sleep(10)
        await listen()  # retry

def retention_cleanup():
    """Delete old messages past retention_hours."""
    try:
        url = f"{GOTIFY_URL}/message?token={GOTIFY_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z","+00:00")).timestamp()
            if ts < cutoff:
                requests.delete(f"{GOTIFY_URL}/message/{msg['id']}?token={GOTIFY_TOKEN}")
                print(f"[Jarvis Jnr] Deleted old message {msg['id']}")
    except Exception as e:
        print("[Jarvis Jnr] Retention cleanup failed:", e)

def run_scheduler():
    """Run scheduled jobs like retention cleanup."""
    schedule.every(30).minutes.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    send_message("Startup", "Jarvis Jnr bot is now running.")

    # Explicitly create new asyncio loop (fixes DeprecationWarning)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start listener + scheduler
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print("[Jarvis Jnr] Event loop started.")
    loop.run_forever()
