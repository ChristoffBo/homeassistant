import os, json, time, requests, websocket, threading, datetime

# Config from env (set in run.sh from options.json)
BOT_NAME = os.getenv("BOT_NAME", "Jarvis")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")        # for sending
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")  # for deleting
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

STREAM_URL = GOTIFY_URL.replace("http", "ws") + f"/stream?token={CLIENT_TOKEN}"

print(f"[{BOT_NAME}] Starting add-on...")
print(f"[{BOT_NAME}] Connecting to {STREAM_URL} ...")

def send_message(title, message, priority=5):
    """Send beautified message via APP token."""
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": f"{message}\n\n{BOT_ICON} With regards, {BOT_NAME}",
        "priority": priority
    }
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] Sent beautified: {title}")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")

def delete_message(mid):
    """Delete message via CLIENT (admin) token."""
    url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
    try:
        r = requests.delete(url, timeout=5)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] Deleted original message {mid}")
        else:
            print(f"[{BOT_NAME}] Failed to delete {mid}: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[{BOT_NAME}] Delete error: {e}")

def beautify_text(title, message):
    """Make messages look nicer."""
    return f"✨ {title}\n\n{message.capitalize()}"

def on_message(ws, raw):
    try:
        data = json.loads(raw)
        mid = data.get("id")
        appid = data.get("appid")
        title = data.get("title", "")
        message = data.get("message", "")

        # Ignore if it's Jarvis itself (appid will match Jarvis’ app)
        if appid and APP_TOKEN in message:
            print(f"[{BOT_NAME}] Ignoring self message id {mid}")
            return

        beautified = beautify_text(title, message)
        send_message(title, beautified)
        delete_message(mid)

    except Exception as e:
        print(f"[{BOT_NAME}] Error processing message: {e}")

def on_error(ws, error):
    print(f"[{BOT_NAME}] WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"[{BOT_NAME}] WebSocket closed: {close_status_code} {close_msg}")
    time.sleep(5)
    start_ws()  # reconnect

def on_open(ws):
    print(f"[{BOT_NAME}] Listening to Gotify...")

def start_ws():
    ws = websocket.WebSocketApp(
        STREAM_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open
    )
    ws.run_forever(ping_interval=30, ping_timeout=10)

if __name__ == "__main__":
    send_message("Startup", f"Good Day, I am {BOT_NAME}, ready to assist.")
    start_ws()
