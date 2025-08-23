import os, json, time, asyncio, requests, websockets, schedule, datetime, random

# -----------------------------
# Config from environment (set in run.sh from options.json)
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")
ENABLE_BULK_PURGE = os.getenv("ENABLE_BULK_PURGE", "false").lower() in ("1", "true", "yes")

jarvis_app_id = None  # resolved on startup

# -----------------------------
# Send message (with APP token)
# -----------------------------
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": message,
        "priority": priority,
    }
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] Sent beautified: {title} (priority={priority})")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")
        return False

# -----------------------------
# Delete individual message by ID
# -----------------------------
def delete_message(message_id):
    """Delete a specific message by its ID using CLIENT token - tries multiple methods"""
    if not message_id:
        print(f"[{BOT_NAME}] No message ID provided for deletion")
        return False
    
    print(f"[{BOT_NAME}] Attempting to delete message ID: {message_id}")
    
    # Method 1: Query parameter (most common for Gotify)
    try:
        url = f"{GOTIFY_URL}/message/{message_id}?token={CLIENT_TOKEN}"
        print(f"[{BOT_NAME}] DELETE attempt 1 - URL: {url[:50]}...")
        
        r = requests.delete(url, timeout=10)
        print(f"[{BOT_NAME}] DELETE response: {r.status_code} - {r.text}")
        
        if r.status_code == 200:
            print(f"[{BOT_NAME}] ✅ Successfully deleted message ID {message_id} (query param)")
            return True
        elif r.status_code == 404:
            print(f"[{BOT_NAME}] ⚠️ Message {message_id} not found (already deleted?)")
            return True  # Consider this success since message is gone
            
    except Exception as e:
        print(f"[{BOT_NAME}] Method 1 failed: {e}")
    
    # Method 2: Header authentication
    try:
        url = f"{GOTIFY_URL}/message/{message_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        print(f"[{BOT_NAME}] DELETE attempt 2 - URL: {url} with header")
        
        r = requests.delete(url, headers=headers, timeout=10)
        print(f"[{BOT_NAME}] DELETE response (header): {r.status_code} - {r.text}")
        
        if r.status_code == 200:
            print(f"[{BOT_NAME}] ✅ Successfully deleted message ID {message_id} (header)")
            return True
        elif r.status_code == 404:
            print(f"[{BOT_NAME}] ⚠️ Message {message_id} not found (already deleted?)")
            return True
            
    except Exception as e:
        print(f"[{BOT_NAME}] Method 2 failed: {e}")
    
    # Method 3: Check if we can get message first (for debugging)
    try:
        get_url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(get_url, timeout=5)
        if r.status_code == 200:
            messages = r.json().get('messages', [])
            message_exists = any(msg.get('id') == message_id for msg in messages)
            print(f"[{BOT_NAME}] Message {message_id} exists in API: {message_exists}")
            if not message_exists:
                print(f"[{BOT_NAME}] Message {message_id} doesn't exist, considering deleted")
                return True
        else:
            print(f"[{BOT_NAME}] Cannot verify message existence: {r.status_code}")
    except Exception as e:
        print(f"[{BOT_NAME}] Cannot check message existence: {e}")
    
    print(f"[{BOT_NAME}] ❌ All deletion methods failed for message {message_id}")
    print(f"[{BOT_NAME}] Debug info:")
    print(f"[{BOT_NAME}]   - GOTIFY_URL: {GOTIFY_URL}")
    print(f"[{BOT_NAME}]   - CLIENT_TOKEN length: {len(CLIENT_TOKEN) if CLIENT_TOKEN else 'None'}")
    print(f"[{BOT_NAME}]   - CLIENT_TOKEN starts with: {CLIENT_TOKEN[:10] if CLIENT_TOKEN else 'None'}...")
    
    return False

