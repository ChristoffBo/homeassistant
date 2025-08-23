import os, json, time, asyncio, requests, websockets, schedule, datetime, random

# -----------------------------
# Config from environment
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

# Radarr/Sonarr
RADARR_ENABLED = os.getenv("RADARR_ENABLED", "false").lower() in ("1", "true", "yes")
RADARR_URL = os.getenv("RADARR_URL", "")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")

SONARR_ENABLED = os.getenv("SONARR_ENABLED", "false").lower() in ("1", "true", "yes")
SONARR_URL = os.getenv("SONARR_URL", "")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")

jarvis_app_id = None

# -----------------------------
# Gotify Messaging
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
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")
        return False

def delete_message(message_id):
    if not message_id:
        return False
    try:
        url = f"{GOTIFY_URL}/message/{message_id}?token={CLIENT_TOKEN}"
        r = requests.delete(url, timeout=10)
        if r.status_code == 200:
            return True
        url = f"{GOTIFY_URL}/message/{message_id}"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        r = requests.delete(url, headers=headers, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[{BOT_NAME}] Error deleting message {message_id}: {e}")
        return False

def resolve_app_id():
    global jarvis_app_id
    try:
        r = requests.get(f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}", timeout=5)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] Resolved app ID: {jarvis_app_id}")
                return
    except Exception as e:
        print(f"[{BOT_NAME}] Could not resolve app id: {e}")

# -----------------------------
# Cleanup
# -----------------------------
def retention_cleanup():
    try:
        r = requests.get(f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}", timeout=5)
        r.raise_for_status()
        msgs = r.json().get("messages", [])
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in msgs:
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed: {e}")

def cleanup_non_jarvis_messages():
    if not jarvis_app_id:
        return
    try:
        r = requests.get(f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}", timeout=5)
        r.raise_for_status()
        msgs = r.json().get("messages", [])
        for msg in msgs:
            if msg.get("appid") != jarvis_app_id:
                delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Non-Jarvis cleanup failed: {e}")

def run_scheduler():
    schedule.every(5).minutes.do(retention_cleanup)
    schedule.every(5).seconds.do(cleanup_non_jarvis_messages)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Beautifier
# -----------------------------
def beautify_message(title, raw):
    text = raw.strip()
    lower = text.lower()

    prefix = "💡"
    if "error" in lower or "failed" in lower: prefix = "💀"
    elif "success" in lower or "completed" in lower: prefix = "✅"
    elif "warning" in lower: prefix = "⚠️"
    elif "start" in lower: prefix = "🚀"

    closings = [
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🧩 Ever at your service, {BOT_NAME}",
        f"🤖 Yours truly, {BOT_NAME}",
        f"🧠 Insight provided by {BOT_NAME}",
    ]
    closing = random.choice(closings)

    return f"{prefix} {text}\n\n{closing}"

