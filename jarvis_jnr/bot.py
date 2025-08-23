import os, json, time, asyncio, requests, websockets, schedule, datetime

# Load config from Home Assistant options.json
with open("/data/options.json", "r") as f:
    config = json.load(f)

BOT_NAME = config.get("bot_name", "Jarvis Jnr")
BOT_ICON = config.get("bot_icon", "🤖")
CLIENT_TOKEN = config.get("gotify_client_token")
APP_TOKEN = config.get("gotify_app_token")
GOTIFY_URL = config.get("gotify_url")
RETENTION_HOURS = int(config.get("retention_hours", 24))

# Dynamic marker to identify Jarvis’ own messages
SELF_MARKER = f"{BOT_ICON} With regards, {BOT_NAME}"

def send_message(title, message, priority=5, silent=True):
    """Send a message to Gotify using the app token."""
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    # Append dynamic footer to all messages
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": f"{message}\n\n{SELF_MARKER}",
        "priority": priority,
        "extras": {"client::display": {"contentType": "text/markdown"}},
    }
    if silent:
        data["extras"]["client::notification"] = {"click": {"url": ""}}

    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] Sent message: {title}")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")

async def listen():
    """Listen to Gotify WebSocket stream for new messages via client token."""
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

                    # Skip if the message already contains Jarvis’ marker
                    if message and SELF_MARKER in message:
                        print(f"[{BOT_NAME}] Ignored own message id={mid}")
                        continue

                    # Beautify + repost
                    if config.get("beautify_enabled", True):
                        new_msg = f"✨ {message.strip().capitalize()}"
                        send_message(title, new_msg, priority=5, silent=True)

                        # delete the original
                        try:
                            requests.delete(f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}")
                            print(f"[{BOT_NAME}] Deleted original message {mid}")
                        except Exception as e:
                            print(f"[{BOT_NAME}] Failed to delete original message {mid}: {e}")

                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing message: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed: {e}")
        await asyncio.sleep(10)
        await listen()  # retry

def retention_cleanup():
    """Delete old messages past retention_hours."""
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
    """Run scheduled jobs like retention cleanup."""
    schedule.every(30).minutes.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    # Startup greeting
    send_message("Startup", f"Good Day, I am {BOT_NAME}, ready to assist.", silent=True)

    # Explicitly create new asyncio loop (fixes DeprecationWarning)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start listener + scheduler
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
