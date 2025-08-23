import os, json, time, asyncio, requests, websockets, schedule, datetime, random

BOT_NAME = os.getenv("BOT_NAME", "Jarvis")
BOT_ICON = os.getenv("BOT_ICON", "🤖")
GOTIFY_URL = os.getenv("GOTIFY_URL")
CLIENT_TOKEN = os.getenv("GOTIFY_CLIENT_TOKEN")
APP_TOKEN = os.getenv("GOTIFY_APP_TOKEN")
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "12"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")

RADARR_URL = os.getenv("RADARR_URL", "").rstrip("/")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")
SONARR_URL = os.getenv("SONARR_URL", "").rstrip("/")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")

WEATHER_CITY = os.getenv("WEATHER_CITY", "Johannesburg")

jarvis_app_id = None
radarr_cache = {}
sonarr_cache = {}

# -----------------------------
# Gotify Messaging
# -----------------------------
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    data = {"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}
    try:
        r = requests.post(url, json=data, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[{BOT_NAME}] Send error: {e}")
        return False

def delete_message(mid):
    if not mid: return False
    try:
        url = f"{GOTIFY_URL}/message/{mid}?token={CLIENT_TOKEN}"
        r = requests.delete(url, timeout=5)
        return r.status_code == 200
    except: return False

def resolve_app_id():
    global jarvis_app_id
    try:
        r = requests.get(f"{GOTIFY_URL}/application?token={CLIENT_TOKEN}", timeout=5)
        r.raise_for_status()
        for app in r.json():
            if app.get("name") == APP_NAME:
                jarvis_app_id = app.get("id")
    except: pass

# -----------------------------
# Beautify
# -----------------------------
def beautify_message(title, raw):
    text = raw.strip()
    lower = text.lower()
    prefix = "✨"
    if "error" in lower or "failed" in lower: prefix = "💀"
    elif "success" in lower or "completed" in lower: prefix = "✅"
    elif "warning" in lower: prefix = "⚠️"
    elif "start" in lower: prefix = "🚀"

    closings = [
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🧠 Insight provided by {BOT_NAME}",
        f"📊 Analysis complete — {BOT_NAME} signing off",
        f"🤖 Yours truly, {BOT_NAME}"
    ]
    closing = random.choice(closings)
    return f"{prefix} {text}\n\n{closing}"

# -----------------------------
# Weather (wttr.in)
# -----------------------------
def get_weather():
    try:
        url = f"https://wttr.in/{WEATHER_CITY}?format=j1"
        r = requests.get(url, timeout=10)
        data = r.json()
        current = data["current_condition"][0]
        temp = current["temp_C"]
        wind = current["windspeedKmph"]
        return f"🌤 Current weather: {temp}°C, wind {wind} km/h"
    except Exception as e:
        return f"⚠️ Weather unavailable: {e}"

# -----------------------------
# Radarr / Sonarr API
# -----------------------------
def upcoming_movies(days=7):
    try:
        start = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        end = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        url = f"{RADARR_URL}/api/v3/calendar?start={start}&end={end}"
        headers = {"X-Api-Key": RADARR_API_KEY}
        r = requests.get(url, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        return []

def upcoming_series(days=7):
    try:
        start = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        end = (datetime.datetime.utcnow() + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        url = f"{SONARR_URL}/api/v3/calendar?start={start}&end={end}"
        headers = {"X-Api-Key": SONARR_API_KEY}
        r = requests.get(url, headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        return []

# -----------------------------
# Cleanup
# -----------------------------
def cleanup_non_jarvis():
    try:
        r = requests.get(f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}", timeout=5)
        msgs = r.json().get("messages", [])
        for msg in msgs:
            if msg["appid"] != jarvis_app_id:
                delete_message(msg["id"])
    except: pass

def cleanup_old_jarvis():
    cutoff = time.time() - (12 * 3600)
    try:
        r = requests.get(f"{GOTIFY_URL}/message?token={CLIENT_TOKEN}", timeout=5)
        msgs = r.json().get("messages", [])
        for msg in msgs:
            if msg["appid"] == jarvis_app_id:
                ts = datetime.datetime.fromisoformat(msg["date"].replace("Z", "+00:00")).timestamp()
                if ts < cutoff:
                    delete_message(msg["id"])
    except: pass

def run_scheduler():
    schedule.every(5).seconds.do(cleanup_non_jarvis)
    schedule.every(30).minutes.do(cleanup_old_jarvis)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Command handler
# -----------------------------
def handle_command(cmd):
    lower = cmd.lower()

    # Weather
    if any(word in lower for word in ["weather", "forecast", "temperature"]):
        return get_weather()

    # Upcoming
    if "upcoming" in lower and "movie" in lower:
        movies = upcoming_movies()
        if not movies: return "🎬 No upcoming movies this week."
        return "🎬 Upcoming movies:\n" + "\n".join([f"- {m['title']} ({m['inCinemas'][:10]})" for m in movies[:5]])

    if any(word in lower for word in ["upcoming series", "upcoming show", "series upcoming", "show upcoming"]):
        eps = upcoming_series()
        if not eps: return "📺 No upcoming episodes this week."
        return "📺 Upcoming episodes:\n" + "\n".join([f"- {e['series']['title']} - S{e['seasonNumber']}E{e['episodeNumber']} ({e['airDate']})" for e in eps[:5]])

    # Help
    if "help" in lower:
        return (
            "🤖 Available commands:\n"
            "- Jarvis weather / forecast\n"
            "- Jarvis upcoming movies\n"
            "- Jarvis upcoming series\n"
            "- Jarvis movie count / series count\n"
            "- Jarvis longest movie / longest series\n"
        )

    return f"🤖 I didn’t understand. Try 'Jarvis help' for commands."

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url += f"/stream?token={CLIENT_TOKEN}"
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        async for msg in ws:
            try:
                data = json.loads(msg)
                mid = data.get("id")
                appid = data.get("appid")
                title = data.get("title", "")
                message = data.get("message", "")

                if jarvis_app_id and appid == jarvis_app_id: continue

                if BOT_NAME.lower() in title.lower() or BOT_NAME.lower() in message.lower():
                    response = handle_command(message)
                    send_message("Command Response", beautify_message(title, response))
                    delete_message(mid)
                else:
                    if BEAUTIFY_ENABLED:
                        beautified = beautify_message(title, message)
                        if send_message(title, beautified, priority=(0 if SILENT_REPOST else 5)):
                            delete_message(mid)
            except: pass

# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    resolve_app_id()
    send_message("Startup", random.choice([
        f"🚀 {BOT_NAME} systems online.",
        f"✨ Good day! {BOT_NAME} ready to assist.",
        f"🤖 {BOT_NAME} initialized and standing by."
    ]))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