# -----------------------------
# Radarr / Sonarr Insights
# -----------------------------
def get_movie_count():
    try:
        if RADARR_ENABLED:
            r = requests.get(f"{RADARR_URL}/api/v3/movie", headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                return f"🎬 You have {len(r.json())} movies."
    except Exception as e:
        return f"🎬 Error: {e}"
    return "🎬 Could not fetch movie count."

def get_series_count():
    try:
        if SONARR_ENABLED:
            r = requests.get(f"{SONARR_URL}/api/v3/series", headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                return f"📺 You have {len(r.json())} series."
    except Exception as e:
        return f"📺 Error: {e}"
    return "📺 Could not fetch series count."

def get_largest_series():
    try:
        if SONARR_ENABLED:
            r = requests.get(f"{SONARR_URL}/api/v3/series", headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                series = [s for s in r.json() if "statistics" in s and s["statistics"].get("sizeOnDisk", 0) > 0]
                if not series: return "📺 No valid series found with size data."
                largest = max(series, key=lambda s: s["statistics"]["sizeOnDisk"])
                size_gb = largest["statistics"]["sizeOnDisk"] / (1024**3)
                return f"📺 Largest series: {largest['title']} ({size_gb:.1f} GB)"
    except Exception as e:
        return f"📺 Error: {e}"
    return "📺 Could not fetch largest series."

def get_longest_series():
    try:
        if SONARR_ENABLED:
            r = requests.get(f"{SONARR_URL}/api/v3/series", headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                series = [s for s in r.json() if "statistics" in s and s["statistics"].get("episodeFileCount", 0) > 0]
                if not series: return "📺 No valid series found with episode data."
                longest = max(series, key=lambda s: s["statistics"]["episodeFileCount"])
                count = longest["statistics"]["episodeFileCount"]
                return f"📺 Longest series: {longest['title']} ({count} episodes)"
    except Exception as e:
        return f"📺 Error: {e}"
    return "📺 Could not fetch longest series."

def get_largest_movie():
    try:
        if RADARR_ENABLED:
            r = requests.get(f"{RADARR_URL}/api/v3/movie", headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                movies = [m for m in r.json() if m.get("movieFile")]
                if not movies: return "🎬 No movies with file data found."
                largest = max(movies, key=lambda m: m["movieFile"]["size"])
                size_gb = largest["movieFile"]["size"] / (1024**3)
                return f"🎬 Largest movie: {largest['title']} ({size_gb:.1f} GB)"
    except Exception as e:
        return f"🎬 Error: {e}"
    return "🎬 Could not fetch largest movie."

def get_longest_movie():
    try:
        if RADARR_ENABLED:
            r = requests.get(f"{RADARR_URL}/api/v3/movie", headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                movies = [m for m in r.json() if m.get("runtime", 0) > 0]
                if not movies: return "🎬 No movies with runtime info found."
                longest = max(movies, key=lambda m: m.get("runtime", 0))
                runtime = longest.get("runtime", 0)
                return f"🎬 Longest movie: {longest['title']} ({runtime} min)"
    except Exception as e:
        return f"🎬 Error: {e}"
    return "🎬 Could not fetch longest movie."

# -----------------------------
# WebSocket Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/stream?token={CLIENT_TOKEN}"
    try:
        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
            async for msg in ws:
                try:
                    data = json.loads(msg)
                    mid, appid = data.get("id"), data.get("appid")
                    title, message = data.get("title", ""), data.get("message", "")

                    if jarvis_app_id and appid == jarvis_app_id:
                        continue

                    if BOT_NAME in title or BOT_ICON in message:
                        continue

                    if not mid:
                        continue

                    # Commands
                    cmd = message.strip().lower()
                    response = None

                    if cmd in ["jarvis movie count", "jarvis movies", "movies count"]:
                        response = get_movie_count()
                    elif cmd in ["jarvis series count", "jarvis series", "series count"]:
                        response = get_series_count()
                    elif cmd in ["jarvis largest series"]:
                        response = get_largest_series()
                    elif cmd in ["jarvis longest series"]:
                        response = get_longest_series()
                    elif cmd in ["jarvis largest movie"]:
                        response = get_largest_movie()
                    elif cmd in ["jarvis longest movie"]:
                        response = get_longest_movie()

                    if response:
                        send_message("Command Response", response, priority=0 if SILENT_REPOST else 5)
                        delete_message(mid)
                        continue

                    # Normal beautify repost
                    final_msg = beautify_message(title, message) if BEAUTIFY_ENABLED else message
                    send_success = send_message(title, final_msg, priority=0 if SILENT_REPOST else 5)
                    if send_success: delete_message(mid)

                except Exception as e:
                    print(f"[{BOT_NAME}] Error processing: {e}")
    except Exception as e:
        print(f"[{BOT_NAME}] WebSocket connection failed: {e}")
        await asyncio.sleep(10)
        await listen()

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on...")
    resolve_app_id()

    startup_msg = random.choice([
        f"🚀 {BOT_NAME} systems initialized.",
        f"{BOT_NAME} is online and operational.",
        f"🤖 Greetings! {BOT_NAME} reporting for duty.",
        f"✨ Good day! {BOT_NAME} ready to assist.",
    ])
    send_message("Startup", startup_msg, priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
