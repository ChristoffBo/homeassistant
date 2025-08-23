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

# Retention / cleanup
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))

# Radarr
RADARR_ENABLED = os.getenv("RADARR_ENABLED", "false").lower() in ("1", "true", "yes")
RADARR_URL = os.getenv("RADARR_URL", "")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")

# Sonarr
SONARR_ENABLED = os.getenv("SONARR_ENABLED", "false").lower() in ("1", "true", "yes")
SONARR_URL = os.getenv("SONARR_URL", "")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")

# Weather
WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "false").lower() in ("1", "true", "yes")
WEATHER_API = os.getenv("WEATHER_API", "open-meteo")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
WEATHER_CITY = os.getenv("WEATHER_CITY", "Johannesburg")
WEATHER_LAT = os.getenv("WEATHER_LAT", "-26.2041")
WEATHER_LON = os.getenv("WEATHER_LON", "28.0473")

jarvis_app_id = None

# -----------------------------
# Gotify helpers
# -----------------------------
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {
        "title": f"{BOT_ICON} {BOT_NAME}: {title}",
        "message": message,
        "priority": priority,
    }
    try:
        r = requests.post(url, json=data, timeout=10)
        r.raise_for_status()
        print(f"[{BOT_NAME}] Sent message: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] Failed to send message: {e}")
        return False

def delete_message(mid):
    if not mid: return False
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
        r = requests.get(f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}", timeout=5)
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app["id"]
                print(f"[{BOT_NAME}] Resolved app id={jarvis_app_id}")
    except Exception as e:
        print(f"[{BOT_NAME}] Resolve app id failed: {e}")

# -----------------------------
# Cleanup
# -----------------------------
def retention_cleanup():
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5).json()
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for msg in r.get("messages", []):
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Cleanup error: {e}")

def cleanup_non_jarvis():
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        r = requests.get(url, timeout=5).json()
        for msg in r.get("messages", []):
            if msg.get("appid") != jarvis_app_id:
                delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Non-jarvis cleanup error: {e}")

def run_scheduler():
    schedule.every(5).minutes.do(retention_cleanup)
    schedule.every(5).seconds.do(cleanup_non_jarvis)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# API helpers
# -----------------------------
def radarr_get(path):
    if not RADARR_ENABLED: return []
    try:
        url = f"{RADARR_URL.rstrip('/')}/api/v3/{path}?apikey={RADARR_API_KEY}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[{BOT_NAME}] Radarr error {path}: {e}")
        return []

def sonarr_get(path):
    if not SONARR_ENABLED: return []
    try:
        url = f"{SONARR_URL.rstrip('/')}/api/v3/{path}?apikey={SONARR_API_KEY}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[{BOT_NAME}] Sonarr error {path}: {e}")
        return []

# -----------------------------
# Insights
# -----------------------------
def movie_count():
    movies = radarr_get("movie")
    return len(movies)

def series_count():
    series = sonarr_get("series")
    return len(series)

def longest_movie():
    movies = radarr_get("movie")
    movies = [m for m in movies if m.get("runtime")]
    if not movies: return None
    return max(movies, key=lambda m: m["runtime"])

def shortest_movie():
    movies = radarr_get("movie")
    movies = [m for m in movies if m.get("runtime") and m["runtime"] > 0]
    if not movies: return None
    return min(movies, key=lambda m: m["runtime"])

def largest_movie():
    movies = radarr_get("movie")
    movies = [m for m in movies if m.get("movieFile", {}).get("size")]
    if not movies: return None
    return max(movies, key=lambda m: m["movieFile"]["size"])

def longest_series():
    series = sonarr_get("series")
    if not series: return None
    return max(series, key=lambda s: s.get("statistics", {}).get("episodeFileCount", 0))

def largest_series():
    series = sonarr_get("series")
    if not series: return None
    return max(series, key=lambda s: s.get("statistics", {}).get("sizeOnDisk", 0))

def upcoming_movies():
    today = datetime.date.today()
    end = today + datetime.timedelta(days=7)
    results = radarr_get(f"calendar?start={today}&end={end}")
    return results

def upcoming_series():
    today = datetime.date.today()
    end = today + datetime.timedelta(days=7)
    results = sonarr_get(f"calendar?start={today}&end={end}")
    return results

def get_weather():
    if not WEATHER_ENABLED: return None
    try:
        if WEATHER_API.lower() == "openweathermap" and WEATHER_API_KEY:
            url = f"http://api.openweathermap.org/data/2.5/weather?q={WEATHER_CITY}&appid={WEATHER_API_KEY}&units=metric"
            r = requests.get(url, timeout=10).json()
            return f"{r['main']['temp']}°C, {r['weather'][0]['description']}"
        else:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={WEATHER_LAT}&longitude={WEATHER_LON}&current_weather=true"
            r = requests.get(url, timeout=10).json()
            cw = r.get("current_weather", {})
            return f"{cw.get('temperature')}°C, {cw.get('weathercode', 'clear')}"
    except Exception as e:
        print(f"[{BOT_NAME}] Weather fetch failed: {e}")
        return None

