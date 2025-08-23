import os, json, time, asyncio, requests, websockets, schedule, datetime

BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
GOTIFY_TOKEN = os.getenv("GOTIFY_TOKEN")
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={GOTIFY_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        requests.post(url, json=data, timeout=5)
    except Exception as e:
        print("[Jarvis Jnr] Failed to send message:", e)

async def listen():
    ws_url = f"{GOTIFY_URL}/stream?token={GOTIFY_TOKEN}"
    async with websockets.connect(ws_url) as ws:
        async for msg in ws:
            data = json.loads(msg)
            title = data.get("title","")
            message = data.get("message","")
            mid = data.get("id")
            # Beautify + repost
            if os.getenv("BEAUTIFY_ENABLED","true") == "true":
                new = f"✨ {message.capitalize()}"
                send_message(title, new)
                try:
                    requests.delete(f"{GOTIFY_URL}/message/{mid}?token={GOTIFY_TOKEN}")
                except: pass

def retention_cleanup():
    url = f"{GOTIFY_URL}/message?token={GOTIFY_TOKEN}"
    r = requests.get(url).json()
    cutoff = time.time() - (RETENTION_HOURS * 3600)
    for msg in r.get("messages", []):
        ts = datetime.datetime.fromisoformat(msg["date"].replace("Z","+00:00")).timestamp()
        if ts < cutoff:
            requests.delete(f"{GOTIFY_URL}/message/{msg['id']}?token={GOTIFY_TOKEN}")

def run_scheduler():
    schedule.every(30).minutes.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    send_message("Startup", "Jarvis Jnr bot is now running.")
    loop = asyncio.get_event_loop()
    loop.create_task(listen())
    run_scheduler()
