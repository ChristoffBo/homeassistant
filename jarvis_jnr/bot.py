import os, json, time, asyncio, requests, websockets, schedule, datetime

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")   # only for listening
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")         # used for sending + deleting
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

FOOTER = f"{BOT_ICON} With regards, {BOT_NAME}"


def send_message(title, message, priority=5):
    """Send a message via Gotify using APP_TOKEN."""
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": f"{message}\n\n{FOOTER}",
        "priority": priority,
    }
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] Sent message: {title}")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message:", e)


async def listen():
    """Listen to Gotify WebSocket stream for new messages using CLIENT_TOKEN."""
    ws_url = f"{GOTIFY_URL.replace('http', 'ws')}/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    mid = data.get("id")
                    title = data.get("title", "")
                    message = data.get("message", "")

                    # skip own messages (avoid infinite loop)
                    if FOOTER in message:
                        print(f"[{BOT_NAME}] Skipping own message id={mid}")
                        continue

                    # Beautify + repost
                    if os.getenv("BEAUTIFY_ENABLED", "true") == "true":
                        new_msg = f"✨ {message.strip()}"
                        send_message(title, new_msg)

                        # delete original (now with APP_TOKEN)
                        try:
                            requests.delete(f"{GOTIFY_URL}/message/{mid}?token={APP_TOKEN}")
                            print(f"[{BOT_NAME}] Deleted original message {mid}")
                        except Exception as e:
                            print(f"[{BOT_NAME}] Failed to delete message {mid}: {e}")

                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing message:", e)
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed:", e)
        await asyncio.sleep(10)
        await listen()  # retry


def retention_cleanup():
    """Delete old messages past retention_hours (using APP_TOKEN)."""
    try:
        url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z","+00:00")).timestamp()
            if ts < cutoff:
                requests.delete(f"{GOTIFY_URL}/message/{msg['id']}?token={APP_TOKEN}")
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
    send_message("Startup", f"Good Day, I am {BOT_NAME}, ready to assist.")

    # Explicitly create new asyncio loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start listener + scheduler
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
