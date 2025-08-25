import os
import requests
import datetime
from tabulate import tabulate
import difflib
import json
import random

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
radarr_cache = {"movies": [], "by_id": {}, "fetched": None}
sonarr_cache = {"series": [], "by_id": {}, "fetched": None}

# -----------------------------
# Quotes
# -----------------------------
MOVIE_QUOTES = [
    "May the Force be with you.",
    "I'll be back.",
    "Here's looking at you, kid.",
    "You talking to me?",
    "I love the smell of napalm in the morning.",
    "Hasta la vista, baby.",
    "Show me the money!",
    "You can’t handle the truth!",
    "To infinity and beyond!",
    "Why so serious?",
    "I see dead people.",
    "E.T. phone home.",
    "You had me at hello.",
    "Just keep swimming.",
    "Life is like a box of chocolates.",
    "Say hello to my little friend!",
    "Bond. James Bond.",
    "They may take our lives, but they’ll never take our freedom!",
    "I feel the need—the need for speed!",
    "Houston, we have a problem.",
    "Frankly, my dear, I don’t give a damn.",
    "Nobody puts Baby in a corner.",
    "Keep your friends close, but your enemies closer.",
    "I’m king of the world!",
    "Wax on, wax off.",
    "They call it a Royale with Cheese.",
    "This is the beginning of a beautiful friendship.",
    "What we’ve got here is failure to communicate.",
    "Go ahead, make my day."
]

SERIES_QUOTES = [
    "I am the one who knocks.",
    "You come at the king, you best not miss.",
    "How you doin’?",
    "Winter is coming.",
    "The truth is out there.",
    "D’oh!",
    "That's what she said.",
    "Live long and prosper.",
    "Bazinga!",
    "This is the way.",
    "Say my name.",
    "Yada, yada, yada.",
    "Clear eyes, full hearts, can’t lose.",
    "Just one more thing...",
    "You got it, dude!",
    "Legend—wait for it—dary!",
    "Is that your final answer?",
    "You are the weakest link. Goodbye.",
    "We were on a break!",
    "It’s gonna be legen—wait for it—dary!",
    "The night is dark and full of terrors.",
    "This is Sparta! (okay, not a show, but fun)",
    "Who lives in a pineapple under the sea?",
    "Cowabunga!",
    "You rang?",
    "Allons-y!",
    "Geronimo!",
    "The cake is a lie.",
    "In the name of the Moon, I’ll punish you!",
    "Scooby-Doo, where are you?"
]

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

def _movie_quote():
    return random.choice(MOVIE_QUOTES)

def _series_quote():
    return random.choice(SERIES_QUOTES)

def _truthy(val, default=False):
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "y")
    return bool(val)

def _utc_iso(dt):
    # Return ISO8601 UTC Z string
    if isinstance(dt, datetime.datetime) and dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

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
        radarr_cache["by_id"] = {m.get("id"): m for m in data if isinstance(m, dict)}
        radarr_cache["fetched"] = datetime.datetime.now(datetime.timezone.utc)
    else:
        radarr_cache["movies"] = []
        radarr_cache["by_id"] = {}
        radarr_cache["fetched"] = None

def _radarr_movie_has_file_from_cache(movie_id):
    if not radarr_cache["by_id"]:
        cache_radarr()
    m = radarr_cache["by_id"].get(movie_id) if movie_id is not None else None
    if not m:
        return False
    return _truthy(m.get("hasFile"), False)

def upcoming_movies(days=7):
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None

    # Build time window explicitly (now .. now+days)
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=int(days))
    start_s = _utc_iso(now)
    end_s = _utc_iso(end)

    # Ask API to exclude unmonitored and include movie payloads
    url = (
        f"{RADARR_URL}/api/v3/calendar"
        f"?apikey={RADARR_API}&start={start_s}&end={end_s}"
        f"&unmonitored=false&includeMovie=true"
    )
    data = _get_json(url)
    if not isinstance(data, list) or not data:
        return "🎬 No upcoming movies", None

    lines = []
    kept = 0
    for m in data:
        movie_id = m.get("movie", {}).get("id") or m.get("id") or m.get("movieId")
        # Filter: skip if already downloaded
        if _radarr_movie_has_file_from_cache(movie_id):
            continue

        title = m.get("title") or m.get("movie", {}).get("title", "Unknown")
        year = m.get("year") or m.get("movie", {}).get("year", "")
        date = m.get("inCinemas") or m.get("physicalRelease") or m.get("releaseDate")
        try:
            if isinstance(date, str):
                date = datetime.datetime.fromisoformat(date.replace("Z", "+00:00"))
                date = date.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
        lines.append(f"- {title} ({year}) — {date}")
        kept += 1

    if kept == 0:
        return "🎬 No upcoming movies (all items already downloaded)", None

    commentary = f"🎬 {kept} upcoming movies in the next {days} days.\n{_movie_quote()}"
    return "🎬 Upcoming Movies\n" + "\n".join(lines) + f"\n{commentary}", None

