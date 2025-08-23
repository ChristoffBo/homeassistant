#!/usr/bin/env python3
import asyncio
import websockets
import json
import requests
import logging
import os

# ---- Load configuration from options.json ----
CONFIG_PATH = "/data/options.json"

with open(CONFIG_PATH, "r") as f:
    options = json.load(f)

BOT_NAME = options.get("bot_name", "Jarvis")
BOT_ICON = options.get("bot_icon", "🤖")
GOTIFY_URL = options.get("gotify_url", "http://gotify:80")
CLIENT_TOKEN = options.get("gotify_client_token", "")
APP_TOKEN = options.get("gotify_app_token", "")
RETENTION_HOURS = options.get("retention_hours", 24)

# ---- Setup logging ----
logging.basicConfig(level=logging.INFO, format=f"[{BOT_NAME}] %(message)s")

# ---- Gotify endpoints ----
STREAM_URL = f"{GOTIFY_URL}/stream?token={CLIENT_TOKEN}"
MESSAGE_URL = f"{GOTIFY_URL}/message"

# ---- Headers ----
CLIENT_HEADERS = {"X-Gotify-Key": CLIENT_TOKEN}
APP_HEADERS = {"X-Gotify-Key": APP_TOKEN}

# ---- Beautify Function ----
def beautify_message(message):
    """
    Create a cleaner, more professional formatted message.
    """
    title = message.get("title", "Notification")
    body = message.get("message", "")

    beautified_title = f"{BOT_ICON} {BOT_NAME}: {title}"
    beautified_message = (
        f"✨ {body}\n\n"
        f"👋 With regards, {BOT_NAME}"
    )

    return beautified_title, beautified_message


# ---- Delete message ----
def delete_message(message_id):
    """
    Delete a raw Gotify message using the admin CLIENT token.
    """
    try:
        url = f"{MESSAGE_URL}/{message_id}"
        r = requests.delete(url, headers=CLIENT_HEADERS, timeout=5)
        if r.status_code == 200:
            logging.info(f"Deleted original message {message_id}")
        else:
            logging.error(f"Failed to delete {message_id}: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"Error deleting message {message_id}: {e}")


# ---- Post message ----
def post_message(title, message):
    """
    Post a beautified message using the APP token.
    """
    try:
        payload = {"title": title, "message": message, "priority": 5}
        r = requests.post(MESSAGE_URL, headers=APP_HEADERS, json=payload, timeout=5)
        if r.status_code == 200:
            logging.info(f"Sent beautified: {title}")
        else:
            logging.error(f"Failed to send beautified message: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"Error sending message: {e}")


# ---- Process incoming ----
def process_message(raw):
    """
    Decide whether to beautify/delete or ignore.
    """
    try:
        data = json.loads(raw)
        msg = data.get("message")

        if not msg:
            return

        msg_id = msg.get("id")
        title = msg.get("title", "")
        body = msg.get("message", "")

        # Ignore Jarvis's own beautified messages (check footer/tag)
        if body.strip().endswith(f"With regards, {BOT_NAME}"):
            logging.info(f"Ignored own message {msg_id}")
            return

        # Beautify & send
        beautified_title, beautified_body = beautify_message(msg)
        post_message(beautified_title, beautified_body)

        # Delete original
        delete_message(msg_id)

    except Exception as e:
        logging.error(f"Process error: {e}")


# ---- WebSocket Event Loop ----
async def listen():
    logging.info("Starting add-on...")
    logging.info(f"Connecting to {STREAM_URL} ...")

    async for ws in websockets.connect(STREAM_URL):
        try:
            logging.info("Event loop started.")
            async for message in ws:
                process_message(message)
        except websockets.ConnectionClosed:
            logging.warning("WebSocket closed, reconnecting...")
            await asyncio.sleep(3)
            continue


# ---- Startup Message ----
def send_startup_message():
    startup_title = f"{BOT_ICON} {BOT_NAME}: Startup"
    startup_body = f"Good Day, I am {BOT_NAME}, ready to assist.\n\n👋 With regards, {BOT_NAME}"
    post_message(startup_title, startup_body)


# ---- Main ----
if __name__ == "__main__":
    send_startup_message()
    asyncio.run(listen())
