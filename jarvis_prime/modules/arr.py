import os
import requests
import datetime
from tabulate import tabulate
import json
import random
import re

# Fuzzy matcher (RapidFuzz is in requirements.txt)
try:
    from rapidfuzz import process, fuzz
except Exception:
    # Soft fallback if RF isn’t available
    process = None
    fuzz = None

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
    "May the Force be with you.","I'll be back.","Here's looking at you, kid.","You talking to me?",
    "I love the smell of napalm in the morning.","Hasta la vista, baby.","Show me the money!",
    "You can’t handle the truth!","To infinity and beyond!","Why so serious?","I see dead people.",
    "E.T. phone home.","You had me at hello.","Just keep swimming.","Life is like a box of chocolates.",
    "Say hello to my little friend!","Bond. James Bond.","They may take our lives, but they’ll never take our freedom!",
    "I feel the need—the need for speed!","Houston, we have a problem."
]
SERIES_QUOTES = [
    "I am the one who knocks.","You come at the king, you best not miss.","How you doin’?",
    "Winter is coming.","The truth is out there.","D’oh!","That's what she said.","Live long and prosper.",
    "Bazinga!","This is the way.","Say my name.","Yada, yada, yada."
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

def _movie_quote():  return random.choice(MOVIE_QUOTES)
def _series_quote(): return random.choice(SERIES_QUOTES)

def _truthy(val, default=False):
    if val is None: return default
    if isinstance(val, bool): return val
    if isinstance(val, (int, float)): return val != 0
    if isinstance(val, str): return val.strip().lower() in ("1","true","yes","y")
    return bool(val)

def _utc_iso(dt):
    if isinstance(dt, datetime.datetime) and dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

# -----------------------------
# Radarr
# -----------------------------
def cache_radarr():
    global radarr_cache
    if not RADARR_ENABLED: return
    data = _get_json(f"{RADARR_URL}/api/v3/movie?apikey={RADARR_API}")
    if isinstance(data, list):
        radarr_cache["movies"] = data
        radarr_cache["by_id"] = {m.get("id"): m for m in data if isinstance(m, dict)}
        radarr_cache["fetched"] = datetime.datetime.now(datetime.timezone.utc)
    else:
        radarr_cache = {"movies": [], "by_id": {}, "fetched": None}

def _radarr_movie_has_file_from_cache(movie_id):
    if not radarr_cache["by_id"]: cache_radarr()
    m = radarr_cache["by_id"].get(movie_id) if movie_id is not None else None
    return _truthy(m.get("hasFile"), False) if m else False

def upcoming_movies(days=7):
    if not RADARR_ENABLED: return "⚠️ Radarr not enabled", None
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=int(days))
    url = (f"{RADARR_URL}/api/v3/calendar?apikey={RADARR_API}"
           f"&start={_utc_iso(now)}&end={_utc_iso(end)}&unmonitored=false&includeMovie=true")
    data = _get_json(url)
    if not isinstance(data, list) or not data: return "🎬 No upcoming movies", None

    lines, kept = [], 0
    for m in data:
        mid = m.get("movie", {}).get("id") or m.get("id") or m.get("movieId")
        if _radarr_movie_has_file_from_cache(mid): continue
        title = m.get("title") or m.get("movie", {}).get("title", "Unknown")
        year  = m.get("year") or m.get("movie", {}).get("year", "")
        date  = m.get("inCinemas") or m.get("physicalRelease") or m.get("releaseDate")
        try:
            if isinstance(date, str):
                date = datetime.datetime.fromisoformat(date.replace("Z","+00:00")).strftime("%Y-%m-%d %H:%M")
        except Exception: pass
        lines.append(f"- {title} ({year}) — {date}"); kept += 1

    if kept == 0: return "🎬 No upcoming movies (all items already downloaded)", None
    return "🎬 Upcoming Movies\n" + "\n".join(lines) + f"\n🎬 {kept} in next {days} days.\n{_movie_quote()}", None

def movie_count():
    if not RADARR_ENABLED: return "⚠️ Radarr not enabled", None
    if not radarr_cache["movies"]: cache_radarr()
    total = len(radarr_cache["movies"])
    note = "🎬 That’s quite a collection!" if total > 500 else "🎬 A modest library."
    return f"🎬 Total Movies: {total}\n{note}\n{_movie_quote()}", None

def longest_movie():
    if not RADARR_ENABLED: return "⚠️ Radarr not enabled", None
    if not radarr_cache["movies"]: cache_radarr()
    if not radarr_cache["movies"]: return "⚠️ No movies in cache", None
    longest = max(radarr_cache["movies"], key=lambda m: m.get("runtime",0) or 0)
    title = longest.get("title","Unknown"); runtime = longest.get("runtime",0)
    note = "🎬 That’s a long one!" if runtime > 150 else "🎬 Pretty average runtime."
    return f"🎬 Longest Movie: {title} — {runtime} min\n{note}\n{_movie_quote()}", None

