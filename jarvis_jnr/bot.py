import os, json, time, asyncio, requests, websockets, schedule, datetime, random

# -----------------------------
# Config
# -----------------------------
BOT_NAME = os.getenv("BOT_NAME", "Jarvis")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1","true","yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1","true","yes")

RADARR_ENABLED = os.getenv("RADARR_ENABLED", "false").lower() in ("1","true","yes")
RADARR_URL = os.getenv("RADARR_URL", "")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")

SONARR_ENABLED = os.getenv("SONARR_ENABLED", "false").lower() in ("1","true","yes")
SONARR_URL = os.getenv("SONARR_URL", "")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")

WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "false").lower() in ("1","true","yes")
WEATHER_LAT = os.getenv("WEATHER_LAT", "-26.2041")
WEATHER_LON = os.getenv("WEATHER_LON", "28.0473")

jarvis_app_id = None
CACHE = {"radarr":{}, "sonarr":{}}

# -----------------------------
# Gotify helpers
# -----------------------------
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] Send failed: {e}")
        return False

def delete_message(mid):
    if not mid: return
    try:
        url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
        requests.delete(url, timeout=5)
    except Exception as e:
        print(f"[{BOT_NAME}] Delete error: {e}")

def resolve_app_id():
    global jarvis_app_id
    try:
        r = requests.get(f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}", timeout=5)
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
                print(f"[{BOT_NAME}] Resolved {APP_NAME} → {jarvis_app_id}")
    except Exception as e:
        print(f"[{BOT_NAME}] Could not resolve app id: {e}")

# -----------------------------
# Beautify
# -----------------------------
def beautify_response(content, kind="info"):
    prefixes = {
        "info": ["💡","📊","🧠","🌐"],
        "error": ["⚠️","💀","❌"],
        "success": ["✅","✨","🚀"]
    }
    closings = [
        f"{BOT_ICON} Insight provided by {BOT_NAME}",
        f"🤖 Processed intelligently by {BOT_NAME}",
        f"🧠 Analysis complete — {BOT_NAME} signing off",
        f"📊 Report crafted by {BOT_NAME}",
    ]
    prefix = random.choice(prefixes.get(kind,["💡"]))
    closing = random.choice(closings)
    return f"{prefix} {content}\n\n{closing}"

# -----------------------------
# Radarr/Sonarr API helpers (with cache)
# -----------------------------
def radarr_get(path):
    if not RADARR_ENABLED: return []
    now = time.time()
    if path in CACHE["radarr"] and now-CACHE["radarr"][path]["time"] < 60:
        return CACHE["radarr"][path]["data"]
    try:
        url = f"{RADARR_URL.rstrip('/')}/api/v3/{path}?apikey={RADARR_API_KEY}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        CACHE["radarr"][path] = {"data":r.json(), "time":now}
        return r.json()
    except: return []

def sonarr_get(path):
    if not SONARR_ENABLED: return []
    now = time.time()
    if path in CACHE["sonarr"] and now-CACHE["sonarr"][path]["time"] < 60:
        return CACHE["sonarr"][path]["data"]
    try:
        url = f"{SONARR_URL.rstrip('/')}/api/v3/{path}?apikey={SONARR_API_KEY}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        CACHE["sonarr"][path] = {"data":r.json(), "time":now}
        return r.json()
    except: return []

# -----------------------------
# Media Insights
# -----------------------------
def movie_count(): return len(radarr_get("movie"))
def series_count(): return len(sonarr_get("series"))

def longest_movie():
    movies = [m for m in radarr_get("movie") if m.get("runtime")]
    return max(movies, key=lambda m:m["runtime"], default=None)

def shortest_movie():
    movies = [m for m in radarr_get("movie") if m.get("runtime",0)>0]
    return min(movies, key=lambda m:m["runtime"], default=None)

def largest_movie():
    movies = [m for m in radarr_get("movie") if m.get("movieFile",{}).get("size")]
    return max(movies, key=lambda m:m["movieFile"]["size"], default=None)

def longest_series():
    series = sonarr_get("series")
    return max(series, key=lambda s:s.get("statistics",{}).get("episodeFileCount",0), default=None)

def largest_series():
    series = sonarr_get("series")
    return max(series, key=lambda s:s.get("statistics",{}).get("sizeOnDisk",0), default=None)

def upcoming_movies():
    today = datetime.date.today()
    end = today+datetime.timedelta(days=7)
    return radarr_get(f"calendar?start={today}&end={end}")

def upcoming_series():
    today = datetime.date.today()
    end = today+datetime.timedelta(days=7)
    return sonarr_get(f"calendar?start={today}&end={end}")

# -----------------------------
# Weather (Open-Meteo only)
# -----------------------------
def get_weather():
    if not WEATHER_ENABLED: return None
    try:
        url=f"https://api.open-meteo.com/v1/forecast?latitude={WEATHER_LAT}&longitude={WEATHER_LON}&current_weather=true"
        w=requests.get(url,timeout=10).json()
        cw=w.get("current_weather",{})
        return f"{cw.get('temperature')}°C, wind {cw.get('windspeed')} km/h"
    except: return None