# -----------------------------
# Beautify
# -----------------------------
def beautify_response(content, kind="info"):
    prefixes = {
        "info": ["💡", "📊", "🧠"],
        "error": ["⚠️", "💀", "❌"],
        "success": ["✅", "✨", "🚀"]
    }
    closings = [
        f"{BOT_ICON} Insight provided by {BOT_NAME}",
        f"🤖 Processed intelligently by {BOT_NAME}",
        f"🧠 Analysis complete — {BOT_NAME} signing off",
    ]
    prefix = random.choice(prefixes.get(kind, ["💡"]))
    closing = random.choice(closings)
    return f"{prefix} {content}\n\n{closing}"

# -----------------------------
# Command handler
# -----------------------------
def handle_command(text):
    t = text.lower()

    if "how many movies" in t or "movie count" in t:
        return beautify_response(f"You have {movie_count()} movies.", "success")
    if "how many series" in t or "series count" in t:
        return beautify_response(f"You have {series_count()} series.", "success")

    if "longest movie" in t:
        m = longest_movie()
        if m: return beautify_response(f"🎬 Longest movie: {m['title']} ({m['runtime']} mins)")
        return beautify_response("Couldn't fetch longest movie.", "error")

    if "shortest movie" in t:
        m = shortest_movie()
        if m: return beautify_response(f"🎬 Shortest movie: {m['title']} ({m['runtime']} mins)")
        return beautify_response("Couldn't fetch shortest movie.", "error")

    if "largest movie" in t:
        m = largest_movie()
        if m: return beautify_response(f"🎬 Largest movie: {m['title']} ({round(m['movieFile']['size']/1e9,2)} GB)")
        return beautify_response("Couldn't fetch largest movie.", "error")

    if "longest series" in t:
        s = longest_series()
        if s: return beautify_response(f"📺 Longest series: {s['title']} ({s['statistics']['episodeFileCount']} episodes)")
        return beautify_response("Couldn't fetch longest series.", "error")

    if "largest series" in t:
        s = largest_series()
        if s: return beautify_response(f"📺 Largest series: {s['title']} ({round(s['statistics']['sizeOnDisk']/1e9,2)} GB)")
        return beautify_response("Couldn't fetch largest series.", "error")

    if "upcoming movie" in t:
        movies = upcoming_movies()
        if movies:
            lines = [f"• {m['title']} ({m.get('inCinemas')})" for m in movies]
            return beautify_response("🎬 Upcoming movies:\n" + "\n".join(lines))
        return beautify_response("🎬 No upcoming movies this week.", "info")

    if "upcoming series" in t:
        shows = upcoming_series()
        if shows:
            lines = [f"• {s['series']['title']} - S{s['seasonNumber']}E{s['episodeNumber']} ({s['airDate']})" for s in shows]
            return beautify_response("📺 Upcoming episodes:\n" + "\n".join(lines))
        return beautify_response("📺 No upcoming series episodes this week.", "info")

    if "weather" in t:
        w = get_weather()
        if w: return beautify_response(f"🌦 Current weather in {WEATHER_CITY}: {w}")
        return beautify_response("Couldn't fetch weather.", "error")

    if "help" in t:
        return beautify_response("Commands: movie count, series count, longest/shortest/largest movie, longest/largest series, upcoming movies/series, weather.", "info")

    return beautify_response("I didn't understand. Try 'Jarvis help' for a list of commands.", "error")

# -----------------------------
# Main listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://")
    ws_url += f"/stream?token={CLIENT_TOKEN}"
    async with websockets.connect(ws_url, ping_interval=30) as ws:
        async for msg in ws:
            try:
                data = json.loads(msg)
                mid, appid, text = data.get("id"), data.get("appid"), data.get("message","")
                if appid == jarvis_app_id: continue
                if BOT_NAME.lower() in text.lower() or "jarvis" in text.lower():
                    response = handle_command(text)
                    send_message("Command Response", response)
                    delete_message(mid)
            except Exception as e:
                print(f"[{BOT_NAME}] Error processing: {e}")

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    resolve_app_id()
    send_message("Startup", random.choice([
        f"🚀 {BOT_NAME} systems online.",
        f"✨ Good day! {BOT_NAME} ready to assist.",
        f"🤖 {BOT_NAME} reporting for duty."
    ]))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
