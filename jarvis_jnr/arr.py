import os, requests, datetime, re, schedule, time, threading
from tabulate import tabulate

# -----------------------------
# Config from environment
# -----------------------------
RADARR_URL = os.getenv("RADARR_URL")
RADARR_APIKEY = os.getenv("RADARR_APIKEY")
SONARR_URL = os.getenv("SONARR_URL")
SONARR_APIKEY = os.getenv("SONARR_APIKEY")

RADARR_ENABLED = bool(RADARR_URL and RADARR_APIKEY)
SONARR_ENABLED = bool(SONARR_URL and SONARR_APIKEY)

# -----------------------------
# Cache
# -----------------------------
radarr_cache = {"movies": []}
sonarr_cache = {"series": []}

# -----------------------------
# API Helpers
# -----------------------------
def api_get(url, apikey):
    try:
        r = requests.get(url, headers={"X-Api-Key": apikey}, timeout=10)
        if r.ok:
            return r.json()
        else:
            print(f"[arr] ❌ API request failed {url} {r.status_code}")
            return None
    except Exception as e:
        print(f"[arr] ❌ Exception in api_get: {e}")
        return None

# -----------------------------
# Cache functions
# -----------------------------
def cache_radarr():
    global radarr_cache
    if not RADARR_ENABLED:
        return
    try:
        radarr_cache["movies"] = api_get(f"{RADARR_URL}/api/v3/movie", RADARR_APIKEY) or []
        print(f"[arr] ✅ Cached {len(radarr_cache['movies'])} Radarr movies")
    except Exception as e:
        print(f"[arr] ❌ Failed to cache Radarr: {e}")

def cache_sonarr():
    global sonarr_cache
    if not SONARR_ENABLED:
        return
    try:
        sonarr_cache["series"] = api_get(f"{SONARR_URL}/api/v3/series", SONARR_APIKEY) or []
        print(f"[arr] ✅ Cached {len(sonarr_cache['series'])} Sonarr series")
    except Exception as e:
        print(f"[arr] ❌ Failed to cache Sonarr: {e}")

# -----------------------------
# Command Handlers
# -----------------------------
def upcoming_movies():
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None
    url = f"{RADARR_URL}/api/v3/calendar?start={datetime.date.today()}&end={(datetime.date.today() + datetime.timedelta(days=7))}"
    items = api_get(url, RADARR_APIKEY) or []
    if not items:
        return "🎬 No upcoming movies in the next 7 days", None
    table = tabulate(
        [[m.get("title"), m.get("inCinemas",""), m.get("physicalRelease","")] for m in items],
        headers=["Title","In Cinemas","Physical Release"],
        tablefmt="github"
    )
    return f"🎬 UPCOMING MOVIES (7 days)\n╾━━━━━━━━━━━━━━━━╼\n{table}", None

def upcoming_series():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    url = f"{SONARR_URL}/api/v3/calendar?start={datetime.date.today()}&end={(datetime.date.today() + datetime.timedelta(days=7))}"
    items = api_get(url, SONARR_APIKEY) or []
    if not items:
        return "📺 No upcoming episodes in the next 7 days", None
    table = tabulate(
        [[m.get('series',{}).get('title'), f"S{m.get('seasonNumber')}E{m.get('episodeNumber')}", m.get("airDate")] for m in items],
        headers=["Series","Episode","Air Date"],
        tablefmt="github"
    )
    return f"📺 UPCOMING EPISODES (7 days)\n╾━━━━━━━━━━━━━━━━╼\n{table}", None

def count_movies():
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None
    return f"🎬 Total Movies: {len(radarr_cache['movies'])}", None

def count_series():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    return f"📺 Total Series: {len(sonarr_cache['series'])}", None

def longest_movie():
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None
    if not radarr_cache["movies"]:
        return "🎬 No cached movies", None
    longest = max(radarr_cache["movies"], key=lambda m: m.get("runtime",0))
    return f"🎬 Longest Movie: {longest.get('title')} ({longest.get('runtime')} min)", None

def longest_series():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    if not sonarr_cache["series"]:
        return "📺 No cached series", None
    longest = max(sonarr_cache["series"], key=lambda s: (s.get("seasonCount",0), s.get("episodeCount",0)))
    return f"📺 Longest Series: {longest.get('title')} ({longest.get('seasonCount')} seasons, {longest.get('episodeCount')} episodes)", None

# -----------------------------
# Fuzzy Command Router
# -----------------------------
def handle_arr_command(cmd: str):
    c = cmd.lower().strip()

    if "upcoming" in c and "movie" in c:
        return upcoming_movies()
    if "upcoming" in c and ("series" in c or "show" in c):
        return upcoming_series()
    if "how many" in c and "movie" in c:
        return count_movies()
    if "how many" in c and ("series" in c or "show" in c):
        return count_series()
    if "longest" in c and "movie" in c:
        return longest_movie()
    if "longest" in c and ("series" in c or "show" in c):
        return longest_series()

    return f"⚠️ Unknown Jarvis module command: {cmd}", None

# -----------------------------
# Scheduler for refreshing cache
# -----------------------------
def refresh_cache():
    if RADARR_ENABLED:
        cache_radarr()
    if SONARR_ENABLED:
        cache_sonarr()

def start_scheduler():
    schedule.every(60).minutes.do(refresh_cache)
    def run():
        while True:
            schedule.run_pending()
            time.sleep(1)
    t = threading.Thread(target=run, daemon=True)
    t.start()

# Start cache refresh loop on import
refresh_cache()
start_scheduler()
