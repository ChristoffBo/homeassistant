#!/usr/bin/env python3
import asyncio, json, os, requests, websockets, time, logging

# Load config
with open("/data/options.json") as f:
    cfg = json.load(f)

BOT_NAME = cfg.get("bot_name", "Jarvis")
BOT_ICON = cfg.get("bot_icon", "🤖")
GOTIFY_URL = cfg.get("gotify_url")
CLIENT_TOKEN = cfg.get("gotify_client_token")
APP_TOKEN = cfg.get("gotify_app_token")

# Retention & settings
RETENTION_HOURS = cfg.get("retention_hours", 24)
QUIET = cfg.get("quiet_hours_enabled", False)
QUIET_RANGE = cfg.get("quiet_hours", "22:00-06:00")

# Headers
HEADERS_CLIENT = {"X-Gotify-Key": CLIENT_TOKEN}
HEADERS_APP = {"X-Gotify-Key": APP_TOKEN}

# Logging
logging.basicConfig(level=logging.INFO, format=f"[{BOT_NAME}] %(message)s")

STREAM_URL = f"{GOTIFY_URL}/stream?token={CLIENT_TOKEN}"
MSG_URL = f"{GOTIFY_URL}/message"

# Beautify any incoming message
def beautify(raw_msg):
    title = raw_msg.get("title", "Notification")
    body = raw_msg.get("message", "")
    clean = f"✨ {body.strip()}\n\n🤖 With regards, {BOT_NAME}"
    return f"{BOT_ICON} {BOT_NAME}: {title}", clean

# Delete a message using client token
def delete_msg(msg_id):
    try:
        resp = requests.delete(f"{MSG_URL}/{msg_id}", headers=HEADERS_CLIENT, timeout=5)
        if resp.ok:
            logging.info(f"Deleted original {msg_id}")
        else:
            logging.error(f"Delete failed {msg_id}: {resp.status_code}")
    except Exception as e:
        logging.error(f"Error deleting {msg_id}: {e}")

# Post beautified using app token
def post_msg(title, body):
    try:
        requests.post(MSG_URL, headers=HEADERS_APP, json={
            "title": title, "message": body, "priority": 5
        }, timeout=5)
        logging.info(f"Sent beautified: {title}")
    except Exception as e:
        logging.error(f"Posting failed: {e}")

def process(raw):
    try:
        data = json.loads(raw)["message"]
        mid = data.get("id")
        if not data.get("message", "").endswith(f"With regards, {BOT_NAME}"):
            bt, bb = beautify(data)
            post_msg(bt, bb)
            delete_msg(mid)
        else:
            logging.info(f"Ignored own {mid}")
    except Exception as e:
        logging.error(f"Process error: {e}")

async def listen_loop():
    logging.info("Listening to Gotify...")
    async with websockets.connect(STREAM_URL) as ws:
        async for msg in ws:
            process(msg)

def send_startup():
    title = f"{BOT_ICON} {BOT_NAME}: Startup"
    body = f"Good Day, I am {BOT_NAME}, ready to assist.\n\n🤖 With regards, {BOT_NAME}"
    post_msg(title, body)

if __name__ == "__main__":
    send_startup()
    asyncio.run(listen_loop())
