import os, json, time, requests, websocket, threading, datetime

# Config from env (set in run.sh from options.json)
BOT_NAME = os.getenv("BOT_NAME", "Jarvis")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")        # for sending
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")  # for deleting
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

# Get the app ID for this bot to avoid processing our own messages
BOT_APP_ID = None

def get_bot_app_id():
    """Get our bot's app ID to avoid processing our own messages."""
    global BOT_APP_ID
    try:
        url = f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        apps = r.json()
        
        # Find our app by token (last part of APP_TOKEN)
        for app in apps:
            if app.get('token') == APP_TOKEN:
                BOT_APP_ID = app.get('id')
                print(f"[{BOT_NAME}] Found bot app ID: {BOT_APP_ID}")
                return BOT_APP_ID
                
        print(f"[{BOT_NAME}] Could not find bot app ID")
        return None
    except Exception as e:
        print(f"[{BOT_NAME}] Error getting app ID: {e}")
        return None

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
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")
        return False

def delete_message(mid):
    """Delete message via CLIENT (admin) token."""
    if not mid:
        print(f"[{BOT_NAME}] No message ID provided for deletion")
        return False
        
    url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
    try:
        r = requests.delete(url, timeout=5)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] Deleted original message {mid}")
            return True
        else:
            print(f"[{BOT_NAME}] Failed to delete {mid}: {r.status_code} {r.text}")
            return False
    except Exception as e:
        print(f"[{BOT_NAME}] Delete error: {e}")
        return False

def beautify_text(title, message):
    """Make messages look nicer."""
    if not message:
        message = "No content"
    return f"✨ {title}\n\n{message.strip().capitalize()}"

def on_message(ws, raw):
    try:
        data = json.loads(raw)
        mid = data.get("id")
        appid = data.get("appid")
        title = data.get("title", "")
        message = data.get("message", "")
        
        print(f"[{BOT_NAME}] Received message ID {mid} from app {appid}")
        
        # Skip if no message ID
        if not mid:
            print(f"[{BOT_NAME}] No message ID, skipping")
            return
            
        # Skip if it's from our bot app
        if BOT_APP_ID and appid == BOT_APP_ID:
            print(f"[{BOT_NAME}] Ignoring own message ID {mid}")
            return
            
        # Additional check: if message contains our bot signature
        if BOT_NAME in title and BOT_ICON in message:
            print(f"[{BOT_NAME}] Ignoring message with bot signature ID {mid}")
            return
        
        print(f"[{BOT_NAME}] Processing message: '{title}' - '{message[:50]}...'")
        
        # Beautify and send new message
        beautified = beautify_text(title, message)
        if send_message(title, beautified):
            # Only delete original if we successfully sent the beautified version
            delete_message(mid)
        else:
            print(f"[{BOT_NAME}] Not deleting original message {mid} due to send failure")
            
    except json.JSONDecodeError as e:
        print(f"[{BOT_NAME}] JSON decode error: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] Error processing message: {e}")

def on_error(ws, error):
    print(f"[{BOT_NAME}] WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"[{BOT_NAME}] WebSocket closed: {close_status_code} {close_msg}")
    time.sleep(5)
    start_ws()  # reconnect

def on_open(ws):
    print(f"[{BOT_NAME}] Connected! Listening to Gotify...")

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
    # Get bot app ID first
    get_bot_app_id()
    
    # Send startup message
    send_message("Startup", f"Good Day, I am {BOT_NAME}, ready to assist.")
    
    # Start WebSocket listener
    start_ws()