# -----------------------------
# Bulk purge all messages for an app (keep this for cleanup)
# -----------------------------
def purge_app_messages(appid):
    if not appid:
        return
    url = f"{GOTIFY_URL}/application/{appid}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] Purged all messages for app id={appid}")
        else:
            print(f"[{BOT_NAME}] Failed purge for app {appid}: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[{BOT_NAME}] Purge error for app {appid}: {e}")

def test_token_permissions():
    """Test if CLIENT_TOKEN has proper permissions"""
    try:
        # Test getting messages
        print(f"[{BOT_NAME}] Testing CLIENT_TOKEN permissions...")
        
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5)
        
        if r.status_code == 200:
            print(f"[{BOT_NAME}] ✅ CLIENT_TOKEN can read messages")
            messages = r.json().get('messages', [])
            print(f"[{BOT_NAME}] Found {len(messages)} messages")
            
            # Try to find a message to test deletion on
            if messages:
                test_msg = messages[0]
                print(f"[{BOT_NAME}] Test message: ID={test_msg.get('id')}, Title='{test_msg.get('title', '')[:30]}...'")
        else:
            print(f"[{BOT_NAME}] ❌ CLIENT_TOKEN cannot read messages: {r.status_code} {r.text}")
            
        # Test getting applications  
        app_url = f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}"
        r = requests.get(app_url, timeout=5)
        
        if r.status_code == 200:
            print(f"[{BOT_NAME}] ✅ CLIENT_TOKEN can read applications")
        else:
            print(f"[{BOT_NAME}] ❌ CLIENT_TOKEN cannot read applications: {r.status_code}")
            
    except Exception as e:
        print(f"[{BOT_NAME}] Error testing token permissions: {e}")

# Test token permissions on startup
def resolve_app_id():
    global jarvis_app_id
    print(f"[{BOT_NAME}] Resolving app ID for app name: '{APP_NAME}'")
    try:
        url = f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}"
        print(f"[{BOT_NAME}] Getting applications from: {url}")
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        apps = r.json()
        
        print(f"[{BOT_NAME}] Found {len(apps)} applications:")
        for app in apps:
            app_name = app.get("name", "Unknown")
            app_id = app.get("id", "Unknown")
            print(f"[{BOT_NAME}]   - App: '{app_name}' (ID: {app_id})")
            
            if app_name == APP_NAME:
                jarvis_app_id = app_id
                print(f"[{BOT_NAME}] ✅ MATCHED! Resolved app '{APP_NAME}' to id={jarvis_app_id}")
                return
                
        print(f"[{BOT_NAME}] ❌ WARNING: Could not find app '{APP_NAME}' in available apps")
        print(f"[{BOT_NAME}] Available app names: {[app.get('name') for app in apps]}")
        
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")
        
    print(f"[{BOT_NAME}] Final jarvis_app_id = {jarvis_app_id}")

# -----------------------------
# AI-like beautifier
# -----------------------------
def beautify_message(title, raw):
    text = raw.strip()
    lower = text.lower()

    # Emoji prefix based on keywords
    prefix = "💡"
    if "error" in lower or "failed" in lower:
        prefix = "💀"
    elif "success" in lower or "completed" in lower or "done" in lower:
        prefix = "✅"
    elif "warning" in lower:
        prefix = "⚠️"
    elif "start" in lower or "starting" in lower:
        prefix = "🚀"

    closings = [
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🧩 Ever at your service, {BOT_NAME}",
        f"🤖 Yours truly, {BOT_NAME}",
    ]
    closing = random.choice(closings)

    return f"{prefix} {text}\n\n{closing}"

# -----------------------------
# Retention cleanup
# -----------------------------
def retention_cleanup():
    try:
        url = f"{GOTIFY_URL}/message"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.get(url, headers=headers, timeout=5)
        r.raise_for_status()
        msgs = r.json().get("messages", [])
        cutoff = time.time() - (RETENTION_HOURS * 3600)

        deleted_count = 0
        for msg in msgs:
            try:
                ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
                if ts < cutoff:
                    if delete_message(msg["id"]):
                        deleted_count += 1
            except Exception as e:
                print(f"[{BOT_NAME}] Error checking msg {msg.get('id')}: {e}")
        
        if deleted_count > 0:
            print(f"[{BOT_NAME}] Retention cleanup deleted {deleted_count} old messages")
            
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed: {e}")