# -----------------------------
# Sonarr
# -----------------------------
def cache_sonarr():
    global sonarr_cache
    if not SONARR_ENABLED: return
    data = _get_json(f"{SONARR_URL}/api/v3/series?apikey={SONARR_API}")
    if isinstance(data, list):
        sonarr_cache["series"] = data
        sonarr_cache["by_id"] = {s.get("id"): s for s in data if isinstance(s, dict)}
        sonarr_cache["fetched"] = datetime.datetime.now(datetime.timezone.utc)
    else:
        sonarr_cache = {"series": [], "by_id": {}, "fetched": None}

def _sonarr_episode_has_file(ep_obj):
    if not isinstance(ep_obj, dict): return False
    if "hasFile" in ep_obj: return _truthy(ep_obj.get("hasFile"), False)
    ep_id = ep_obj.get("id")
    if ep_id:
        data = _get_json(f"{SONARR_URL}/api/v3/episode/{ep_id}?apikey={SONARR_API}")
        if isinstance(data, dict): return _truthy(data.get("hasFile"), False)
    return False

def upcoming_series(days=7):
    if not SONARR_ENABLED: return "⚠️ Sonarr not enabled", None
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=int(days))
    url = (f"{SONARR_URL}/api/v3/calendar?apikey={SONARR_API}"
           f"&start={_utc_iso(now)}&end={_utc_iso(end)}&unmonitored=false&includeSeries=true&includeEpisode=true")
    data = _get_json(url)
    if not isinstance(data, list) or not data: return "📺 No upcoming episodes", None

    lines, kept = [], 0
    for e in data:
        if not _truthy(e.get("monitored", True), True): continue
        if _sonarr_episode_has_file(e): continue
        series = (e.get("series") or {}).get("title")
        if not series:
            sid = e.get("seriesId")
            cached = sonarr_cache["by_id"].get(sid, {}) if sid is not None else {}
            series = cached.get("title","Unknown")
        ep = e.get("episodeNumber","?"); season = e.get("seasonNumber","?")
        date = e.get("airDateUtc","")
        try:
            if isinstance(date,str):
                date = datetime.datetime.fromisoformat(date.replace("Z","+00:00")).strftime("%Y-%m-%d %H:%M")
        except Exception: pass
        try: season_i = int(season)
        except Exception: season_i = 0
        try: ep_i = int(ep)
        except Exception: ep_i = 0
        lines.append(f"- {series} — S{season_i:02}E{ep_i:02} — {date}"); kept += 1

    if kept == 0: return "📺 No upcoming episodes (all items already downloaded or unmonitored)", None
    return "📺 Upcoming Episodes\n" + "\n".join(lines) + f"\n📺 {kept} in next {days} days.\n{_series_quote()}", None

def series_count():
    if not SONARR_ENABLED: return "⚠️ Sonarr not enabled", None
    if not sonarr_cache["series"]: cache_sonarr()
    total = len(sonarr_cache["series"])
    note = "📺 That’s a huge collection of shows!" if total > 200 else "📺 Not too many series yet."
    return f"📺 Total Series: {total}\n{note}\n{_series_quote()}", None

def longest_series():
    if not SONARR_ENABLED: return "⚠️ Sonarr not enabled", None
    if not sonarr_cache["series"]: cache_sonarr()
    if not sonarr_cache["series"]: return "⚠️ No series in cache", None

    def series_length(s):
        return s.get("statistics", {}).get("episodeCount") or s.get("totalEpisodeCount", 0) or 0

    longest = max(sonarr_cache["series"], key=series_length)
    title = longest.get("title","Unknown")
    seasons = longest.get("seasonCount","?")
    episodes = longest.get("statistics", {}).get("episodeCount") or longest.get("totalEpisodeCount","?")
    note = f"📺 Wow, {title} has {episodes} episodes across {seasons} seasons!" if episodes not in ("?",0) else "📺 Couldn’t determine full stats."
    return f"📺 Longest Series: {title} — {seasons} seasons, {episodes} episodes\n{note}\n{_series_quote()}", None

# -----------------------------
# Command Router (very tolerant)
# -----------------------------

COMMANDS = {
    "movie_count": movie_count,
    "series_count": series_count,
    "longest_movie": longest_movie,
    "longest_series": longest_series,
    "upcoming_movies": upcoming_movies,
    "upcoming_series": upcoming_series,
}

# Canonical phrases per command (add spellings & variants)
PHRASES = {
    "movie_count": [
        "movie count","movies count","how many movies","how many movis","how many mvoies"
    ],
    "series_count": [
        "series count","shows count","how many series","how many shows","how many shos"
    ],
    "longest_movie": [
        "longest movie","longest film","longest movy","longest moive"
    ],
    "longest_series": [
        "longest series","longest show","longest shows","longest seris"
    ],
    "upcoming_movies": [
        "upcoming movies","upcoming movie","movies upcoming","movie upcoming",
        "next movies","next movie","upcomming movies","upcomin movies","upcomng movies"
    ],
    "upcoming_series": [
        "upcoming series","upcoming shows","series upcoming","shows upcoming",
        "next series","next show","upcomming series","upcomin series","upcomng series"
    ],
}

# Build reverse lookup for fuzzy search
ALL_CANDIDATES = []
for key, arr in PHRASES.items():
    for p in arr:
        ALL_CANDIDATES.append((p, key))

