import os, json, time, asyncio, requests, websockets, schedule, datetime, random

# -----------------------------
# Config from environment
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "12"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")

# Weather
WEATHER_API = os.getenv("WEATHER_API", "metno")
WEATHER_CITY = os.getenv("WEATHER_CITY", "Johannesburg")
WEATHER_LAT = os.getenv("WEATHER_LAT", "-26.2")
WEATHER_LON = os.getenv("WEATHER_LON", "28.0")

# Radarr
RADARR_ENABLED = os.getenv("RADARR_ENABLED", "false").lower() in ("1", "true", "yes")
RADARR_URL = os.getenv("RADARR_URL", "")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")

# Sonarr
SONARR_ENABLED = os.getenv("SONARR_ENABLED", "false").lower() in ("1", "true", "yes")
SONARR_URL = os.getenv("SONARR_URL", "")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")

jarvis_app_id = None

# -----------------------------
# Send Gotify message
# -----------------------------
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] Sent: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] Send error: {e}")
        return False

# -----------------------------
# Delete message
# -----------------------------
def delete_message(mid):
    try:
        url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
        r = requests.delete(url, timeout=5)
        return r.status_code == 200
    except:
        return False

# -----------------------------
# Cleanup
# -----------------------------
def cleanup_non_jarvis_messages():
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        msgs = requests.get(url, timeout=5).json().get("messages", [])
        for msg in msgs:
            if msg.get("appid") != jarvis_app_id:
                delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Cleanup error: {e}")

def retention_cleanup():
    cutoff = time.time() - (RETENTION_HOURS * 3600)
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        msgs = requests.get(url, timeout=5).json().get("messages", [])
        for msg in msgs:
            ts = datetime.datetime.fromisoformat(msg["date"].replace("Z","+00:00")).timestamp()
            if ts < cutoff: delete_message(msg["id"])
    except Exception as e:
        print(f"[{BOT_NAME}] Retention cleanup failed: {e}")

# -----------------------------
# Beautifier
# -----------------------------
def beautify_message(title, raw):
    prefix = "💡"
    if "error" in raw.lower(): prefix = "💀"
    elif "success" in raw.lower() or "completed" in raw.lower(): prefix = "✅"
    elif "warning" in raw.lower(): prefix = "⚠️"
    elif "start" in raw.lower(): prefix = "🚀"
    closings = [
        f"{BOT_ICON} Yours truly, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"📊 Analysis complete — {BOT_NAME} signing off",
        f"🌐 Insight provided by {BOT_NAME}"
    ]
    return f"{prefix} {raw}\n\n{random.choice(closings)}"

# -----------------------------
# Radarr & Sonarr helpers
# -----------------------------
def get_radarr_movies():
    if not RADARR_ENABLED: return []
    try:
        r = requests.get(f"{RADARR_URL}/api/v3/movie", headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
        return r.json()
    except: return []

def get_sonarr_series():
    if not SONARR_ENABLED: return []
    try:
        r = requests.get(f"{SONARR_URL}/api/v3/series", headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
        return r.json()
    except: return []

def get_upcoming_movies(days=7):
    if not RADARR_ENABLED: return []
    start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    end = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        r = requests.get(f"{RADARR_URL}/api/v3/calendar?start={start}&end={end}",
                         headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
        return r.json()
    except: return []

def get_upcoming_episodes(days=7):
    if not SONARR_ENABLED: return []
    start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    end = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        r = requests.get(f"{SONARR_URL}/api/v3/calendar?start={start}&end={end}",
                         headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
        return r.json()
    except: return []

# -----------------------------
# Weather (MET.no)
# -----------------------------
def get_weather():
    try:
        r = requests.get(f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={WEATHER_LAT}&lon={WEATHER_LON}",
                         headers={"User-Agent": "JarvisBot/1.0"}, timeout=10)
        data = r.json()["properties"]["timeseries"][0]
        temp = data["data"]["instant"]["details"]["air_temperature"]
        wind = data["data"]["instant"]["details"]["wind_speed"]
        return f"🌤 Current weather: {temp}°C, wind {wind} km/h"
    except Exception as e:
        return f"❌ Weather fetch failed: {e}"

# -----------------------------
# Command Handler
# -----------------------------
def handle_command(text):
    q = text.lower()

    # Weather
    if "weather" in q: return get_weather()

    # Movies
    if "movie count" in q: return f"🎬 You have {len(get_radarr_movies())} movies."
    if "longest movie" in q:
        m = max(get_radarr_movies(), key=lambda x:x.get("runtime",0), default=None)
        return f"🎬 Longest movie: {m['title']} ({m.get('runtime',0)} mins)" if m else "No movies."
    if "upcoming movie" in q: 
        items = get_upcoming_movies()
        if not items: return "🎬 No upcoming movies this week."
        return "🎬 Upcoming movies:\n" + "\n".join([f"• {m['title']} ({m['inCinemas'][:10]})" for m in items[:5]])

    # Series
    if "series count" in q: return f"📺 You have {len(get_sonarr_series())} series."
    if "longest series" in q or "largest series" in q:
        s = max(get_sonarr_series(), key=lambda x:x.get("episodeCount",0), default=None)
        return f"📺 Longest series: {s['title']} ({s.get('episodeCount',0)} episodes)" if s else "No series."
    if "upcoming series" in q or "upcoming show" in q:
        eps = get_upcoming_episodes()
        if not eps: return "📺 No upcoming episodes."
        return "📺 Upcoming episodes:\n" + "\n".join([
            f"• {e['series']['title']} - S{e.get('seasonNumber')}E{e.get('episodeNumber')} ({e.get('airDateUtc','?')[:10]})"
            for e in eps[:5] if e.get("series")
        ])

    return f"🤖 I didn’t understand. Try '{BOT_NAME} help' for commands."

# -----------------------------
# WebSocket Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        async for raw in ws:
            try:
                data = json.loads(raw)
                mid, appid, title, msg = data.get("id"), data.get("appid"), data.get("title",""), data.get("message","")

                if appid == jarvis_app_id: continue
                if not mid: continue

                response = handle_command(msg)
                final = beautify_message("Response", response) if BEAUTIFY_ENABLED else response
                send_message("Response", final, priority=5)
                delete_message(mid)

            except Exception as e:
                print(f"[{BOT_NAME}] Error: {e}")

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(5).seconds.do(cleanup_non_jarvis_messages)
    schedule.every(12).hours.do(retention_cleanup)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] Starting add-on...")
    startup_msg = random.choice([
        f"🚀 {BOT_NAME} systems online.",
        f"🤖 {BOT_NAME} reporting for duty.",
        f"✨ {BOT_NAME} initialized and ready."
    ])
    send_message("Startup", startup_msg, priority=5)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
