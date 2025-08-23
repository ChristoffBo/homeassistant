import os, json, time, asyncio, requests, websockets, schedule, random
from datetime import datetime, timedelta

# -----------------------------
# Config
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis Jnr")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", BOT_NAME)

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")

WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "false").lower() in ("1", "true", "yes")
WEATHER_LAT = float(os.getenv("WEATHER_LAT", "-26.2041"))
WEATHER_LON = float(os.getenv("WEATHER_LON", "28.0473"))
WEATHER_CITY = os.getenv("WEATHER_CITY", "Johannesburg")
WEATHER_TIME = os.getenv("WEATHER_TIME", "07:00")

DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "false").lower() in ("1", "true", "yes")
DIGEST_TIME = os.getenv("DIGEST_TIME", "08:00")

RADARR_ENABLED = os.getenv("RADARR_ENABLED", "false").lower() in ("1", "true", "yes")
RADARR_URL = os.getenv("RADARR_URL", "").rstrip("/")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")
RADARR_TIME = os.getenv("RADARR_TIME", "07:30")

SONARR_ENABLED = os.getenv("SONARR_ENABLED", "false").lower() in ("1", "true", "yes")
SONARR_URL = os.getenv("SONARR_URL", "").rstrip("/")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")
SONARR_TIME = os.getenv("SONARR_TIME", "07:30")

jarvis_app_id = None
series_cache = {}
movie_cache = {}

# -----------------------------
# Beautifier with Image Support
# -----------------------------
def beautify_message(title, raw):
    text = raw.strip()
    lower = text.lower()

    has_image = "![](" in text or text.lower().endswith((".jpg", ".png", ".jpeg"))

    prefix = "💡"
    if "error" in lower: prefix = "💀"
    elif "success" in lower: prefix = "✅"
    elif "warning" in lower: prefix = "⚠️"
    elif "start" in lower: prefix = "🚀"
    elif "grabbed" in lower or "downloaded" in lower: prefix = "📥"

    closings = [
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🧩 Ever at your service, {BOT_NAME}",
        f"🤖 Yours truly, {BOT_NAME}",
        f"📡 At your command, {BOT_NAME}",
        f"🔧 Report crafted by {BOT_NAME}",
        f"🤝 Always assisting, {BOT_NAME}",
        f"🧠 Thoughtfully yours, {BOT_NAME}"
    ]
    closing = random.choice(closings)

    if has_image:
        return f"{prefix} {title}\n\n{text}\n\n{closing}"
    else:
        return f"{prefix} {text}\n\n{closing}"

# -----------------------------
# Helpers
# -----------------------------
def send_message(title, message, priority=5):
    try:
        url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
        data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent: {title}")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Send error: {e}")

def resolve_app_id():
    global jarvis_app_id
    try:
        r = requests.get(f"{GOTIFY_URL}/application", headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=5)
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] ✅ Jarvis app_id={jarvis_app_id}")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Resolve app_id failed: {e}")

# -----------------------------
# Count functions
# -----------------------------
def get_series_count():
    if not SONARR_ENABLED or not SONARR_API_KEY:
        return "📺 Sonarr is not enabled or misconfigured."
    try:
        url = f"{SONARR_URL}/api/v3/series"
        r = requests.get(url, headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
        if r.status_code == 200:
            return f"📺 You currently have {len(r.json())} series in your Sonarr library."
    except Exception as e:
        return f"📺 Error fetching series count: {e}"

def get_movie_count():
    if not RADARR_ENABLED or not RADARR_API_KEY:
        return "🎬 Radarr is not enabled or misconfigured."
    try:
        url = f"{RADARR_URL}/api/v3/movie"
        r = requests.get(url, headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
        if r.status_code == 200:
            return f"🎬 Your Radarr library contains {len(r.json())} movies."
    except Exception as e:
        return f"🎬 Error fetching movie count: {e}"

# -----------------------------
# Command parser
# -----------------------------
def parse_command(title, raw):
    bot_name_lower = BOT_NAME.lower()
    text = (title + " " + raw).strip().lower()
    if bot_name_lower not in text:
        return None

    if "series count" in text or "series amount" in text or "how many series" in text:
        return "series_count"
    if "movies count" in text or "movies amount" in text or "how many movies" in text:
        return "movie_count"
    if "radarr" in text or "movie" in text:
        return "radarr_upcoming"
    if "sonarr" in text or "show" in text or "series" in text:
        return "sonarr_upcoming"
    if "weather" in text:
        return "weather"
    if "digest" in text:
        return "digest"
    if "help" in text:
        return "help"
    return None

def handle_command(command):
    if command == "series_count": return get_series_count()
    if command == "movie_count": return get_movie_count()
    if command == "help":
        return (
            f"🤖 Hello, I am {BOT_NAME}, your AI assistant.\n\n"
            "• 'Jarvis movies count' → total movies\n"
            "• 'Jarvis series count' → total series\n"
            "• 'Jarvis movies' → upcoming movies\n"
            "• 'Jarvis series' → upcoming episodes\n"
            "• 'Jarvis weather' → weather update\n"
            "• 'Jarvis digest' → daily report\n"
        )
    return f"🤖 I didn’t understand. Try 'Jarvis help' for a list of commands."

# -----------------------------
# Async WebSocket listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting to {ws_url}...")
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        async for msg in ws:
            try:
                data = json.loads(msg)
                mid = data.get("id")
                appid = data.get("appid")
                title = data.get("title", "")
                message = data.get("message", "")

                # Skip own messages
                if jarvis_app_id and appid == jarvis_app_id:
                    continue

                command = parse_command(title, message)
                if command:
                    response = handle_command(command)
                    send_message("Command Response", response, priority=5)
                    continue

                if BEAUTIFY_ENABLED:
                    final_msg = beautify_message(title, message)
                    send_message(title, final_msg, priority=(0 if SILENT_REPOST else 5))

            except Exception as e:
                print(f"[{BOT_NAME}] Error processing WS msg: {e}")

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] 🚀 Starting...")
    resolve_app_id()

    startup_msgs = [
        f"🤖 {BOT_NAME} online and operational.",
        f"🚀 Greetings! {BOT_NAME} systems ready.",
        f"✨ Hello, I am {BOT_NAME}, your AI companion.",
        f"📡 {BOT_NAME} is standing by, awaiting instructions."
    ]
    send_message("Startup", random.choice(startup_msgs))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_forever()
