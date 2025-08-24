import os
import requests
import datetime
from tabulate import tabulate
import difflib
import json

# -----------------------------
# Config from environment
# -----------------------------
RADARR_URL = os.getenv("radarr_url", "")
RADARR_API = os.getenv("radarr_api_key", "")
SONARR_URL = os.getenv("sonarr_url", "")
SONARR_API = os.getenv("sonarr_api_key", "")

RADARR_ENABLED = os.getenv("radarr_enabled", "false").lower() in ("1", "true", "yes")
SONARR_ENABLED = os.getenv("sonarr_enabled", "false").lower() in ("1", "true", "yes")

# -----------------------------
# Load Home Assistant options.json (overrides env)
# -----------------------------
try:
    with open("/data/options.json", "r") as f:
        options = json.load(f)
        RADARR_ENABLED = options.get("radarr_enabled", RADARR_ENABLED)
        SONARR_ENABLED = options.get("sonarr_enabled", SONARR_ENABLED)
        RADARR_URL = options.get("radarr_url", RADARR_URL)
        RADARR_API = options.get("radarr_api_key", RADARR_API)
        SONARR_URL = options.get("sonarr_url", SONARR_URL)
        SONARR_API = options.get("sonarr_api_key", SONARR_API)
except Exception as e:
    print(f"[ARR] ⚠️ Could not load options.json: {e}")

# -----------------------------
# Caches
# -----------------------------
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
    if not radarr_cache["movies"]:
        cache_radarr()
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

    lines = []
    for e in data:
        series = e.get("series", {}).get("title")
        if not series:
            # fallback: lookup in cache
            sid = e.get("seriesId")
            cached = next((s for s in sonarr_cache["series"] if s.get("id") == sid), {})
            series = cached.get("title", "Unknown")

        ep = e.get("episodeNumber", "?")
        season = e.get("seasonNumber", "?")

        date = e.get("airDateUtc", "")
        try:
            date = datetime.datetime.fromisoformat(date.replace("Z", "+00:00"))
            date = date.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

        lines.append(f"- {series} — S{season:02}E{ep:02} — {date}")

    return "📺 Upcoming Episodes\n" + "\n".join(lines), None

def series_count():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    if not sonarr_cache["series"]:
        cache_sonarr()
    return f"📺 Total Series: {len(sonarr_cache['series'])}", None

def longest_series():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    if not sonarr_cache["series"]:
        cache_sonarr()
    if not sonarr_cache["series"]:
        return "⚠️ No series in cache", None
    longest = max(
        sonarr_cache["series"],
        key=lambda s: (s.get("seasonCount", 0) * s.get("episodeCount", 0))
    )
    title = longest.get("title", "Unknown")
    seasons = longest.get("seasonCount", "?")
    episodes = longest.get("episodeCount", "?")
    return f"📺 Longest Series: {title} — {seasons} seasons, {episodes} episodes", None

# -----------------------------
# Command Router
# -----------------------------
ALIASES = {
    "movies count": "movie_count",
    "how many movies": "movie_count",
    "movie count": "movie_count",
    "shows count": "series_count",
    "how many shows": "series_count",
    "series count": "series_count",
    "longest film": "longest_movie",
    "longest movie": "longest_movie",
    "longest series": "longest_series",
    "longest show": "longest_series",
    "upcoming movies": "upcoming_movies",
    "upcoming movie": "upcoming_movies",
    "upcoming shows": "upcoming_series",
    "upcoming series": "upcoming_series",
}

COMMANDS = {
    "movie_count": movie_count,
    "series_count": series_count,
    "longest_movie": longest_movie,
    "longest_series": longest_series,
    "upcoming_movies": upcoming_movies,
    "upcoming_series": upcoming_series,
}

def handle_arr_command(title: str, message: str):
    # merge into a single command string
    cmd = f"{title} {message}".lower().strip()

    if cmd.startswith("jarvis jnr"):
        cmd = cmd.replace("jarvis jnr", "", 1).strip()
    elif cmd.startswith("jarvis"):
        cmd = cmd.replace("jarvis", "", 1).strip()
    if cmd.startswith("message"):
        cmd = cmd.replace("message", "", 1).strip()

    if cmd in ALIASES:
        cmd = ALIASES[cmd]

    if cmd in COMMANDS:
        return COMMANDS[cmd]()

    possibilities = list(COMMANDS.keys()) + list(ALIASES.keys())
    match = difflib.get_close_matches(cmd, possibilities, n=1, cutoff=0.6)
    if match:
        mapped = ALIASES.get(match[0], match[0])
        return COMMANDS[mapped]()

    return f"🤖 Unknown command: {cmd}", None
