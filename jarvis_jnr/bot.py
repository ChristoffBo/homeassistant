import os
import json
import time
import asyncio
import requests
import websockets
import schedule
import datetime

# -----------------------------
# Load configuration
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")   # must allow delete
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")         # for Jarvis identity
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
QUIET_HOURS_ENABLED = os.getenv("QUIET_HOURS_ENABLED", "false").lower() == "true"
QUIET_HOURS = os.getenv("QUIET_HOURS", "22:00-06:00")
WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "false").lower() == "true"
RADARR_ENABLED = os.getenv("RADARR_ENABLED", "false").lower() == "true"
SONARR_ENABLED = os.getenv("SONARR_ENABLED", "false").lower() == "true"

FOOTER = f"{BOT_ICON} With regards, {BOT_NAME}"


# -----------------------------
# Utilities
# -----------------------------
def send_message(title, message, priority=5):
    """Send beautified message via APP_TOKEN."""
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": f"{message}\n\n{FOOTER}",
        "priority": priority
    }
    try:
        r = requests.post(url, json=data, timeout=5)
        if r.ok:
            print(f"[{BOT_NAME}] Sent message: {title}")
        else:
            print(f"[{BOT_NAME}] Failed to send message: status={r.status_code}, body={r.text}")
    except Exception as e:
        print(f"[{BOT_NAME}] Error sending message: {e}")


def delete_message(mid):
    """Delete original via CLIENT_TOKEN."""
    try:
        url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
        resp = requests.delete(url, timeout=5)
        if resp.ok:
            print(f"[{BOT_NAME}] Deleted original message {mid}")
        else:
            print(f"[{BOT_NAME}] Failed to delete id={mid}, status={resp.status_code}, body={resp.text}")
    except Exception as e:
        print(f"[{BOT_NAME}] Error deleting id={mid}: {e}")


def retention_cleanup():
    """Delete old messages past retention threshold."""
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup error: {e}")


def in_quiet_hours():
    """Return True if current time falls in configured quiet hours."""
    if not QUIET_HOURS_ENABLED:
        return False
    try:
        start, end = QUIET_HOURS.split("-")
        now = datetime.datetime.now().time()
        s = datetime.datetime.strptime(start, "%H:%M").time()
        e = datetime.datetime.strptime(end, "%H:%M").time()
        if s < e:
            return s <= now <= e
        else:  # wraps midnight
            return now >= s or now <= e
    except Exception:
        return False


# -----------------------------
# Event Loop / Listener
# -----------------------------
async def listen():
    """Listen with CLIENT_TOKEN, beautify, then delete original."""
    ws_url = f"{GOTIFY_URL.replace('http', 'ws')}/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting to {ws_url}...")
    async with websockets.connect(ws_url) as ws:
        async for msg in ws:
            try:
                data = json.loads(msg)
                mid = data.get("id")
                message = data.get("message", "")
                title = data.get("title", "")

                # Skip own messages
                if FOOTER in message:
                    print(f"[{BOT_NAME}] Skipped own message id={mid}")
                    continue

                # Quiet hours: skip beautify
                if in_quiet_hours():
                    print(f"[{BOT_NAME}] Quiet hours active, skipping id={mid}")
                    continue

                # Beautify & repost
                new_msg = f"✨ {message.strip()}"
                send_message(title, new_msg)

                # Delete original
                delete_message(mid)

            except Exception as e:
                print(f"[{BOT_NAME}] Error handling message: {e}")


# -----------------------------
# Scheduled Jobs
# -----------------------------
def run_scheduler():
    schedule.every(30).minutes.do(retention_cleanup)

    if WEATHER_ENABLED:
        schedule.every().day.at("07:00").do(lambda: send_message("Weather", "Weather report TODO"))

    if RADARR_ENABLED:
        schedule.every().day.at("07:30").do(lambda: send_message("Radarr", "Radarr releases TODO"))

    if SONARR_ENABLED:
        schedule.every().day.at("07:30").do(lambda: send_message("Sonarr", "Sonarr releases TODO"))

    while True:
        schedule.run_pending()
        time.sleep(1)


# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    send_message("Startup", f"Good Day, I am {BOT_NAME}, ready to assist.")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
