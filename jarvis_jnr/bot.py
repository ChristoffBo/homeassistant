import os, json, time, asyncio, requests, websockets, schedule, datetime, random

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
ENABLE_BULK_PURGE = os.getenv("ENABLE_BULK_PURGE", "false").lower() in ("1", "true", "yes")

jarvis_app_id = None

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
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")

def delete_message(mid):
    if not mid:
        return False
    url = f"{GOTIFY_URL}/message/{mid}"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    for attempt in range(3):
        try:
            r = requests.delete(url, headers=headers, timeout=5)
            if r.status_code == 200:
                print(f"[{BOT_NAME}] Deleted original message {mid}")
                return True
            elif r.status_code == 404:
                print(f"[{BOT_NAME}] Message {mid} already gone (404)")
                return True
            else:
                print(f"[{BOT_NAME}] Delete {mid} failed: {r.status_code} {r.text}")
        except Exception as e:
            print(f"[{BOT_NAME}] Delete attempt {attempt+1} error: {e}")
        time.sleep(2 ** attempt)
    return False

def bulk_purge_app_messages():
    if not jarvis_app_id:
        print(f"[{BOT_NAME}] Can't bulk purge—app_id unknown.")
        return
    url = f"{GOTIFY_URL}/application/{jarvis_app_id}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.delete(url, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[{BOT_NAME}] Bulk-purged all messages from application id {jarvis_app_id}")
        else:
            print(f"[{BOT_NAME}] Bulk purge failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[{BOT_NAME}] Bulk purge error: {e}")

def resolve_app_id():
    global jarvis_app_id
    try:
        r = requests.get(f"{GOTIFY_URL}/application", headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=5)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] Resolved app '{APP_NAME}' to id={jarvis_app_id}")
                return
        print(f"[{BOT_NAME}] WARNING: Could not find app {APP_NAME}")
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to resolve app id: {e}")

def beautify_message(title, raw):
    text = raw.strip()
    lower = text.lower()
    prefix = "💡"
    if "error" in lower or "failed" in lower:
        prefix = "💀"
    elif "success" in lower or "completed" in lower:
        prefix = "✅"
    elif "warning" in lower:
        prefix = "⚠️"
    elif "start" in lower:
        prefix = "🚀"
    closings = [
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🧩 Ever at your service, {BOT_NAME}",
        f"🤖 Yours truly, {BOT_NAME}",
    ]
    closing = random.choice(closings)
    return f"{prefix} {text}\n\n{closing}"

def retention_cleanup():
    try:
        url = f"{GOTIFY_URL}/message"
        r = requests.get(url, headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=5)
        r.raise_for_status()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.json().get("messages", []):
            try:
                ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
                if ts < cutoff:
                    delete_message(msg["id"])
            except Exception as e:
                print(f"[{BOT_NAME}] Error checking msg {msg.get('id')}: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed: {e}")

def run_scheduler():
    if ENABLE_BULK_PURGE:
        # Run bulk purge on startup then schedule retention cleanup
        bulk_purge_app_messages()
    schedule.every(30).minutes.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    mid = data.get("id")
                    appid = data.get("appid")
                    title = data.get("title", "")
                    message = data.get("message", "")

                    if jarvis_app_id and appid == jarvis_app_id:
                        continue

                    print(f"[{BOT_NAME}] Processing message id={mid} title='{title}'")
                    beautified = beautify_message(title, message)
                    send_message(title, beautified, priority=(0 if SILENT_REPOST else 5))
                    delete_message(mid)
                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed: {e}")
        await asyncio.sleep(10)
        await listen()

if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on...")
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
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    print(f"[{BOT_NAME}] Event loop started.")
    loop.run_forever()