def _normalize(text: str) -> str:
    t = (text or "").lower().strip()
    # Strip wake words at the start if present
    for head in ("jarvis jnr","jarvis prime","jarvis","message"):
        if t.startswith(head):
            t = t[len(head):].strip()
    # Remove punctuation, collapse spaces
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _fuzzy_route(cmd: str):
    """
    Use RapidFuzz (if available) to map to the closest phrase with a tolerant threshold.
    """
    if not process:
        return None, 0
    choices = [c[0] for c in ALL_CANDIDATES]
    match, score, idx = process.extractOne(cmd, choices, scorer=fuzz.QRatio) if choices else (None, 0, None)
    if match and score >= 70:  # tolerance: accepts mild misspellings
        return ALL_CANDIDATES[idx][1], score
    return None, 0

def handle_arr_command(title: str, message: str):
    # Merge → normalize
    raw = f"{title or ''} {message or ''}".strip()
    cmd = _normalize(raw)

    # Direct exact search first
    for key, phrases in PHRASES.items():
        if cmd in phrases:
            return COMMANDS[key]()

    # Regex shortcuts
    if re.search(r"\b(next|upcoming)\s+(movie|movies)\b", cmd):  return COMMANDS["upcoming_movies"]()
    if re.search(r"\b(next|upcoming)\s+(series|show|shows)\b", cmd): return COMMANDS["upcoming_series"]()
    if re.search(r"\b(movie|movies)\s+count\b", cmd): return COMMANDS["movie_count"]()
    if re.search(r"\b(series|shows)\s+count\b", cmd): return COMMANDS["series_count"]()
    if re.search(r"\blongest\s+(movie|film)\b", cmd): return COMMANDS["longest_movie"]()
    if re.search(r"\blongest\s+(series|show)\b", cmd): return COMMANDS["longest_series"]()

    # Fuzzy fallback (handles typos like “upcomin movis”)
    mapped, score = _fuzzy_route(cmd)
    if mapped:
        return COMMANDS[mapped]()

    return f"🤖 Unknown command: {cmd}", None

# -----------------------------
# NEW: helpers for heartbeat (safe; no routing change)
# -----------------------------
def list_upcoming_movies(days=1, limit=3):
    """
    Returns a short list of strings for movies releasing in the next `days` (default 1 = today),
    excluding items that already have files. Does not post, just returns lines.
    """
    if not RADARR_ENABLED:
        return []
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + datetime.timedelta(days=int(days))
    url = (f"{RADARR_URL}/api/v3/calendar?apikey={RADARR_API}"
           f"&start={_utc_iso(start)}&end={_utc_iso(end)}&unmonitored=false&includeMovie=true")
    data = _get_json(url)
    if not isinstance(data, list) or not data:
        return []
    if not radarr_cache["movies"]:
        cache_radarr()
    out = []
    for m in data:
        mid = m.get("movie", {}).get("id") or m.get("id") or m.get("movieId")
        if _radarr_movie_has_file_from_cache(mid):
            continue
        title = m.get("title") or m.get("movie", {}).get("title", "Unknown")
        year  = m.get("year") or m.get("movie", {}).get("year", "")
        date  = m.get("inCinemas") or m.get("physicalRelease") or m.get("releaseDate")
        try:
            if isinstance(date, str):
                dt = datetime.datetime.fromisoformat(date.replace("Z","+00:00"))
                date = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
        out.append(f"{title} ({year}) — {date}")
        if len(out) >= int(limit):
            break
    return out

def list_upcoming_series(days=1, limit=5):
    """
    Returns a short list of strings for episodes airing in the next `days` (default 1 = today),
    excluding already-downloaded / unmonitored. Does not post, just returns lines.
    """
    if not SONARR_ENABLED:
        return []
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + datetime.timedelta(days=int(days))
    url = (f"{SONARR_URL}/api/v3/calendar?apikey={SONARR_API}"
           f"&start={_utc_iso(start)}&end={_utc_iso(end)}&unmonitored=false&includeSeries=true&includeEpisode=true")
    data = _get_json(url)
    if not isinstance(data, list) or not data:
        return []
    if not sonarr_cache["series"]:
        cache_sonarr()
    out = []
    for e in data:
        if not _truthy(e.get("monitored", True), True):
            continue
        if _sonarr_episode_has_file(e):
            continue
        series = (e.get("series") or {}).get("title")
        if not series:
            sid = e.get("seriesId")
            cached = sonarr_cache["by_id"].get(sid, {}) if sid is not None else {}
            series = cached.get("title","Unknown")
        ep = e.get("episodeNumber","?"); season = e.get("seasonNumber","?")
        date = e.get("airDateUtc","")
        try:
            if isinstance(date,str):
                dt = datetime.datetime.fromisoformat(date.replace("Z","+00:00"))
                date = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
        try: season_i = int(season)
        except Exception: season_i = 0
        try: ep_i = int(ep)
        except Exception: ep_i = 0
        out.append(f"{series} — S{season_i:02}E{ep_i:02} — {date}")
        if len(out) >= int(limit):
            break
    return out
