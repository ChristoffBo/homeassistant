import os, json, time, asyncio, requests, websockets, random, schedule
from datetime import datetime, timedelta

# -----------------------------
# Config
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", BOT_NAME)

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "false").lower() in ("1", "true", "yes")
WEATHER_LAT = float(os.getenv("WEATHER_LAT", "-26.2041"))
WEATHER_LON = float(os.getenv("WEATHER_LON", "28.0473"))
WEATHER_CITY = os.getenv("WEATHER_CITY", "Johannesburg")

DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "false").lower() in ("1", "true", "yes")

RADARR_ENABLED = os.getenv("RADARR_ENABLED", "false").lower() in ("1", "true", "yes")
RADARR_URL = os.getenv("RADARR_URL", "").rstrip("/")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")

SONARR_ENABLED = os.getenv("SONARR_ENABLED", "false").lower() in ("1", "true", "yes")
SONARR_URL = os.getenv("SONARR_URL", "").rstrip("/")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")

jarvis_app_id = None

# -----------------------------
# Messaging
# -----------------------------
def send_message(title, message, priority=5):
    try:
        url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
        data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Send error: {e}")

def delete_message(mid):
    if not mid:
        return False
    try:
        url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
        r = requests.delete(url, timeout=5)
        return r.status_code == 200
    except Exception as e:
        print(f"[{BOT_NAME}] Delete error: {e}")
        return False

def resolve_app_id():
    global jarvis_app_id
    try:
        r = requests.get(f"{GOTIFY_URL}/application", headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=5)
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Resolve app_id failed: {e}")

# -----------------------------
# Beautifier
# -----------------------------
def beautify_message(title, raw):
    text = raw.strip()
    lower = text.lower()
    has_image = "![](" in text or text.lower().endswith((".jpg", ".png", ".jpeg"))

    prefix_options = [
        ("error", "💀"), ("fail", "💥"), ("warning", "⚠️"),
        ("success", "✅"), ("done", "🎉"), ("start", "🚀"),
        ("update", "🔔"), ("download", "📥"), ("upload", "📤"),
        ("backup", "💾"), ("restore", "♻️"), ("weather", "🌦"),
        ("movie", "🎬"), ("series", "📺"), ("music", "🎵"),
    ]
    prefix = "💡"
    for key, emo in prefix_options:
        if key in lower:
            prefix = emo
            break

    ai_responses = [
        "🤔 Analyzing input…",
        "⚡ Processing request…",
        "🔍 Running checks…",
        "📡 Generating report…",
        "🧠 Engaging reasoning core…",
        "✅ Task complete.",
        "🎯 Operation successful.",
    ]
    insert = random.choice(ai_responses)

    closings = [
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🤖 Yours truly, {BOT_NAME}",
        f"📡 Report crafted by {BOT_NAME}",
        f"🧠 Insight provided by {BOT_NAME}",
        f"⚡ Powered by {BOT_NAME}",
        f"🎯 Task completed by {BOT_NAME}",
        f"📊 Analysis finished by {BOT_NAME}"
    ]
    closing = random.choice(closings)

    if has_image:
        return f"{prefix} {title}\n\n{insert}\n\n{text}\n\n{closing}"
    else:
        return f"{prefix} {text}\n\n{insert}\n\n{closing}"

# -----------------------------
# Weather
# -----------------------------
def get_weather():
    if not WEATHER_ENABLED:
        return "🌦 Weather module disabled."
    try:
        url = f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={WEATHER_LAT}&lon={WEATHER_LON}"
        headers = {"User-Agent": f"{BOT_NAME}/1.0"}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        now = data["properties"]["timeseries"][0]
        details = now["data"]["instant"]["details"]
        temp = details.get("air_temperature")
        wind = details.get("wind_speed")
        cloud = details.get("cloud_area_fraction")
        condition = "☀️ Clear"
        if cloud > 70: condition = "☁️ Overcast"
        elif cloud > 30: condition = "🌤 Partly cloudy"
        return f"{condition} in {WEATHER_CITY}, {temp}°C, wind {wind} m/s."
    except Exception as e:
        return f"🌦 Weather fetch error: {e}"