def run_scheduler():
    # Initial cleanup if bulk purge is enabled
    if ENABLE_BULK_PURGE and jarvis_app_id:
        purge_app_messages(jarvis_app_id)
    
    # Schedule retention cleanup
    schedule.every(30).minutes.do(retention_cleanup)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Main async listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url += f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting to {ws_url}...")
    
    try:
        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
            print(f"[{BOT_NAME}] Connected! Listening for messages...")
            
            async for msg in ws:
                try:
                    print(f"[{BOT_NAME}] RAW WebSocket message received: {msg[:200]}...")
                    
                    data = json.loads(msg)
                    mid = data.get("id")
                    appid = data.get("appid")
                    title = data.get("title", "")
                    message = data.get("message", "")

                    print(f"[{BOT_NAME}] PARSED - ID: {mid}, AppID: {appid}, Title: '{title}', Jarvis AppID: {jarvis_app_id}")

                    # Debug: Show all message data
                    print(f"[{BOT_NAME}] Full message data: {json.dumps(data, indent=2)}")

                    # Skip Jarvis's own messages
                    if jarvis_app_id and appid == jarvis_app_id:
                        print(f"[{BOT_NAME}] SKIPPING: Own message id={mid} (appid {appid} == jarvis {jarvis_app_id})")
                        continue

                    # Skip if no message ID
                    if not mid:
                        print(f"[{BOT_NAME}] SKIPPING: No message ID")
                        continue

                    print(f"[{BOT_NAME}] PROCESSING: message id={mid} title='{title}' from app={appid}")

                    # Beautify if enabled
                    if BEAUTIFY_ENABLED:
                        final_msg = beautify_message(title, message)
                        print(f"[{BOT_NAME}] BEAUTIFIED message ready")
                    else:
                        final_msg = message
                        print(f"[{BOT_NAME}] Using original message (beautify disabled)")

                    # Send beautified message
                    repost_priority = 0 if SILENT_REPOST else 5
                    print(f"[{BOT_NAME}] SENDING beautified message with priority={repost_priority}")
                    send_success = send_message(title, final_msg, priority=repost_priority)
                    
                    if send_success:
                        # Only delete original if we successfully sent the beautified version
                        print(f"[{BOT_NAME}] SEND SUCCESS - Now attempting to delete original message {mid}")
                        delete_success = delete_message(mid)
                        if not delete_success:
                            print(f"[{BOT_NAME}] ❌ DELETE FAILED for message {mid}")
                        else:
                            print(f"[{BOT_NAME}] ✅ DELETE SUCCESS for message {mid}")
                    else:
                        print(f"[{BOT_NAME}] ❌ SEND FAILED - Not deleting original message {mid}")

                except json.JSONDecodeError as e:
                    print(f"[{BOT_NAME}] JSON decode error: {e}")
                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing message: {e}")
                    
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed: {e}")
        print(f"[{BOT_NAME}] Reconnecting in 10 seconds...")
        await asyncio.sleep(10)
        await listen()  # Reconnect

# -----------------------------
# Main entrypoint
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on...")

    # Test token permissions first
    test_token_permissions()
    
    resolve_app_id()

    startup_msg = random.choice([
        f"Good Day, I am {BOT_NAME}, ready to assist.",
        f"Greetings, {BOT_NAME} is now online and standing by.",
        f"🚀 {BOT_NAME} systems initialized and operational.",
        f"{BOT_NAME} reporting for duty.",
    ])
    send_message("Startup", startup_msg, priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Start both the listener and scheduler
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)

    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
