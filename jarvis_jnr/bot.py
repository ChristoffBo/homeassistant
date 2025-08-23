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
# Purge all messages for a specific app using CLIENT (admin) token
# -----------------------------
def purge_app_messages(appid):
    """Purge all messages for a specific app using CLIENT (admin) token"""
    if not appid:
        return False
    
    # Try both authentication methods for bulk purge
    print(f"[{BOT_NAME}] Attempting to purge all messages for app ID: {appid}")
    
    # Method 1: Query parameter
    try:
        url = f"{GOTIFY_URL}/application/{appid}/message?token={CLIENT_TOKEN}"
        print(f"[{BOT_NAME}] Purge URL (query): {url}")
        
        r = requests.delete(url, timeout=10)
        print(f"[{BOT_NAME}] Purge response: {r.status_code} - {r.text}")
        
        if r.status_code == 200:
            print(f"[{BOT_NAME}] ✅ Successfully purged all messages for app id={appid}")
            return True
            
    except Exception as e:
        print(f"[{BOT_NAME}] Purge method 1 failed: {e}")
    
    # Method 2: Header authentication  
    try:
        url = f"{GOTIFY_URL}/application/{appid}/message"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        print(f"[{BOT_NAME}] Purge URL (header): {url}")
        
        r = requests.delete(url, headers=headers, timeout=10)
        print(f"[{BOT_NAME}] Purge response (header): {r.status_code} - {r.text}")
        
        if r.status_code == 200:
            print(f"[{BOT_NAME}] ✅ Successfully purged all messages for app id={appid} (via header)")
            return True
        else:
            print(f"[{BOT_NAME}] ❌ Failed purge for app {appid}: {r.status_code} {r.text}")
            return False
            
    except Exception as e:
        print(f"[{BOT_NAME}] Purge method 2 failed: {e}")
        return False

# -----------------------------
# Delete specific message by ID
# -----------------------------
def delete_message(message_id):
    """Delete a specific message by its ID using CLIENT token"""
    if not message_id:
        return False
    
    try:
        # Try query parameter method
        url = f"{GOTIFY_URL}/message/{message_id}?token={CLIENT_TOKEN}"
        r = requests.delete(url, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] ✅ Deleted message ID: {message_id}")
            return True
            
        # Try header method
        url = f"{GOTIFY_URL}/message/{message_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] ✅ Deleted message ID: {message_id} (via header)")
            return True
        else:
            print(f"[{BOT_NAME}] ❌ Failed to delete message {message_id}: {r.status_code}")
            return False
            
    except Exception as e:
        print(f"[{BOT_NAME}] Error deleting message {message_id}: {e}")
        return False

# -----------------------------
# Test token permissions
# -----------------------------
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

# -----------------------------
# Resolve numeric app_id for Jarvis app
# -----------------------------
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
# Retention cleanup with Jarvis message cleanup
# -----------------------------
def retention_cleanup():
    """Clean up old messages including Jarvis's own beautified messages"""
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        msgs = r.json().get("messages", [])
        cutoff = time.time() - (RETENTION_HOURS * 3600)

        deleted_count = 0
        jarvis_deleted = 0
        
        for msg in msgs:
            try:
                ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
                msg_id = msg.get("id")
                appid = msg.get("appid")
                title = msg.get("title", "")
                
                # Check if message is old enough for cleanup
                if ts < cutoff and msg_id:
                    # Clean up all old messages, including Jarvis's own
                    if delete_message(msg_id):
                        deleted_count += 1
                        if appid == jarvis_app_id:
                            jarvis_deleted += 1
                            print(f"[{BOT_NAME}] Cleaned up old Jarvis message: '{title[:50]}...'")
                            
            except Exception as e:
                print(f"[{BOT_NAME}] Error checking msg {msg.get('id')}: {e}")
        
        if deleted_count > 0:
            print(f"[{BOT_NAME}] Retention cleanup: {deleted_count} total messages deleted ({jarvis_deleted} Jarvis messages)")
            
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed: {e}")

# -----------------------------
# Clean up old Jarvis messages specifically
# -----------------------------
def cleanup_old_jarvis_messages():
    """Clean up Jarvis's own old beautified messages"""
    if not jarvis_app_id:
        print(f"[{BOT_NAME}] No Jarvis app ID - cannot clean old messages")
        return
        
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        msgs = r.json().get("messages", [])
        
        # Clean messages older than 1 hour for Jarvis specifically
        cleanup_cutoff = time.time() - (1 * 3600)  # 1 hour
        deleted_count = 0
        
        for msg in msgs:
            try:
                if msg.get("appid") == jarvis_app_id:
                    ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
                    msg_id = msg.get("id")
                    title = msg.get("title", "")
                    
                    if ts < cleanup_cutoff and msg_id:
                        if delete_message(msg_id):
                            deleted_count += 1
                            print(f"[{BOT_NAME}] Cleaned old beautified message: '{title[:50]}...'")
                            
            except Exception as e:
                print(f"[{BOT_NAME}] Error processing Jarvis message {msg.get('id')}: {e}")
        
        if deleted_count > 0:
            print(f"[{BOT_NAME}] Cleaned up {deleted_count} old Jarvis messages")
            
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to cleanup old Jarvis messages: {e}")

def run_scheduler():
    # Initial cleanup if bulk purge is enabled
    if ENABLE_BULK_PURGE and jarvis_app_id:
        purge_app_messages(jarvis_app_id)
    
    # Schedule retention cleanup (includes Jarvis cleanup now)
    schedule.every(30).minutes.do(retention_cleanup)
    
    # Schedule specific Jarvis message cleanup more frequently
    schedule.every(10).minutes.do(cleanup_old_jarvis_messages)
    
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

                    # Skip Jarvis's own messages - CRITICAL CHECK
                    if jarvis_app_id and appid == jarvis_app_id:
                        print(f"[{BOT_NAME}] SKIPPING: Own message id={mid} (appid {appid} == jarvis {jarvis_app_id})")
                        continue

                    # Additional check: Skip messages that already have Jarvis branding
                    if BOT_NAME in title or BOT_ICON in message:
                        print(f"[{BOT_NAME}] SKIPPING: Message already has Jarvis branding")
                        continue

                    # Skip if no message ID
                    if not mid:
                        print(f"[{BOT_NAME}] SKIPPING: No message ID")
                        continue

                    print(f"[{BOT_NAME}] PROCESSING: message id={mid} title='{title}' from app={appid}")

                    # Delete the original message first (to prevent duplicates)
                    print(f"[{BOT_NAME}] Deleting original message {mid} before beautifying")
                    delete_success = delete_message(mid)
                    
                    if not delete_success:
                        print(f"[{BOT_NAME}] WARNING: Could not delete original message {mid}")

                    # Small delay to ensure deletion completes
                    await asyncio.sleep(0.5)

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
                        print(f"[{BOT_NAME}] ✅ Successfully processed and beautified message")
                    else:
                        print(f"[{BOT_NAME}] ❌ Failed to send beautified message")

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
