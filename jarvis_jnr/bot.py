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
# Beautifier (same as before with AI inserts)
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

        advice = "🙂 Looks like a fine day." if cloud < 30 else "☂️ You may want an umbrella." if cloud > 70 else "🌥 A bit cloudy, but manageable."

        return (
            f"{condition} in {WEATHER_CITY}, {temp}°C, wind {wind} m/s.\n"
            f"{advice}"
        )
    except Exception as e:
        return f"🌦 Weather fetch error: {e}"

# -----------------------------
# Radarr / Sonarr (cached lookups)
# -----------------------------
def get_series_count():
    try:
        if SONARR_ENABLED:
            url = f"{SONARR_URL}/api/v3/series"
            r = requests.get(url, headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                total = len(r.json())
                return f"📺 You have {total} series. {'Plenty to binge!' if total>30 else 'A modest collection.'}"
    except: pass
    return "📺 Could not fetch series count."

def get_movie_count():
    try:
        if RADARR_ENABLED:
            url = f"{RADARR_URL}/api/v3/movie"
            r = requests.get(url, headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
            if r.status_code == 200:
                total = len(r.json())
                return f"🎬 You have {total} movies. {'A true cinema archive!' if total>100 else 'Compact but quality.'}"
    except: pass
    return "🎬 Could not fetch movie count."

def get_upcoming_series():
    try:
        if SONARR_ENABLED:
            today = datetime.now().date()
            until = today + timedelta(days=7)
            series_map = {}
            sr = requests.get(f"{SONARR_URL}/api/v3/series", headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
            if sr.status_code == 200:
                for s in sr.json():
                    series_map[s["id"]] = s.get("title", "Unknown Show")
            r = requests.get(f"{SONARR_URL}/api/v3/calendar?start={today}&end={until}", headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
            if r.status_code == 200 and r.json():
                items = []
                for e in r.json():
                    sid = e.get("seriesId")
                    title = series_map.get(sid, "Unknown Show")
                    season = e.get("seasonNumber", "?")
                    ep = e.get("episodeNumber", "?")
                    airdate = e.get("airDate", "N/A")
                    items.append(f"• {title} - S{season}E{ep} ({airdate})")
                return "📺 Upcoming episodes:\n" + "\n".join(items[:10]) + f"\n⚡ {len(items)} episodes airing this week!"
    except Exception as e:
        return f"📺 Error fetching upcoming series: {e}"
    return "📺 No upcoming episodes this week. 📭 A quiet schedule ahead."

def get_upcoming_movies():
    try:
        if RADARR_ENABLED:
            today = datetime.now().date()
            until = today + timedelta(days=7)
            movie_map = {}
            mr = requests.get(f"{RADARR_URL}/api/v3/movie", headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
            if mr.status_code == 200:
                for m in mr.json():
                    movie_map[m["id"]] = m.get("title", "Unknown Movie")
            r = requests.get(f"{RADARR_URL}/api/v3/calendar?start={today}&end={until}", headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
            if r.status_code == 200 and r.json():
                items = []
                for m in r.json():
                    mid = m.get("movieId")
                    title = movie_map.get(mid, m.get("title", "Unknown Movie"))
                    airdate = m.get("inCinemas", "N/A")[:10]
                    items.append(f"• {title} ({airdate})")
                return "🎬 Upcoming movies:\n" + "\n".join(items[:10]) + f"\n🍿 {len(items)} movies arriving this week!"
    except Exception as e:
        return f"🎬 Error fetching upcoming movies: {e}"
    return "🎬 No upcoming movies this week. 🎞 Time to revisit old favorites!"

# -----------------------------
# Digest with Time-based Greetings
# -----------------------------
def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12: return "🌅 Good morning!"
    if 12 <= hour < 18: return "🌞 Good afternoon!"
    if 18 <= hour < 22: return "🌆 Good evening!"
    return "🌙 Good night!"

def get_digest():
    parts = []
    parts.append(f"{get_greeting()} Here is your personalized digest:\n")
    parts.append(get_weather())
    parts.append(get_movie_count())
    parts.append(get_series_count())
    parts.append(get_upcoming_movies())
    parts.append(get_upcoming_series())
    parts.append(random.choice([
        f"🤖 That’s all for now, {BOT_NAME} signing off.",
        f"✨ Digest prepared and delivered by {BOT_NAME}.",
        f"📡 Stay tuned for more updates with {BOT_NAME}.",
    ]))
    return "\n\n".join(parts)

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
# Parser + Command Handling
# -----------------------------
def parse_command(title, raw):
    text = (title + " " + raw).strip().lower()
    if BOT_NAME.lower() not in text: return None
    if "movie" in text and "count" in text: return "movie_count"
    if "series" in text and "count" in text: return "series_count"
    if "upcoming movie" in text: return "movies_upcoming"
    if "upcoming series" in text: return "series_upcoming"
    if "series" in text: return "series_upcoming"
    if "movies" in text: return "movies_upcoming"
    if "weather" in text: return "weather"
    if "digest" in text: return "digest"
    if "help" in text: return "help"
    return None

def handle_command(command):
    if command == "movie_count": return get_movie_count()
    if command == "series_count": return get_series_count()
    if command == "movies_upcoming": return get_upcoming_movies()
    if command == "series_upcoming": return get_upcoming_series()
    if command == "weather": return get_weather()
    if command == "digest": return get_digest()
    if command == "help":
        return (
            f"🤖 Commands for {BOT_NAME}:\n"
            "• Jarvis movies count → total movies\n"
            "• Jarvis series count → total series\n"
            "• Jarvis upcoming movies → next 7 days\n"
            "• Jarvis upcoming series → next 7 days\n"
            "• Jarvis weather → forecast\n"
            "• Jarvis digest → daily report\n"
        )
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
