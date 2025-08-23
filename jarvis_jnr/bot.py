import os, json, time, asyncio, requests, websockets, schedule, datetime

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

# Fetch Jarvis appid at startup (so we can filter out its own posts)
JARVIS_APPID = None
try:
    apps = requests.get(f"{GOTIFY_URL}/application?token={APP_TOKEN}", timeout=5).json()
    if isinstance(apps, list) and len(apps) > 0:
        JARVIS_APPID = apps[0].get("id")
        print(f"[Jarvis Jnr] Detected own appid = {JARVIS_APPID}")
except Exception as e:
    print("[Jarvis Jnr] Failed to detect appid:", e)

def send_message(title, message, priority=5):
    """Send a message using APP token (post as Jarvis App)."""
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print("[Jarvis Jnr] Failed to send message:", e)

async def listen():
    """Listen using CLIENT token (see all messages)."""
    ws_url = f"{GOTIFY_URL.replace('http', 'ws')}/stream?token={CLIENT_TOKEN}"
    print(f"[Jarvis Jnr] Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    title = data.get("title", "")
                    message = data.get("message", "")
                    mid = data.get("id")
                    appid = data.get("appid")

                    # Skip Jarvis’ own posts
                    if JARVIS_APPID and appid == JARVIS_APPID:
                        continue

                    # Beautify
                    if os.getenv("BEAUTIFY_ENABLED", "true") == "true":
                        new = f"✨ {message.capitalize()}"
                        send_message(title, new)
                        # delete original
                        try:
                            requests.delete(f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}")
                        except:
                            pass
                except Exception as e:
                    print("[Jarvis Jnr] Error processing message:", e)
    except Exception as e:
        print("[Jarvis Jnr] WebSocket connection failed:", e)
        await asyncio.sleep(10)
        await listen()

def retention_cleanup():
    """Delete old messages past retention_hours."""
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z","+00:00")).timestamp()
            if ts < cutoff:
                requests.delete(f"{GOTIFY_URL}/message/{msg['id']}?token={CLIENT_TOKEN}")
                print(f"[Jarvis Jnr] Deleted old message {msg['id']}")
    except Exception as e:
        print("[Jarvis Jnr] Retention cleanup failed:", e)

def run_scheduler():
    schedule.every(30).minutes.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    send_message("Startup", "Jarvis Jnr bot is now running.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
