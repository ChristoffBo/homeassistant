import os, requests, difflib, datetime
from tabulate import tabulate

# -----------------------------
# Config from environment (set via run.sh → options.json)
# -----------------------------
RADARR_ENABLED = os.getenv("radarr_enabled", "false").lower() in ("1", "true", "yes", "on")
RADARR_URL = os.getenv("radarr_url")
RADARR_KEY = os.getenv("radarr_api_key")

SONARR_ENABLED = os.getenv("sonarr_enabled", "false").lower() in ("1", "true", "yes", "on")
SONARR_URL = os.getenv("sonarr_url")
SONARR_KEY = os.getenv("sonarr_api_key")

# -----------------------------
# Helper functions
# -----------------------------
def human_size(num, suffix="B"):
    try:
        num = float(num)
        for unit in ["", "K", "M", "G", "T"]:
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f}P{suffix}"
    except Exception:
        return str(num)

def format_runtime(minutes):
    try:
        minutes = int(minutes)
        if minutes <= 0:
            return "?"
        h, m = divmod(minutes, 60)
        if h:
            return f"{h}h {m}m"
        return f"{m}m"
    except Exception:
        return "?"

def fetch_api(url, key):
    try:
        r = requests.get(url, headers={"X-Api-Key": key}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

# -----------------------------
# Radarr functions
# -----------------------------
def radarr_upcoming():
    if not RADARR_ENABLED:
        return "🎬 Radarr is disabled", None
    start = datetime.date.today()
    end = start + datetime.timedelta(days=7)
    data = fetch_api(f"{RADARR_URL}/api/v3/calendar?start={start}&end={end}", RADARR_KEY)
    if "error" in data:
        return f"⛔ Radarr error: {data['error']}", None
    if not data:
        return "🎬 No upcoming movies in the next 7 days.", None
    table = [[d.get("title"), d.get("inCinemas", "N/A")[:10], format_runtime(d.get("runtime", 0))] for d in data]
    msg = f"🎬 UPCOMING MOVIES (7 days)\n╾━━━━━━━━━━━━━━━━╼\n{tabulate(table, headers=['Title','In Cinemas','Runtime'], tablefmt='github')}"
    return msg, None

def radarr_count():
    data = fetch_api(f"{RADARR_URL}/api/v3/movie", RADARR_KEY)
    if "error" in data:
        return f"⛔ Radarr error: {data['error']}", None
    msg = f"🎬 You have **{len(data)} movies** in Radarr."
    return msg, None

def radarr_longest():
    data = fetch_api(f"{RADARR_URL}/api/v3/movie", RADARR_KEY)
    if "error" in data:
        return f"⛔ Radarr error: {data['error']}", None
    if not data:
        return "🎬 No movies in Radarr.", None
    longest = max(data, key=lambda x: x.get("runtime", 0))
    msg = f"🎬 LONGEST MOVIE\n╾━━━━━━━━━━━━━━━━╼\n{longest['title']} ({format_runtime(longest.get('runtime',0))})"
    return msg, None

# -----------------------------
# Sonarr functions
# -----------------------------
def sonarr_upcoming():
    if not SONARR_ENABLED:
        return "📺 Sonarr is disabled", None
    start = datetime.date.today()
    end = start + datetime.timedelta(days=7)
    data = fetch_api(f"{SONARR_URL}/api/v3/calendar?start={start}&end={end}", SONARR_KEY)
    if "error" in data:
        return f"⛔ Sonarr error: {data['error']}", None
    if not data:
        return "📺 No upcoming episodes in the next 7 days.", None
    table = [[d['series']['title'], f"S{d['seasonNumber']:02}E{d['episodeNumber']:02}", d.get("airDate","N/A")] for d in data]
    msg = f"📺 UPCOMING SERIES (7 days)\n╾━━━━━━━━━━━━━━━━╼\n{tabulate(table, headers=['Series','Episode','Air Date'], tablefmt='github')}"
    return msg, None

def sonarr_count():
    data = fetch_api(f"{SONARR_URL}/api/v3/series", SONARR_KEY)
    if "error" in data:
        return f"⛔ Sonarr error: {data['error']}", None
    msg = f"📺 You have **{len(data)} shows** in Sonarr."
    return msg, None

def sonarr_longest():
    data = fetch_api(f"{SONARR_URL}/api/v3/series", SONARR_KEY)
    if "error" in data:
        return f"⛔ Sonarr error: {data['error']}", None
    if not data:
        return "📺 No shows in Sonarr.", None
    longest = max(data, key=lambda x: (x.get("seasonCount",0), x.get("episodeCount",0)))
    msg = f"📺 LONGEST SERIES\n╾━━━━━━━━━━━━━━━━╼\n{longest['title']} → {longest.get('seasonCount',0)} seasons / {longest.get('episodeCount',0)} episodes"
    return msg, None

# -----------------------------
# Command router with fuzzy matching
# -----------------------------
COMMANDS = {
    "upcoming movies": radarr_upcoming,
    "how many movies": radarr_count,
    "longest movie": radarr_longest,
    "upcoming series": sonarr_upcoming,
    "how many shows": sonarr_count,
    "longest series": sonarr_longest,
}

def handle_arr_command(query):
    query = query.lower()
    matches = difflib.get_close_matches(query, COMMANDS.keys(), n=1, cutoff=0.5)
    if matches:
        return COMMANDS[matches[0]]()
    return None, None