def movie_count():
    if not RADARR_ENABLED:
        return "⚠️ Radarr not enabled", None
    if not radarr_cache["movies"]:
        cache_radarr()
    total = len(radarr_cache["movies"])
    commentary = "🎬 That’s quite a collection!" if total > 500 else "🎬 A modest library."
    return f"🎬 Total Movies: {total}\n{commentary}\n{_movie_quote()}", None

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
    commentary = "🎬 That’s a long one!" if runtime > 150 else "🎬 Pretty average runtime."
    return f"🎬 Longest Movie: {title} — {runtime} min\n{commentary}\n{_movie_quote()}", None

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
        sonarr_cache["by_id"] = {s.get("id"): s for s in data if isinstance(s, dict)}
        sonarr_cache["fetched"] = datetime.datetime.now(datetime.timezone.utc)
    else:
        sonarr_cache["series"] = []
        sonarr_cache["by_id"] = {}
        sonarr_cache["fetched"] = None

def _sonarr_episode_has_file(ep_obj):
    # Prefer direct field from calendar payload
    if isinstance(ep_obj, dict):
        if "hasFile" in ep_obj:
            return _truthy(ep_obj.get("hasFile"), False)
        ep_id = ep_obj.get("id")
        if ep_id:
            # Fallback: fetch episode to check hasFile (rare path)
            url = f"{SONARR_URL}/api/v3/episode/{ep_id}?apikey={SONARR_API}"
            data = _get_json(url)
            if isinstance(data, dict):
                return _truthy(data.get("hasFile"), False)
    return False

def upcoming_series(days=7):
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None

    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=int(days))
    start_s = _utc_iso(now)
    end_s = _utc_iso(end)

    # Ask API to exclude unmonitored and include series/episode data
    url = (
        f"{SONARR_URL}/api/v3/calendar"
        f"?apikey={SONARR_API}&start={start_s}&end={end_s}"
        f"&unmonitored=false&includeSeries=true&includeEpisode=true"
    )
    data = _get_json(url)
    if not isinstance(data, list) or not data:
        return "📺 No upcoming episodes", None

    lines = []
    kept = 0
    for e in data:
        # Skip if unmonitored (defensive even though we passed unmonitored=false)
        if not _truthy(e.get("monitored", True), True):
            continue
        # Skip if already has a file
        if _sonarr_episode_has_file(e):
            continue

        series = (e.get("series") or {}).get("title")
        if not series:
            sid = e.get("seriesId")
            cached = sonarr_cache["by_id"].get(sid, {}) if sid is not None else {}
            series = cached.get("title", "Unknown")

        ep = e.get("episodeNumber", "?")
        season = e.get("seasonNumber", "?")

        date = e.get("airDateUtc", "")
        try:
            if isinstance(date, str):
                date = datetime.datetime.fromisoformat(date.replace("Z", "+00:00"))
                date = date.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

        try:
            season_i = int(season)
        except Exception:
            season_i = 0
        try:
            ep_i = int(ep)
        except Exception:
            ep_i = 0

        lines.append(f"- {series} — S{season_i:02}E{ep_i:02} — {date}")
        kept += 1

    if kept == 0:
        return "📺 No upcoming episodes (all items already downloaded or unmonitored)", None

    commentary = f"📺 {kept} upcoming episodes in the next {days} days.\n{_series_quote()}"
    return "📺 Upcoming Episodes\n" + "\n".join(lines) + f"\n{commentary}", None

def series_count():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    if not sonarr_cache["series"]:
        cache_sonarr()
    total = len(sonarr_cache["series"])
    commentary = "📺 That’s a huge collection of shows!" if total > 200 else "📺 Not too many series yet."
    return f"📺 Total Series: {total}\n{commentary}\n{_series_quote()}", None

def longest_series():
    if not SONARR_ENABLED:
        return "⚠️ Sonarr not enabled", None
    if not sonarr_cache["series"]:
        cache_sonarr()
    if not sonarr_cache["series"]:
        return "⚠️ No series in cache", None

    def series_length(s):
        episodes = s.get("statistics", {}).get("episodeCount") or s.get("totalEpisodeCount", 0) or 0
        return episodes

    longest = max(sonarr_cache["series"], key=series_length)
    title = longest.get("title", "Unknown")
    seasons = longest.get("seasonCount", "?")
    episodes = longest.get("statistics", {}).get("episodeCount") or longest.get("totalEpisodeCount", "?")

    commentary = f"📺 Wow, {title} has {episodes} episodes across {seasons} seasons!" if episodes not in ("?", 0) else "📺 Couldn’t determine full stats."
    return f"📺 Longest Series: {title} — {seasons} seasons, {episodes} episodes\n{commentary}\n{_series_quote()}", None

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