# -----------------------------
# Cleanup
# -----------------------------
def retention_cleanup():
    """Remove Jarvis's own messages older than 12 hours"""
    try:
        msgs=requests.get(f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}",timeout=5).json().get("messages",[])
        cutoff=time.time()-(12*3600)
        for msg in msgs:
            ts=datetime.datetime.fromisoformat(msg["date"].replace("Z","+00:00")).timestamp()
            if msg.get("appid")==jarvis_app_id and ts<cutoff:
                delete_message(msg["id"])
    except Exception as e: print(f"[{BOT_NAME}] Retention cleanup error {e}")

def cleanup_non_jarvis():
    """Remove all non-Jarvis messages every 5s"""
    try:
        msgs=requests.get(f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}",timeout=5).json().get("messages",[])
        for msg in msgs:
            if msg.get("appid")!=jarvis_app_id:
                delete_message(msg["id"])
    except: pass

def run_scheduler():
    schedule.every(5).minutes.do(retention_cleanup)
    schedule.every(5).seconds.do(cleanup_non_jarvis)
    while True:
        schedule.run_pending(); time.sleep(1)

# -----------------------------
# Command Handler
# -----------------------------
def handle_command(text):
    t=text.lower()
    if "movie" in t and "count" in t: return beautify_response(f"You have {movie_count()} movies.", "success")
    if "series" in t and "count" in t: return beautify_response(f"You have {series_count()} series.", "success")

    if "longest movie" in t:
        m=longest_movie(); return beautify_response(f"🎬 Longest movie: {m['title']} ({m['runtime']} mins)") if m else beautify_response("No longest movie found.","error")
    if "shortest movie" in t:
        m=shortest_movie(); return beautify_response(f"🎬 Shortest movie: {m['title']} ({m['runtime']} mins)") if m else beautify_response("No shortest movie found.","error")
    if "largest movie" in t:
        m=largest_movie(); return beautify_response(f"🎬 Largest movie: {m['title']} ({round(m['movieFile']['size']/1e9,2)} GB)") if m else beautify_response("No largest movie found.","error")

    if "longest series" in t:
        s=longest_series(); return beautify_response(f"📺 Longest series: {s['title']} ({s['statistics']['episodeFileCount']} episodes)") if s else beautify_response("No longest series.","error")
    if "largest series" in t:
        s=largest_series(); return beautify_response(f"📺 Largest series: {s['title']} ({round(s['statistics']['sizeOnDisk']/1e9,2)} GB)") if s else beautify_response("No largest series.","error")

    if "upcoming movie" in t:
        movies=upcoming_movies()
        if movies: return beautify_response("🎬 Upcoming movies:\n"+"\n".join([f"• {m['title']} ({m.get('inCinemas')})" for m in movies]))
        return beautify_response("🎬 No upcoming movies.","info")

    if "upcoming series" in t:
        shows=upcoming_series()
        if shows: return beautify_response("📺 Upcoming episodes:\n"+"\n".join([f"• {s['series']['title']} - S{s['seasonNumber']}E{s['episodeNumber']} ({s['airDate']})" for s in shows]))
        return beautify_response("📺 No upcoming series.","info")

    if "weather" in t:
        w=get_weather(); return beautify_response(f"🌦 Current weather: {w}") if w else beautify_response("Couldn't fetch weather.","error")

    if "help" in t:
        return beautify_response("Commands: movie count, series count, longest/shortest/largest movie, longest/largest series, upcoming movies/series, weather.","info")

    return beautify_response("I didn’t understand. Try 'Jarvis help'.","error")

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://")+f"/stream?token={CLIENT_TOKEN}"
    async with websockets.connect(ws_url,ping_interval=30,ping_timeout=10) as ws:
        async for msg in ws:
            try:
                data=json.loads(msg)
                mid=data.get("id"); appid=data.get("appid"); text=f"{data.get('title','')} {data.get('message','')}"
                if jarvis_app_id and appid==jarvis_app_id: continue
                if BOT_NAME.lower() in text.lower() or "jarvis" in text.lower():
                    response=handle_command(text)
                    send_message("Command Response",response,priority=0 if SILENT_REPOST else 5)
                    delete_message(mid)
            except Exception as e: print(f"[{BOT_NAME}] Error: {e}")

# -----------------------------
# Entrypoint
# -----------------------------
if __name__=="__main__":
    resolve_app_id()
    startup=random.choice([f"🚀 {BOT_NAME} systems online.",f"✨ {BOT_NAME} ready to assist.",f"🤖 {BOT_NAME} reporting for duty."])
    send_message("Startup",startup,priority=5)
    loop=asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    loop.create_task(listen()); loop.run_in_executor(None,run_scheduler)
    loop.run_forever()
