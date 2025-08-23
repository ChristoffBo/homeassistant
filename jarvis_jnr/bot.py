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
APP_NAME = os.getenv("JARVIS_APP_NAME", "Jarvis")

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "24"))
SILENT_REPOST = os.getenv("SILENT_REPOST", "true").lower() in ("1", "true", "yes")
BEAUTIFY_ENABLED = os.getenv("BEAUTIFY_ENABLED", "true").lower() in ("1", "true", "yes")

WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "false").lower() in ("1", "true", "yes")
WEATHER_API = os.getenv("WEATHER_API", "openweathermap")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
WEATHER_CITY = os.getenv("WEATHER_CITY", "Johannesburg")
WEATHER_TIME = os.getenv("WEATHER_TIME", "07:00")

DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "false").lower() in ("1", "true", "yes")
DIGEST_TIME = os.getenv("DIGEST_TIME", "08:00")

RADARR_ENABLED = os.getenv("RADARR_ENABLED", "false").lower() in ("1", "true", "yes")
RADARR_URL = os.getenv("RADARR_URL", "")
RADARR_API_KEY = os.getenv("RADARR_API_KEY", "")
RADARR_TIME = os.getenv("RADARR_TIME", "07:30")

SONARR_ENABLED = os.getenv("SONARR_ENABLED", "false").lower() in ("1", "true", "yes")
SONARR_URL = os.getenv("SONARR_URL", "")
SONARR_API_KEY = os.getenv("SONARR_API_KEY", "")
SONARR_TIME = os.getenv("SONARR_TIME", "07:30")

jarvis_app_id = None

# -----------------------------
# Helpers
# -----------------------------
def send_message(title, message, priority=5):
    url = f"{GOTIFY_URL}/message?token={APP_TOKEN}"
    try:
        r = requests.post(url, json={"title": f"{BOT_ICON} {BOT_NAME}: {title}", "message": message, "priority": priority}, timeout=5)
        r.raise_for_status()
        print(f"[{BOT_NAME}] ✅ Sent: {title}")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Failed send: {e}")

def purge_non_jarvis_apps():
    global jarvis_app_id
    try:
        r = requests.get(f"{GOTIFY_URL}/application", headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=5)
        r.raise_for_status()
        for app in r.json():
            if app.get("id") != jarvis_app_id:
                requests.delete(f"{GOTIFY_URL}/application/{app['id']}/message", headers={"X-Gotify-Key": CLIENT_TOKEN}, timeout=5)
                print(f"[{BOT_NAME}] 🗑 Purged {app['name']} (id={app['id']})")
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Purge error: {e}")

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

def beautify_message(title, raw):
    prefix = "💡"
    lower = raw.lower()
    if "error" in lower: prefix = "💀"
    elif "success" in lower: prefix = "✅"
    elif "warning" in lower: prefix = "⚠️"
    elif "start" in lower: prefix = "🚀"
    closings = [
        f"{BOT_ICON} With regards, {BOT_NAME}",
        f"✨ Processed intelligently by {BOT_NAME}",
        f"🧩 Ever at your service, {BOT_NAME}"
    ]
    return f"{prefix} {raw.strip()}\n\n{random.choice(closings)}"

# -----------------------------
# Modules
# -----------------------------
def fetch_weather():
    if not WEATHER_ENABLED or not WEATHER_API_KEY: return None
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={WEATHER_CITY}&appid={WEATHER_API_KEY}&units=metric"
        r = requests.get(url, timeout=5).json()
        return f"🌤 {WEATHER_CITY}: {r['main']['temp']}°C, {r['weather'][0]['description']}"
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Weather error: {e}")
        return None

def fetch_radarr_upcoming(days=7):
    if not RADARR_ENABLED or not RADARR_API_KEY: return None
    try:
        start = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        url = f"{RADARR_URL}/api/v3/calendar?start={start}&end={end}"
        r = requests.get(url, headers={"X-Api-Key": RADARR_API_KEY}, timeout=5).json()
        if not r: return "🎬 No upcoming movies"
        items = [f"{m['title']} ({m['inCinemas'][:10] if m.get('inCinemas') else 'TBA'})" for m in r]
        return "🎬 Upcoming Movies:\n" + "\n".join(items[:5])
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Radarr upcoming error: {e}")
        return None

