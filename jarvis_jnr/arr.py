import os
import requests
import datetime
import difflib
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

def _normalize_command(title: str, message: str) -> str:
    """Combine title+message, normalize to lowercase for command parsing."""
    combined = f"{title} {message}".lower()
    return combined.strip()

def _fuzzy_match(cmd: str, keywords: list, cutoff: float = 0.75) -> bool:
    """Return True if cmd is close enough to any keyword."""
    for keyword in keywords:
        ratio = difflib.SequenceMatcher(None, cmd, keyword).ratio()
        if ratio >= cutoff or keyword in cmd:
            return True
    return False

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
# Command Router
# -----------------------------
def handle_arr_command(title: str, message: str):
    cmd = _normalize_command(title, message)

    if _fuzzy_match(cmd, ["upcoming movie", "movies upcoming"]):
        return upcoming_movies()
    if _fuzzy_match(cmd, ["upcoming series", "upcoming show", "shows upcoming"]):
        return upcoming_series()
    if _fuzzy_match(cmd, ["how many movie", "movie count", "total movies", "movies count"]):
        return movie_count()
    if _fuzzy_match(cmd, ["how many show", "how many series", "series count", "total series", "shows count"]):
        return series_count()
    if _fuzzy_match(cmd, ["longest movie", "longest movies"]):
        return longest_movie()
    if _fuzzy_match(cmd, ["longest series", "longest show", "longest shows", "longest tv"]):
        return longest_series()

    return None, None
