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

# Radarr/Sonarr
RADARR_URL = os.getenv("radarr_url")
RADARR_KEY = os.getenv("radarr_api_key")
SONARR_URL = os.getenv("sonarr_url")
SONARR_KEY = os.getenv("sonarr_api_key")

# Weather
WEATHER_CITY = os.getenv("weather_city", "Johannesburg")
WEATHER_LAT = os.getenv("weather_lat", "")
WEATHER_LON = os.getenv("weather_lon", "")

# Options
RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")

jarvis_app_id = None

# -----------------------------
# In-memory caches
# -----------------------------
cache = {
    "movies": None,
    "series": None,
    "movies_expiry": 0,
    "series_expiry": 0,
}

# -----------------------------
# Gotify Helpers
# -----------------------------
def send_message(title, message, priority=5):
    if not GOTIFY_URL or not APP_TOKEN:
        print(f"[{BOT_NAME}] ❌ Missing GOTIFY_URL or APP_TOKEN, cannot send message.")
        return False
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent: {title}")
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to send message '{title}': {e}")
        return False

def delete_message(mid):
    try:
        url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
        requests.delete(url, timeout=5)
    except Exception as e:
        print("Delete error:", e)

# -----------------------------
# Purge Helpers
# -----------------------------
def purge_app_messages(appid, appname=""):
    if not appid: return False
    url = f"{GOTIFY_URL}/application/{appid}/message"
    headers = {"X-Gotify-Key": CLIENT_TOKEN}
    try:
        r = requests.delete(url, headers=headers, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging app {appid}: {e}")
        return False

def purge_non_jarvis_apps():
    global jarvis_app_id
    if not jarvis_app_id: return
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        apps = requests.get(url, headers=headers, timeout=5).json()
        for app in apps:
            if app.get("id") != jarvis_app_id:
                purge_app_messages(app.get("id"), app.get("name"))
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Error purging non-Jarvis apps: {e}")

def resolve_app_id():
    global jarvis_app_id
    try:
        url = f"{GOTIFY_URL}/application"
        headers = {"X-Gotify-Key": CLIENT_TOKEN}
        apps = requests.get(url, headers=headers, timeout=5).json()
        for app in apps:
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] ✅ MATCHED: '{APP_NAME}' -> id={jarvis_app_id}")
                return
        print(f"[{BOT_NAME}] ❌ WARNING: Could not find app '{APP_NAME}'")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed to resolve app id: {e}")

# -----------------------------
# Beautify
# -----------------------------
def beautify_message(title, raw):
    text = raw.strip()
    lower = text.lower()
    prefix = "💡"
    if "error" in lower or "failed" in lower: prefix = "💀"
    elif "success" in lower or "completed" in lower: prefix = "✅"
    elif "warning" in lower: prefix = "⚠️"
    elif "start" in lower or "starting" in lower: prefix = "🚀"
    closings = [
        f"{BOT_ICON} Yours truly, {BOT_NAME}",
        f"✨ Insight provided by {BOT_NAME}",
        f"🌍 Analysis complete — {BOT_NAME}",
        f"🤖 At your service, {BOT_NAME}",
    ]
    return f"{prefix} {text}\n\n{random.choice(closings)}"

# -----------------------------
# Cleanup
# -----------------------------
def cleanup_messages():
    try:
        url = f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}"
        msgs = requests.get(url, timeout=5).json().get("messages", [])
        cutoff = time.time() - (RETENTION_HOURS * 3600)
        for m in msgs:
            ts = datetime.datetime.fromisoformat(m["date"].replace("Z","+00:00")).timestamp()
            if ts < cutoff and m.get("id") and BOT_NAME not in m.get("title",""):
                delete_message(m["id"])
    except Exception as e:
        print("Cleanup error:", e)

