import os, requests, datetime

# -----------------------------
# Config from environment
# -----------------------------
RADARR_URL = os.getenv("RADARR_URL", "").rstrip("/")
RADARR_KEY = os.getenv("RADARR_API_KEY", "")
SONARR_URL = os.getenv("SONARR_URL", "").rstrip("/")
SONARR_KEY = os.getenv("SONARR_API_KEY", "")

RADARR_ENABLED = bool(RADARR_URL and RADARR_KEY)
SONARR_ENABLED = bool(SONARR_URL and SONARR_KEY)

# -----------------------------
# Helpers
# -----------------------------
def radarr_request(path):
    try:
        url = f"{RADARR_URL}/api/v3/{path}?apikey={RADARR_KEY}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def sonarr_request(path):
    try:
        url = f"{SONARR_URL}/api/v3/{path}?apikey={SONARR_KEY}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def cache_radarr():
    if not RADARR_ENABLED: return
    radarr_request("movie")  # warms cache

def cache_sonarr():
    if not SONARR_ENABLED: return
    sonarr_request("series")  # warms cache

# -----------------------------
# Commands
# -----------------------------
def get_movie_count():
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None
    data = radarr_request("movie")
    if "error" in data: return f"❌ Radarr error: {data['error']}", None
    return f"🎬 Radarr has {len(data)} movies in library", None

def get_series_count():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    data = sonarr_request("series")
    if "error" in data: return f"❌ Sonarr error: {data['error']}", None
    return f"📺 Sonarr has {len(data)} series in library", None

def get_upcoming_movies():
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None
    data = radarr_request("calendar")
    if "error" in data: return f"❌ Radarr error: {data['error']}", None
    upcoming = [f"{m.get('title')} ({m.get('year')})" for m in data]
    if not upcoming: return "🎬 No upcoming Radarr movies", None
    return "🎬 Upcoming Movies:\n- " + "\n- ".join(upcoming[:10]), None

def get_upcoming_shows():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    data = sonarr_request("calendar")
    if "error" in data: return f"❌ Sonarr error: {data['error']}", None
    upcoming = [f"{e.get('series', {}).get('title')} S{e.get('seasonNumber')}E{e.get('episodeNumber')}" for e in data]
    if not upcoming: return "📺 No upcoming Sonarr episodes", None
    return "📺 Upcoming Episodes:\n- " + "\n- ".join(upcoming[:10]), None

# -----------------------------
# Command Router
# -----------------------------
def handle_arr_command(message, title=""):
    msg = (title + " " + message).lower()

    if "how many movies" in msg:
        return get_movie_count()
    if "how many shows" in msg or "how many series" in msg:
        return get_series_count()
    if "upcoming movies" in msg:
        return get_upcoming_movies()
    if "upcoming shows" in msg or "upcoming series" in msg:
        return get_upcoming_shows()

    return None, None