def fetch_sonarr_upcoming(days=7):
    if not SONARR_ENABLED or not SONARR_API_KEY: return None
    try:
        start = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        url = f"{SONARR_URL}/api/v3/calendar?start={start}&end={end}"
        r = requests.get(url, headers={"X-Api-Key": SONARR_API_KEY}, timeout=5).json()
        if not r: return "📺 No upcoming episodes"
        items = [f"{e['series']['title']} - S{e['seasonNumber']}E{e['episodeNumber']} ({e['airDate']})" for e in r]
        return "📺 Upcoming Episodes:\n" + "\n".join(items[:5])
    except Exception as e:
        print(f"[{BOT_NAME}] ❌ Sonarr upcoming error: {e}")
        return None

def send_digest():
    if not DIGEST_ENABLED: return
    parts = []
    if WEATHER_ENABLED: w = fetch_weather();  parts.append(w) if w else None
    if RADARR_ENABLED:  r = fetch_radarr_upcoming(7); parts.append(r) if r else None
    if SONARR_ENABLED:  s = fetch_sonarr_upcoming(7); parts.append(s) if s else None
    if not parts: return
    digest_msg = "🗞 Daily Digest\n\n" + "\n".join(parts)
    send_message("Daily Digest", beautify_message("Digest", digest_msg))

# -----------------------------
# Command Parser
# -----------------------------
def parse_command(raw):
    text = raw.strip().lower()
    if not text.startswith("jarvis"):
        return None

    if "help" in text: return "help"
    if "media" in text: return "media"
    if "radarr" in text or "movie" in text or "movies" in text: return "radarr_upcoming"
    if "sonarr" in text or "show" in text or "shows" in text or "series" in text: return "sonarr_upcoming"
    if "weather" in text: return "weather"
    if "digest" in text or "summary" in text: return "digest"
    return None

def handle_command(command):
    if command == "radarr_upcoming": return fetch_radarr_upcoming(7)
    if command == "sonarr_upcoming": return fetch_sonarr_upcoming(7)
    if command == "media": return f"{fetch_radarr_upcoming(7)}\n\n{fetch_sonarr_upcoming(7)}"
    if command == "weather": return fetch_weather()
    if command == "digest": 
        send_digest()
        return "🗞 Digest sent"
    if command == "help":
        return (
            "🤖 Jarvis Command Help:\n\n"
            "• Jarvis weather → Get current weather\n"
            "• Jarvis digest → Get full daily digest now\n"
            "• Jarvis radarr / Jarvis movies → Upcoming Radarr movies\n"
            "• Jarvis sonarr / Jarvis shows / Jarvis series → Upcoming Sonarr episodes\n"
            "• Jarvis media → Combined Radarr + Sonarr upcoming"
        )
    return "🤖 I didn’t understand that."

# -----------------------------
# Scheduler
# -----------------------------
def run_scheduler():
    schedule.every(5).minutes.do(purge_non_jarvis_apps)
    if WEATHER_ENABLED: schedule.every().day.at(WEATHER_TIME).do(lambda: send_message("Weather Update", beautify_message("Weather", fetch_weather())))
    if RADARR_ENABLED: schedule.every().day.at(RADARR_TIME).do(lambda: send_message("Radarr Update", beautify_message("Radarr", fetch_radarr_upcoming())))
    if SONARR_ENABLED: schedule.every().day.at(SONARR_TIME).do(lambda: send_message("Sonarr Update", beautify_message("Sonarr", fetch_sonarr_upcoming())))
    if DIGEST_ENABLED: schedule.every().day.at(DIGEST_TIME).do(send_digest)
    while True:
        schedule.run_pending()
        time.sleep(1)

# -----------------------------
# Listener
# -----------------------------
async def listen():
    ws_url = GOTIFY_URL.replace("http://","ws://").replace("https://","wss://") + f"/stream?token={CLIENT_TOKEN}"
    async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
        async for msg in ws:
            data = json.loads(msg)
            mid, appid = data.get("id"), data.get("appid")
            title, message = data.get("title",""), data.get("message","")

            if appid == jarvis_app_id: continue  # skip own

            command = parse_command(message)
            if command:
                reply = handle_command(command)
                if reply: send_message("Jarvis Command", beautify_message("Jarvis", reply))
                requests.delete(f"{GOTIFY_URL}/message/{mid}", headers={"X-Gotify-Key": CLIENT_TOKEN})
                continue

            # Normal beautify flow
            if BEAUTIFY_ENABLED: message = beautify_message(title, message)
            send_message(title, message, priority=(0 if SILENT_REPOST else 5))
            purge_non_jarvis_apps()

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    print(f"[{BOT_NAME}] 🚀 Starting...")
    resolve_app_id()
    send_message("Startup", f"{BOT_NAME} online and ready.", priority=5)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(listen())
    loop.run_in_executor(None, run_scheduler)
    loop.run_forever()