# -----------------------------
# Radarr / Sonarr Insights
# -----------------------------
def get_series_count():
    try:
        if SONARR_ENABLED:
            r = requests.get(f"{SONARR_URL}/api/v3/series", headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                return f"📺 You have {len(r.json())} series."
    except: pass
    return "📺 Could not fetch series count."

def get_movie_count():
    try:
        if RADARR_ENABLED:
            r = requests.get(f"{RADARR_URL}/api/v3/movie", headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                return f"🎬 You have {len(r.json())} movies."
    except: pass
    return "🎬 Could not fetch movie count."

def get_largest_series():
    try:
        if SONARR_ENABLED:
            r = requests.get(f"{SONARR_URL}/api/v3/series", headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                series = r.json()
                largest = max(series, key=lambda s: s.get("statistics", {}).get("sizeOnDisk", 0))
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
                series = r.json()
                longest = max(series, key=lambda s: s.get("statistics", {}).get("episodeFileCount", 0))
                count = longest["statistics"]["episodeFileCount"]
                return f"📺 Longest running series: {longest['title']} ({count} episodes)"
    except Exception as e:
        return f"📺 Error: {e}"
    return "📺 Could not fetch longest series."

def get_largest_movie():
    try:
        if RADARR_ENABLED:
            r = requests.get(f"{RADARR_URL}/api/v3/movie", headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                movies = r.json()
                movies = [m for m in movies if m.get("movieFile")]
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
                movies = r.json()
                longest = max(movies, key=lambda m: m.get("runtime", 0))
                runtime = longest.get("runtime", 0)
                return f"🎬 Longest movie: {longest['title']} ({runtime} min)"
    except Exception as e:
        return f"🎬 Error: {e}"
    return "🎬 Could not fetch longest movie."

# -----------------------------
# Digest
# -----------------------------
def get_digest():
    return "\n".join([
        "🗞 Digest Report",
        get_weather(),
        get_movie_count(),
        get_series_count(),
        get_largest_series(),
        get_longest_series(),
        get_largest_movie(),
        get_longest_movie(),
        f"\n🤖 Report generated by {BOT_NAME}"
    ])

# -----------------------------
# Cleanup + Scheduler
# -----------------------------
def retention_cleanup():
    try:
        r = requests.get(f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}", timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed: {e}")

def cleanup_non_jarvis_messages():
    if not jarvis_app_id: return
    try:
        r = requests.get(f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}", timeout=5).json()
        for msg in r.get("messages", []):
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
# Parser + Commands
# -----------------------------
def parse_command(title, raw):
    text = (title + " " + raw).strip().lower()
    if BOT_NAME.lower() not in text: return None
    if "movie" in text and "count" in text: return "movie_count"
    if "series" in text and "count" in text: return "series_count"
    if "largest series" in text: return "largest_series"
    if "longest series" in text: return "longest_series"
    if "largest movie" in text: return "largest_movie"
    if "longest movie" in text: return "longest_movie"
    if "digest" in text: return "digest"
    if "weather" in text: return "weather"
    return None

def handle_command(command):
    if command == "movie_count": return get_movie_count()
    if command == "series_count": return get_series_count()
    if command == "largest_series": return get_largest_series()
    if command == "longest_series": return get_longest_series()
    if command == "largest_movie": return get_largest_movie()
    if command == "longest_movie": return get_longest_movie()
    if command == "weather": return get_weather()
    if command == "digest": return get_digest()
    return "🤖 Unknown command."

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/stream?token={CLIENT_TOKEN}"
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        async for msg in ws:
            try:
                data = json.loads(msg)
                appid = data.get("appid")
                title = data.get("title", "")
                message = data.get("message", "")
                if jarvis_app_id and appid == jarvis_app_id:
                    continue
                command = parse_command(title, message)
                if command:
                    response = handle_command(command)
                    send_message("Command Response", response, priority=5)
                else:
                    beautified = beautify_message(title, message)
                    send_message(title, beautified, priority=0)
                    delete_message(data.get("id"))
            except Exception as e:
                print(f"[{BOT_NAME}] Error: {e}")

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    resolve_app_id()
    startup_msgs = [
        f"🤖 {BOT_NAME} online and operational.",
        f"🚀 Greetings! {BOT_NAME} is ready.",
        f"✨ Hello, I am {BOT_NAME}, your assistant.",
        f"🧩 Systems initialized. {BOT_NAME} at your service.",
        f"🎯 {BOT_NAME} reporting in.",
        f"📡 Connection established. {BOT_NAME} is live.",
        f"⚡ Boot sequence complete. {BOT_NAME} engaged.",
        f"🔔 {BOT_NAME} is standing by."
    ]
    send_message("Startup", random.choice(startup_msgs))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
