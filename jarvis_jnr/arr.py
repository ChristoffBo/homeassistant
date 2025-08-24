import os
import requests
import datetime
from tabulate import tabulate

# -----------------------------
# Config from environment
# -----------------------------
RADARR_URL = os.getenv("RADARR_URL", "")
RADARR_API = os.getenv("RADARR_API", "")
SONARR_URL = os.getenv("SONARR_URL", "")
SONARR_API = os.getenv("SONARR_API", "")

RADARR_ENABLED = bool(RADARR_URL and RADARR_API)
SONARR_ENABLED = bool(SONARR_URL and SONARR_API)

radarr_cache = {"movies": [], "fetched": None}
sonarr_cache = {"series": [], "fetched": None}

# -----------------------------
# Helpers
# -----------------------------
def _get_json(url):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def _tabulate_list(items, headers):
    return tabulate(items, headers=headers, tablefmt="github")

# -----------------------------
# Radarr functions
# -----------------------------
def cache_radarr():
    global radarr_cache
    if not RADARR_ENABLED:
        return
    url = f"{RADARR_URL}/api/v3/movie?apikey={RADARR_API}"
    data = _get_json(url)
    if isinstance(data, list):
        radarr_cache["movies"] = data
        radarr_cache["fetched"] = datetime.datetime.now()
    else:
        radarr_cache["movies"] = []
        radarr_cache["fetched"] = None

def upcoming_movies(days=7):
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None
    url = f"{RADARR_URL}/api/v3/calendar?apikey={RADARR_API}&days={days}"
    data = _get_json(url)
    if not isinstance(data, list) or not data:
        return "🎬 No upcoming movies", None
    rows = []
    for m in data:
        title = m.get("title", "Unknown")
        year = m.get("year", "")
        date = m.get("inCinemas") or m.get("physicalRelease")
        rows.append([title, year, date])
    return "🎬 Upcoming Movies\n" + _tabulate_list(rows, ["Title", "Year", "Release"]), None

def movie_count():
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None
    return f"🎬 Total Movies: {len(radarr_cache['movies'])}", None

def longest_movie():
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None
    if not radarr_cache["movies"]:
        cache_radarr()
    if not radarr_cache["movies"]:
        return "⚠️ No movies in cache", None
    longest = max(radarr_cache["movies"], key=lambda m: m.get("runtime", 0) or 0)
    title = longest.get("title", "Unknown")
    runtime = longest.get("runtime", 0)
    return f"🎬 Longest Movie: {title} — {runtime} min", None

# -----------------------------
# Sonarr functions
# -----------------------------
def cache_sonarr():
    global sonarr_cache
    if not SONARR_ENABLED:
        return
    url = f"{SONARR_URL}/api/v3/series?apikey={SONARR_API}"
    data = _get_json(url)
    if isinstance(data, list):
        sonarr_cache["series"] = data
        sonarr_cache["fetched"] = datetime.datetime.now()
    else:
        sonarr_cache["series"] = []
        sonarr_cache["fetched"] = None

def upcoming_series(days=7):
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    url = f"{SONARR_URL}/api/v3/calendar?apikey={SONARR_API}&days={days}"
    data = _get_json(url)
    if not isinstance(data, list) or not data:
        return "📺 No upcoming episodes", None
    rows = []
    for e in data:
        series = e.get("series", {}).get("title", "Unknown")
        ep = e.get("episodeNumber", "?")
        season = e.get("seasonNumber", "?")
        date = e.get("airDateUtc", "")
        rows.append([series, f"S{season:02}E{ep:02}", date])
    return "📺 Upcoming Episodes\n" + _tabulate_list(rows, ["Series", "Episode", "Air Date"]), None

def series_count():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    return f"📺 Total Series: {len(sonarr_cache['series'])}", None

def longest_series():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    if not sonarr_cache["series"]:
        cache_sonarr()
    if not sonarr_cache["series"]:
        return "⚠️ No series in cache", None
    longest = max(sonarr_cache["series"], key=lambda s: (s.get("seasonCount", 0) * s.get("episodeCount", 0)))
    title = longest.get("title", "Unknown")
    seasons = longest.get("seasonCount", "?")
    episodes = longest.get("episodeCount", "?")
    return f"📺 Longest Series: {title} — {seasons} seasons, {episodes} episodes", None

# -----------------------------
# Command Router (additive fix: check both title and message)
# -----------------------------
def handle_arr_command(command: str, title: str = ""):
    cmd = f"{title} {command}".lower().strip()
    if "upcoming movie" in cmd:
        return upcoming_movies()
    if "upcoming series" in cmd or "upcoming show" in cmd:
        return upcoming_series()
    if "how many movie" in cmd:
        return movie_count()
    if "how many show" in cmd or "how many series" in cmd:
        return series_count()
    if "longest movie" in cmd:
        return longest_movie()
    if "longest series" in cmd or "longest show" in cmd:
        return longest_series()
    return f"🤖 Unknown command: {command}", None