# -----------------------------
# Radarr / Sonarr with caching
# -----------------------------
def get_upcoming_movies(days=7):
    try:
        now = time.time()
        if cache["movies"] and now < cache["movies_expiry"]:
            return cache["movies"]
        start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        end = (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        url = f"{RADARR_URL}/api/v3/calendar?start={start}&end={end}&apikey={RADARR_KEY}"
        data = requests.get(url, timeout=10).json()
        cache["movies"] = data
        cache["movies_expiry"] = now + 300  # cache 5 minutes
        return data
    except Exception as e:
        print("Radarr error:", e)
        return []

def get_upcoming_episodes(days=7):
    try:
        now = time.time()
        if cache["series"] and now < cache["series_expiry"]:
            return cache["series"]
        start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        end = (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        url = f"{SONARR_URL}/api/v3/calendar?start={start}&end={end}&apikey={SONARR_KEY}"
        data = requests.get(url, timeout=10).json()
        cache["series"] = data
        cache["series_expiry"] = now + 300
        return data
    except Exception as e:
        print("Sonarr error:", e)
        return []

def get_movie_count():
    try:
        url = f"{RADARR_URL}/api/v3/movie?apikey={RADARR_KEY}"
        return len(requests.get(url, timeout=10).json())
    except: return 0

def get_series_count():
    try:
        url = f"{SONARR_URL}/api/v3/series?apikey={SONARR_KEY}"
        return len(requests.get(url, timeout=10).json())
    except: return 0

def get_longest_movie():
    try:
        movies = requests.get(f"{RADARR_URL}/api/v3/movie?apikey={RADARR_KEY}", timeout=10).json()
        m = max(movies, key=lambda x: x.get("runtime",0))
        return f"🎬 Longest movie: {m.get('title')} ({m.get('runtime')} mins)"
    except: return "🎬 Could not fetch longest movie."

def get_longest_series():
    try:
        shows = requests.get(f"{SONARR_URL}/api/v3/series?apikey={SONARR_KEY}", timeout=10).json()
        s = max(shows, key=lambda x: x.get("episodeCount",0))
        return f"📺 Longest series: {s.get('title')} ({s.get('episodeCount')} episodes)"
    except: return "📺 Could not fetch longest series."

# -----------------------------
# Weather
# -----------------------------
def get_weather():
    try:
        if WEATHER_LAT and WEATHER_LON:
            url = f"https://wttr.in/{WEATHER_LAT},{WEATHER_LON}?format=j1"
        else:
            url = f"https://wttr.in/{WEATHER_CITY}?format=j1"
        data = requests.get(url, timeout=10).json()
        cur = data["current_condition"][0]
        return f"🌤 {WEATHER_CITY}: {cur['temp_C']}°C, wind {cur['windspeedKmph']} km/h"
    except: return "🌤 Weather unavailable right now."

# -----------------------------
# Command Handler
# -----------------------------
def handle_command(msg):
    q = msg.lower()
    if "weather" in q: return get_weather()
    if "movie count" in q: return f"🎬 You have {get_movie_count()} movies."
    if "series count" in q: return f"📺 You have {get_series_count()} series."
    if "longest movie" in q: return get_longest_movie()
    if "longest series" in q: return get_longest_series()
    if "upcoming movie" in q:
        um = get_upcoming_movies()
        if not um: return "🎬 No upcoming movies this week."
        return "🎬 Upcoming movies:\n" + "\n".join([f"{m.get('title','Unknown')} ({m.get('physicalRelease','N/A')})" for m in um[:5]])
    if "upcoming series" in q or "upcoming show" in q:
        us = get_upcoming_episodes()
        if not us: return "📺 No upcoming episodes this week."
        lines = [f"{e.get('series',{}).get('title','Unknown')} S{e.get('seasonNumber')}E{e.get('episodeNumber')} ({e.get('airDate','N/A')})" for e in us[:5]]
        return "📺 Upcoming episodes:\n" + "\n".join(lines)
    return None

# -----------------------------
# WebSocket Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://")+f"/stream?token={CLIENT_TOKEN}"
    print(f"[{BOT_NAME}] Connecting to {ws_url}...")
    try:
        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
            print(f"[{BOT_NAME}] ✅ Connected! Listening...")
            async for msg in ws:
                data = json.loads(msg)
                mid, appid, title, message = data.get("id"), data.get("appid"), data.get("title",""), data.get("message","")
                if not mid: continue
                if jarvis_app_id and appid == jarvis_app_id: continue
                resp = handle_command(message)
                if resp:
                    final_msg = beautify_message(title, resp) if BEAUTIFY_ENABLED else resp
                    prio = 0 if SILENT_REPOST else 5
                    if send_message("Response", final_msg, priority=prio):
                        delete_message(mid)
                        purge_non_jarvis_apps()
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ WebSocket error: {e}")
        await asyncio.sleep(10)
        await listen()

# -----------------------------
# Main
# -----------------------------
async def main():
    print(f"[{BOT_NAME}] Starting add-on...")
    resolve_app_id()
    startup_msg = random.choice([
        f"Good Day, I am {BOT_NAME}, ready to assist.",
        f"Greetings, {BOT_NAME} is now online and standing by.",
        f"🚀 {BOT_NAME} systems initialized and operational.",
        f"{BOT_NAME} reporting for duty.",
    ])
    send_message("Startup", beautify_message("Startup", startup_msg), priority=5)
    schedule.every(5).minutes.do(purge_non_jarvis_apps)
    schedule.every(5).seconds.do(cleanup_messages)
    asyncio.create_task(listen())
    while True:
        schedule.run_pending()
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
