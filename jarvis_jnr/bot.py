import os
import json
import time
import asyncio
import requests
import websockets
import schedule
import datetime

# -------------------------------------------------------------------
# Config from environment (set in run.sh from options.json)
# -------------------------------------------------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")      # for posting
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")  # for reading/deleting
SELF_APP_ID = os.getenv("SELF_APP_ID")         # numeric appid of Jarvis
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() == "true"

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def send_message(title, message, priority=5):
    """Send a message to Gotify using the APP token."""
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] Sent message: {title}")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")

def delete_message(mid):
    """Delete a message using the CLIENT token."""
    try:
        url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
        r = requests.delete(url, timeout=5)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] Deleted original message {mid}")
        else:
            print(f"[{BOT_NAME}] Failed to delete {mid}, status={r.status_code}, body={r.text}")
    except Exception as e:
        print(f"[{BOT_NAME}] Exception deleting {mid}: {e}")

def retention_cleanup():
    """Delete old messages past retention_hours."""
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed: {e}")

def run_scheduler():
    """Run scheduled jobs like retention cleanup."""
    schedule.every(30).minutes.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -------------------------------------------------------------------
# WebSocket listener
# -------------------------------------------------------------------
async def listen():
    """Listen to Gotify WebSocket stream using CLIENT token."""
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

                    # Skip Jarvis' own messages (avoid infinite loop)
                    if SELF_APP_ID and str(appid) == str(SELF_APP_ID):
                        print(f"[{BOT_NAME}] Ignored own message id={mid}")
                        continue

                    # Beautify + repost + delete
                    if BEAUTIFY_ENABLED:
                        new = f"✨ {message.capitalize()}"
                        send_message(title, new)
                        await asyncio.sleep(0.5)  # give Gotify time to commit
                        delete_message(mid)

                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing message: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed: {e}")
        await asyncio.sleep(10)
        await listen()  # retry loop

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
if __name__ == "__main__":
    # Startup announcement
    send_message("Startup", f"Good Day, I am {BOT_NAME}, ready to assist.")

    # Scheduler for cleanup
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
