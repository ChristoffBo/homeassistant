import os
import json
import time
import random
import requests
import websocket
from datetime import datetime

CONFIG_PATH = "/data/options.json"

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

config = load_config()

BOT_NAME = config.get("bot_name", "Jarvis")
BOT_ICON = config.get("bot_icon", "🤖")
GOTIFY_URL = config.get("gotify_url").rstrip("/")
CLIENT_TOKEN = config.get("gotify_client_token")
APP_TOKEN = config.get("gotify_app_token")
RETENTION_HOURS = config.get("retention_hours", 24)
BEAUTIFY_ENABLED = config.get("beautify_enabled", True)

HEADERS_CLIENT = {"X-Gotify-Key": CLIENT_TOKEN}
HEADERS_APP = {"X-Gotify-Key": APP_TOKEN}

# --- Dynamic AI-like footers ---
FOOTERS = [
    "With regards, {BOT_NAME}",
    "At your service, {BOT_NAME}",
    "Your loyal assistant, {BOT_NAME}",
    "Glad I could help, {BOT_NAME}",
    "On duty, {BOT_NAME}",
    "Consider it done — {BOT_NAME}",
    "Always watching, {BOT_NAME}"
]

def random_footer():
    return f"{BOT_ICON} {random.choice(FOOTERS).format(BOT_NAME=BOT_NAME)}"

# --- Beautify profiles ---
def beautify_message(msg):
    title = msg.get("title", "")
    body = msg.get("message", "")
    footer = random_footer()

    lowered = (title + " " + body).lower()

    if any(x in lowered for x in ["error", "failed", "failure", "unreachable"]):
        return f"""{BOT_ICON} {BOT_NAME}: {title}
❌🔥 {body}

{footer}"""

    if any(x in lowered for x in ["warn", "degraded", "delay"]):
        return f"""{BOT_ICON} {BOT_NAME}: {title}
⚠️⏳ {body}

{footer}"""

    if any(x in lowered for x in ["completed", "success", "done", "finished", "ok"]):
        return f"""{BOT_ICON} {BOT_NAME}: {title}
✅✨ {body}

{footer}"""

    if any(x in lowered for x in ["started", "boot", "status", "info"]):
        return f"""{BOT_ICON} {BOT_NAME}: {title}
ℹ️ {body}

{footer}"""

    if any(x in lowered for x in ["radarr", "movie"]):
        return f"""{BOT_ICON} {BOT_NAME}: 🎬 {title}
{body}

{footer}"""

    if any(x in lowered for x in ["sonarr", "episode", "tv"]):
        return f"""{BOT_ICON} {BOT_NAME}: 📺 {title}
{body}

{footer}"""

    if any(x in lowered for x in ["backup", "restore", "snapshot"]):
        return f"""{BOT_ICON} {BOT_NAME}: 💾 {title}
{body}

{footer}"""

    if any(x in lowered for x in ["network", "vpn", "zerotier", "netbird"]):
        return f"""{BOT_ICON} {BOT_NAME}: 🌐 {title}
{body}

{footer}"""

    # Default
    return f"""{BOT_ICON} {BOT_NAME}: {title}
{body}

{footer}"""

# --- Delete with client token ---
def delete_message(msg_id):
    url = f"{GOTIFY_URL}/message/{msg_id}"
    try:
        r = requests.delete(url, headers=HEADERS_CLIENT)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] Deleted original id={msg_id}")
        else:
            print(f"[{BOT_NAME}] Failed to delete id={msg_id}, status={r.status_code}, resp={r.text}")
    except Exception as e:
        print(f"[{BOT_NAME}] Exception deleting id={msg_id}: {e}")

# --- Send beautified message ---
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message"
    payload = {"title": title, "message": message, "priority": priority}
    try:
        r = requests.post(url, headers=HEADERS_APP, json=payload)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] Sent beautified: {title}")
        else:
            print(f"[{BOT_NAME}] Failed to send, status={r.status_code}, resp={r.text}")
    except Exception as e:
        print(f"[{BOT_NAME}] Exception sending: {e}")

# --- Process incoming ---
def handle_message(msg):
    msg_id = msg.get("id")
    title = msg.get("title", "")
    body = msg.get("message", "")

    if not body:
        return

    if BEAUTIFY_ENABLED:
        pretty = beautify_message(msg)
        send_message(title, pretty, msg.get("priority", 5))
        delete_message(msg_id)

# --- Websocket events ---
def on_message(ws, message):
    data = json.loads(message)
    if data.get("event") == "message":
        handle_message(data.get("message", {}))

def on_error(ws, error):
    print(f"[{BOT_NAME}] Websocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"[{BOT_NAME}] Websocket closed")

def on_open(ws):
    print(f"[{BOT_NAME}] Connected to Gotify stream")

# --- Startup ---
def main():
    print(f"[{BOT_NAME}] Starting add-on...")
    send_message("Startup", f"Good Day, I am {BOT_NAME}, ready to assist.")

    ws_url = f"{GOTIFY_URL.replace('http', 'ws')}/stream?token={CLIENT_TOKEN}"
    ws = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
    ws.run_forever()

if __name__ == "__main__":
    main()
