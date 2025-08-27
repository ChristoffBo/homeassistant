# alias.py — Canonical command normalization for Jarvis Prime
# Drop this file at: /app/alias.py
# It will be auto-loaded by bot.py (no restart needed if container watches files; otherwise restart add-on)

import json, re, os

# Canonical intents Jarvis Prime understands
# Keep these EXACT so bot.py routes correctly.
CANON = {
    "dns",
    "kuma",
    "weather",
    "forecast",
    "upcoming_movies",
    "upcoming_series",
    "movie_count",
    "series_count",
    "longest_movie",
    "longest_series",
    "joke",
    "help",
    "commands",
}

# Built-in base aliases (case-insensitive)
BASE_ALIASES = {
    # DNS / Technitium
    "dns": "dns",
    "dns status": "dns",
    "dns stats": "dns",
    "tdns": "dns",
    "technitium": "dns",
    "tech dns": "dns",

    # Uptime Kuma
    "kuma": "kuma",
    "uptime": "kuma",
    "uptime kuma": "kuma",
    "status": "kuma",
    "monitors": "kuma",
    "monitor status": "kuma",

    # Weather
    "weather": "weather",
    "temp": "weather",
    "temps": "weather",
    "temperature": "weather",
    "now": "weather",
    "today": "weather",
    "current": "weather",
    "forecast": "forecast",
    "weekly": "forecast",
    "7day": "forecast",
    "7-day": "forecast",
    "7 day": "forecast",

    # ARR shortcuts (explicit)
    "movie count": "movie_count",
    "series count": "series_count",
    "show count": "series_count",
    "upcoming movies": "upcoming_movies",
    "upcoming series": "upcoming_series",
    "longest movie": "longest_movie",
    "longest series": "longest_series",
    "longest show": "longest_series",

    # Fun
    "joke": "joke",
    "pun": "joke",

    # Help
    "help": "help",
    "commands": "commands",
}

# Extra friendly synonyms the user asked for
FRIENDLY_SYNONYMS = {
    # Your examples: “films”, “tv”, “temps”
    "films": "upcoming_movies",         # “Jarvis films” -> upcoming movies
    "film": "upcoming_movies",
    "movies": "upcoming_movies",
    "movie": "upcoming_movies",
    "cinema": "upcoming_movies",

    "tv": "upcoming_series",            # “Jarvis tv” -> upcoming series
    "shows": "upcoming_series",
    "series": "upcoming_series",

    "temps": "weather",
    "temperature now": "weather",
    "weather now": "weather",
    "forecast week": "forecast",
}

def _clean(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    # normalize common punctuation at edges
    s = s.strip(" .,!?:;-/\\'\"()[]{}")
    return s

def _load_custom_aliases() -> dict:
    """
    Load user-defined custom aliases from /data/options.json.
    Format:
      {
        "custom_aliases": {
          "dns dns dns": "dns",
          "movies up": "upcoming_movies",
          "tv up": "upcoming_series",
          "temps": "weather"
        }
      }
    """
    try:
        with open("/data/options.json", "r") as f:
            obj = json.load(f)
            ca = obj.get("custom_aliases", {})
            # normalize keys & values
            out = {}
            for k, v in ca.items():
                ck = _clean(str(k))
                cv = _clean(str(v))
                out[ck] = cv
            return out
    except Exception:
        return {}

_CUSTOM = _load_custom_aliases()

def _keyword_rules(text: str) -> str | None:
    """
    Fallback keyword detection when no direct alias matches.
    Mirrors bot.py routing so we return the SAME canonical strings.
    """
    c = text

    # Counts
    if "count" in c and ("movie" in c or "film" in c): return "movie_count"
    if "count" in c and ("series" in c or "show" in c or "tv" in c): return "series_count"

    # Upcoming
    if ("up" in c or "upcoming" in c) and ("movie" in c or "film" in c): return "upcoming_movies"
    if ("up" in c or "upcoming" in c) and ("series" in c or "show" in c or "tv" in c): return "upcoming_series"

    # Longest
    if "longest" in c and "movie" in c: return "longest_movie"
    if "longest" in c and ("series" in c or "show" in c or "tv" in c): return "longest_series"

    # DNS / Kuma
    if "dns" in c or "technitium" in c: return "dns"
    if "kuma" in c or "uptime" in c or "monitor" in c: return "kuma"

    # Weather
    if "forecast" in c or "7 day" in c or "week" in c: return "forecast"
    if any(w in c for w in ("weather","temp","temps","temperature","now","today","current")): return "weather"

    return None

def normalize_cmd(raw: str) -> str:
    """
    Turn a free-form utterance (after wake word) into a canonical intent string.
    Priority:
      1) Exact match in custom aliases
      2) Exact match in base aliases
      3) Friendly synonyms (single-word shorthands)
      4) Keyword rules (fallback)
